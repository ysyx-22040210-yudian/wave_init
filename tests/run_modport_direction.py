#!/usr/bin/env python3
"""Real NPI declaration direction and queries before a late 60us FSDB start.

Two controlled API degradations emulate variants of older Verdi metadata.
The real elaborated objects, waveforms and member directions remain in use.
"""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from waveinit import __version__


def run(argv, cwd, log, expect=0):
    with log.open("w", encoding="utf-8") as stream:
        proc = subprocess.run([str(a) for a in argv], cwd=str(cwd), stdout=stream,
                              stderr=subprocess.STDOUT, timeout=120)
    if proc.returncode != expect:
        raise AssertionError(log.read_text(encoding="utf-8", errors="replace")[-8000:])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cli", help="optional frozen executable")
    parser.add_argument("--baseline-backend", help="optional 1.3.3 backend to reproduce loss of direction")
    args = parser.parse_args()
    cli = [args.cli, "--cli"] if args.cli else [sys.executable, str(ROOT/"wave_init.py")]
    work = Path(tempfile.mkdtemp(prefix="modport_direction_", dir=str(ROOT/"build")))
    print("EVIDENCE " + str(work), flush=True)
    verdi = Path(os.environ["VERDI_HOME"])
    sources = [ROOT/"tests/fixtures/modport_direction"/name for name in ("bus.sv", "dut.sv", "tb.sv")]
    run(["vcs", "-full64", "-sverilog", "-debug_access+all", "-kdb", "-lca", "-P",
         verdi/"share/PLI/VCS/LINUX64/novas.tab", verdi/"share/PLI/VCS/LINUX64/pli.a"] + sources +
        ["-top", "direction_top", "-o", "simv"], work, work/"compile.log")
    for name, flags in (("full", []), ("late", ["+LATE"])):
        dump = work/name
        dump.mkdir()
        run([work/"simv"]+flags, dump, dump/"simulation.log")
    results = []
    def extract(name, scope="direction_top.u_wrap.dut", when="1us", dump="full", extra=(), expect=0):
        out = work/name
        run(cli + ["--fsdb", work/dump/"waves.fsdb", "--kdb", work/"simv.daidir",
                   "--scope", scope, "--time", when, "--out", out] + list(extra),
            ROOT, work/(name+".console.log"), expect)
        report = json.loads((out/"snapshot.json").read_text(encoding="utf-8"))
        results.append({"case": name, "status": "pass", "exit_code": expect,
                        "time": when, "tick": report["tick"], "min_tick": report["min_tick"],
                        "directions_complete": report["directions_complete"], "signals": len(report["signals"])})
        return report

    slave = {"xxx.clk": ("input", "1"), "xxx.req": ("input", "1"),
             "xxx.data": ("input", "10xz0101"), "xxx.pad": ("inout", "z")}
    master = {"xxx.clk": ("input", "1"), "xxx.ack": ("input", "0"), "xxx.pad": ("inout", "z")}
    def check(report, expected, role, source="formal_npiDefName"):
        rows = {r["logical_path"][len(report["scope"])+1:]: (r["direction"], r["value_bin"]) for r in report["signals"]}
        assert rows == expected, rows
        assert all(r["modport"] == role for r in report["signals"])
        assert report["directions_complete"]
        assert report["bindings"][0]["modport_source"] == source
    for when in ("0us", "1ns", "1us", "59.999us"):
        check(extract("early_"+when, when=when), slave, "slv")
    check(extract("master", scope="direction_top.u_wrap.master"), master, "mst")
    later = dict(slave)
    later.update({"xxx.req": ("input", "0"), "xxx.data": ("input", "z01x1010")})
    check(extract("at_60us", when="60us"), later, "slv")
    check(extract("after_60us", when="60.001us"), later, "slv")
    for when in ("0us", "1us", "59.999us"):
        report = extract("before_dump_"+when, when=when, dump="late", expect=2)
        assert int(report["tick"]) < int(report["min_tick"])
        assert all(r["direction"] in ("input", "inout") and r["status"] == "no_initial_value" and
                   r["value_bin"] is None for r in report["signals"])
    check(extract("late_at_60us", when="60us", dump="late"), later, "slv")

    # Remove only the modport type from the formal npiActual reference. The
    # formal npiDefName still says a.slv/a.mst; old code exported all as unknown.
    hooks = r'''
rename wi::r wi::original_r
proc wi::r {h kind} {
    if {$kind eq "npiActual" && [wi::s $h npiFullName] in {
        direction_top.u_wrap.dut.xxx direction_top.u_wrap.master.xxx
    }} {return [wi::byname direction_top.link]}
    return [wi::original_r $h $kind]
}
'''
    numeric_hook = r'''
rename wi::s wi::original_s
proc wi::s {h property} {
    if {$property eq "npiDirection" && [wi::original_s $h npiType] eq "npiMpPort"} {return npiUndefined}
    return [wi::original_s $h $property]
}
'''
    def wrapper(name, backend, hook):
        script = work/(name+".tcl")
        script.write_text('set env(WI_LIBRARY_ONLY) 1\nsource {'+str(backend)+'}\n'+hook+r'''
set wi::output [open $env(WI_RESULT) w]
fconfigure $wi::output -encoding utf-8 -translation lf
if {[info exists env(WI_TRACE)]} {
    set wi::trace_file [open $env(WI_TRACE) w]
    fconfigure $wi::trace_file -encoding utf-8 -translation lf
}
if {[catch {wi::main} why options]} {
    wi::emit [wi::obj kind [wi::j fatal] message [wi::j $why] detail [wi::j [dict get $options -errorinfo]]]
}
close $wi::output
if {$wi::trace_file ne ""} {close $wi::trace_file}
debExit
''', encoding="utf-8")
        executable = work/(name+".sh")
        executable.write_text("#!/bin/sh\nexec "+shlex.quote(str(verdi/"bin/verdi"))+" -batch -nologo -play "+shlex.quote(str(script))+"\n")
        executable.chmod(0o755)
        return executable
    current = ROOT/"backend/snapshot.tcl"
    if args.baseline_backend:
        vendor = wrapper("baseline_proxy", args.baseline_backend, hooks)
        old = extract("baseline_unknown", extra=("--verdi", str(vendor)))
        assert all(r["direction"] == "unknown" for r in old["signals"])
        assert all(r["status"] == "ok" for r in old["signals"])
    vendor = wrapper("proxy", current, hooks)
    check(extract("proxy_slv", extra=("--verdi", str(vendor))), slave, "slv")
    check(extract("proxy_mst", scope="direction_top.u_wrap.master", extra=("--verdi", str(vendor))), master, "mst")
    typespec_hook = hooks + r'''
rename wi::s wi::original_s
proc wi::s {h property} {
    if {$property eq "npiDefName" && [wi::original_s $h npiType] eq "npiPort" &&
        [wi::original_s $h npiName] eq "xxx"} {return a}
    return [wi::original_s $h $property]
}
'''
    vendor = wrapper("typespec", current, typespec_hook)
    check(extract("typespec_slv", extra=("--verdi", str(vendor))), slave, "slv", "formal_typespec")
    check(extract("typespec_mst", scope="direction_top.u_wrap.master", extra=("--verdi", str(vendor))), master, "mst", "formal_typespec")
    vendor = wrapper("numeric", current, numeric_hook)
    check(extract("numeric_slv", extra=("--verdi", str(vendor))), slave, "slv")
    check(extract("numeric_mst", scope="direction_top.u_wrap.master", extra=("--verdi", str(vendor))), master, "mst")
    filelist = work/"design.f"
    filelist.write_text("".join(str(s)+"\n" for s in sources))
    for name in ("proxy_slv", "proxy_mst", "numeric_slv"):
        run(["bash", work/name/"run_vcs.sh", filelist], ROOT, work/(name+".replay.log"))
        assert "WAVE_INIT_SNAPSHOT_PASS" in (work/(name+".replay.log")).read_text()
    proof = {"status": "pass", "tool_version": __version__, "cases": results,
             "vcs_assign_replays": 3, "api_degradation_is_controlled_test": True,
             "declarations": ["a.slv xxx", "a.mst xxx"], "direction_source": "npiDefName selects exact formal modport",
             "early_times": ["0us", "1ns", "1us", "59.999us"], "late_dump_start": "60us"}
    (work/"results.json").write_text(json.dumps(proof, indent=2)+"\n", encoding="utf-8")
    print("PASS {} declaration/time cases, 3 VCS assign replays".format(len(results)))
    print("RESULTS " + str(work))


if __name__ == "__main__":
    main()
