#!/usr/bin/env python3
"""Real FSDB regression for late canonical paths with early bound aliases.

VCT fallback tests additionally inject a failed/future fast seek while leaving
all FSDB records and first/next traversal APIs unchanged.
"""
import argparse
import csv
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
    with log.open("w", encoding="utf-8") as output:
        p = subprocess.run([str(a) for a in argv], cwd=str(cwd), stdout=output,
                           stderr=subprocess.STDOUT, timeout=120)
    if p.returncode != expect:
        raise AssertionError("{}: exit {}, expected {}\n{}".format(
            log, p.returncode, expect, log.read_text(encoding="utf-8", errors="replace")[-9000:]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cli", help="optional frozen executable")
    parser.add_argument("--baseline-cli", help="optional 1.3.4 executable for the real before/after comparison")
    args = parser.parse_args()
    cli = [args.cli, "--cli"] if args.cli else [sys.executable, str(ROOT/"wave_init.py")]
    work = Path(tempfile.mkdtemp(prefix="early_time_", dir=str(ROOT/"build")))
    print("EVIDENCE " + str(work), flush=True)
    verdi = Path(os.environ["VERDI_HOME"])
    lib = verdi/"share/NPI/lib/LINUX64"
    sources = [ROOT/"tests/fixtures/modport_direction"/n for n in ("bus.sv", "dut.sv", "tb.sv")]
    vcs = ["vcs", "-full64", "-sverilog", "-debug_access+all", "-kdb", "-lca", "-P",
           verdi/"share/PLI/VCS/LINUX64/novas.tab", verdi/"share/PLI/VCS/LINUX64/pli.a"]
    run(vcs+sources+["-top", "direction_top", "-o", "simv"], work, work/"compile.log")
    for name, flags in (("full", []), ("late", ["+LATE"])):
        dump = work/name
        dump.mkdir()
        run([work/"simv"]+flags, dump, dump/"simulation.log")
    run(["g++", "-std=c++11", "-I"+str(verdi/"share/NPI/inc"),
         ROOT/"tests/fixtures/early_interface_fsdb.cpp", "-L"+str(lib), "-Wl,-rpath,"+str(lib),
         "-lNPI", "-ldl", "-lpthread", "-o", work/"writer"], work, work/"writer_compile.log")
    (work/"aliases").mkdir()
    run([work/"writer", work/"aliases/waves.fsdb"], work, work/"writer.log")
    results = []

    def extract(name, when="1ns", dump="aliases", scope="direction_top.u_wrap.dut",
                extra=(), expect=0, command=None, fsdb=None, kdb=None):
        out = work/name
        run((command or cli)+["--fsdb", fsdb or work/dump/"waves.fsdb", "--kdb", kdb or work/"simv.daidir",
                             "--scope", scope, "--time", when, "--out", out]+list(extra),
            ROOT, work/(name+".console.log"), expect)
        report = json.loads((out/"snapshot.json").read_text(encoding="utf-8"))
        with (out/"snapshot.csv").open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        assert [r["value_bin"] for r in rows] == [r["value_bin"] or "" for r in report["signals"]]
        assert all(json.loads(c["waveform_reads"]) == r["waveform_reads"] for c, r in zip(rows, report["signals"]))
        results.append({"case": name, "status": "pass", "time": when, "exit_code": expect,
                        "signals": len(report["signals"]), "tick": report["tick"], "min_tick": report["min_tick"]})
        return report

    early = {"xxx.clk": ("input", "1"), "xxx.req": ("input", "1"),
             "xxx.data": ("input", "10xz0101"), "xxx.pad": ("inout", "z")}
    later = dict(early)
    later.update({"xxx.req": ("input", "0"), "xxx.data": ("input", "z01x1010")})

    def check(report, expected, role="slv"):
        values = {r["logical_path"][len(report["scope"])+1:]: (r["direction"], r["value_bin"]) for r in report["signals"]}
        assert values == expected, values
        assert report["directions_complete"] and all(r["status"] == "ok" and r["modport"] == role for r in report["signals"])

    if args.baseline_cli:
        old = extract("baseline_1ns", command=[args.baseline_cli, "--cli"], expect=2)
        assert all(r["status"] == "no_initial_value" and r["value_bin"] is None for r in old["signals"])
    for when in ("0ns", "1ns", "1us", "9.999us", "10us", "59.999us"):
        report = extract("aliases_"+when, when=when)
        check(report, early)
        assert all("direction_top.link." not in r["waveform_paths"][0] for r in report["signals"])
        if when == "1ns":
            for row in report["signals"]:
                attempts = row["waveform_reads"][0]["attempts"]
                assert attempts[0]["status"] == "no_initial_value" and attempts[0]["first_tick"] == "60000", attempts
                assert attempts[-1]["status"] == "ok" and attempts[-1]["change_tick"] == "0", attempts
            text = (work/"aliases_1ns/diagnostics.txt").read_text(encoding="utf-8")
            assert "first_tick=60000" in text and ": ok" in text
    for when in ("60us", "60.001us"):
        report = extract("aliases_"+when, when=when)
        check(report, later)
        assert all(r["waveform_paths"][0].startswith("direction_top.link.") for r in report["signals"])
    check(extract("aliases_master", scope="direction_top.u_wrap.master"),
          {"xxx.clk": ("input", "1"), "xxx.ack": ("input", "0"), "xxx.pad": ("inout", "z")}, "mst")
    remap_early = {"xxx.clk": ("input", "1"), "xxx.req": ("input", "0"), "xxx.ack": ("input", "1"),
                   "xxx.nibble": ("input", "xz01"), "xxx.mix": ("input", "0110"), "xxx.pad": ("inout", "z")}
    check(extract("aliases_remap_1ns", scope="direction_top.u_wrap.remap"), remap_early, "remap")
    remap_late = dict(remap_early)
    remap_late.update({"xxx.req": ("input", "1"), "xxx.ack": ("input", "0"),
                      "xxx.nibble": ("input", "1x10"), "xxx.mix": ("input", "10z0")})
    check(extract("aliases_remap_60us", when="60us", scope="direction_top.u_wrap.remap"), remap_late, "remap")
    absent = extract("genuine_no_initial", dump="late", expect=2)
    assert all(r["status"] == "no_initial_value" and r["value_bin"] is None for r in absent["signals"])
    assert all(r["waveform_reads"][0]["attempts"][0]["first_tick"] == "60000" for r in absent["signals"])

    def wrapper(name, hook):
        script = work/(name+".tcl")
        backend = Path(args.cli).resolve().parent/"_internal/backend/snapshot.tcl" if args.cli else ROOT/"backend/snapshot.tcl"
        assert backend.is_file(), backend
        script.write_text('set env(WI_LIBRARY_ONLY) 1\nsource {'+str(backend)+'}\n'+hook+r'''
set wi::output [open $env(WI_RESULT) w]
fconfigure $wi::output -encoding utf-8 -translation lf
set wi::trace_file [open $env(WI_TRACE) w]
fconfigure $wi::trace_file -encoding utf-8 -translation lf
if {[catch {wi::main} why options]} {
    wi::emit [wi::obj kind [wi::j fatal] message [wi::j $why] detail [wi::j [dict get $options -errorinfo]]]
}
close $wi::output
close $wi::trace_file
debExit
''', encoding="utf-8")
        executable = work/(name+".sh")
        executable.write_text("#!/bin/sh\nexec "+shlex.quote(str(verdi/"bin/verdi"))+" -batch -nologo -play "+shlex.quote(str(script))+"\n")
        executable.chmod(0o755)
        return executable

    hooks = {
        "failed_seek": "rename npi_fsdb_goto_time original_goto_time\nproc npi_fsdb_goto_time {args} {return 0}\n",
        "future_seek": "rename npi_fsdb_goto_time original_goto_time\nproc npi_fsdb_goto_time {args} {\n"
                       "  set pos [expr {[lsearch -exact $args -time]+1}]\n"
                       # Old NPI dispatch identifies the native command by its
                       # Tcl name. Restore that name temporarily for the call.
                       "  rename npi_fsdb_goto_time injected_goto_time\n"
                       "  rename original_goto_time npi_fsdb_goto_time\n"
                       "  set result [npi_fsdb_goto_time {*}[lreplace $args $pos $pos 60000]]\n"
                       "  rename npi_fsdb_goto_time original_goto_time\n"
                       "  rename injected_goto_time npi_fsdb_goto_time\n"
                       "  return $result\n}\n"
    }
    for name, hook in hooks.items():
        vendor = wrapper(name, hook)
        for when in ("1ns", "59.999us", "60us"):
            report = extract(name+"_"+when, when=when, dump="full", extra=("--verdi", str(vendor)))
            check(report, later if when == "60us" else early)
            if when != "60us" or name == "failed_seek":
                changing = report["signals"] if name == "failed_seek" else [
                    r for r in report["signals"] if r["logical_path"].endswith((".req", ".data"))]
                assert all(r["waveform_reads"][0]["attempts"][0]["read_method"] == "first_scan" for r in changing)
        absent = extract(name+"_genuine_no_initial", dump="late", extra=("--verdi", str(vendor)), expect=2)
        assert all(r["status"] == "no_initial_value" and r["value_bin"] is None for r in absent["signals"])

    glitch = work/"glitch"
    glitch.mkdir()
    run(vcs+[ROOT/"tests/fixtures/glitch_design.sv", "-top", "glitch_top", "-o", "simv"], glitch, glitch/"compile.log")
    run([glitch/"simv", "+fsdb+delta"], glitch, glitch/"simulation.log")
    report = extract("fallback_last_delta", scope="glitch_top.dut", fsdb=glitch/"waves.fsdb",
                     kdb=glitch/"simv.daidir", extra=("--verdi", str(wrapper("glitch_failed_seek", hooks["failed_seek"]))))
    assert len(report["signals"]) == 1 and report["signals"][0]["value_bin"] == "0011", report["signals"]
    assert report["signals"][0]["change_tick"] == "1000"
    filelist = work/"design.f"
    filelist.write_text("".join(str(s)+"\n" for s in sources))
    for name in ("aliases_1ns", "aliases_60us", "aliases_master", "aliases_remap_1ns", "failed_seek_1ns"):
        run(["bash", work/name/"run_vcs.sh", filelist], ROOT, work/(name+".replay.log"))
        assert "WAVE_INIT_SNAPSHOT_PASS" in (work/(name+".replay.log")).read_text()
    force = work/"force_replay"
    force.mkdir()
    observer = force/"observer.sv"
    observer.write_text('''`timescale 1us/1ns
module early_observer;
  `include "{}"
  initial begin
    #0.001;
    direction_top.link.req = 0;
    direction_top.link.data = 0;
    apply_snapshot();
    #0;
    check_snapshot();
    release_snapshot();
    direction_top.link.req = 0;
    direction_top.link.data = 8'h5a;
    #0;
    if (direction_top.link.req !== 0 || direction_top.link.data !== 8'h5a)
      $fatal(1, "release did not restore procedural updates");
    $display("EARLY_FORCE_RELEASE_PASS");
    $finish;
  end
endmodule
'''.format(work/"aliases_1ns/snapshot.svh"))
    run(vcs+sources+[observer, "-top", "direction_top", "-top", "early_observer", "-o", "simv"],
        force, force/"compile.log")
    run([force/"simv"], force, force/"simulation.log")
    assert "EARLY_FORCE_RELEASE_PASS" in (force/"simulation.log").read_text()
    proof = {"status": "pass", "tool_version": __version__, "cases": results, "vcs_assign_replays": 5,
             "vcs_force_release_replays": 1,
             "real_alias_dump_starts_ns": {"actual": 60000, "intermediate": 10000, "formal": 0},
             "vct_seek_degradation_is_controlled_test": True, "fixture_is_not_user_waveform": True}
    (work/"results.json").write_text(json.dumps(proof, indent=2)+"\n", encoding="utf-8")
    print("PASS {} early-time cases, 5 VCS assign replays, force/release replay".format(len(results)), flush=True)
    print("RESULTS " + str(work), flush=True)


if __name__ == "__main__":
    main()
