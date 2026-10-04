#!/usr/bin/env python3
"""Check split-file builds, scoped FSDB dumps and missing interface KDB data."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
RUN = Path(tempfile.mkdtemp(prefix="split_interfaces_", dir=str(ROOT/"build")))


def run(argv, cwd, log, expect=0):
    with log.open("w") as output:
        p = subprocess.run([str(a) for a in argv], cwd=str(cwd), stdout=output,
                           stderr=subprocess.STDOUT, timeout=120)
    if p.returncode != expect:
        raise RuntimeError("{} exited {}\n{}".format(argv[0], p.returncode, log.read_text(encoding="utf-8", errors="replace")[-6000:]))


def extract(directory, name, scope, kdb=None, expect=0):
    out = directory/name
    run([sys.executable, ROOT/"wave_init.py", "--fsdb", directory/"waves.fsdb",
         "--kdb", kdb or directory/"simv.daidir", "--scope", "split_top."+scope,
         "--time", "1ns", "--out", out], directory, directory/(name+".log"), expect)
    report = json.loads((out/"snapshot.json").read_text(encoding="utf-8"))
    if expect:
        return report
    values = {r["logical_path"].split(".", 2)[2]: r["value_bin"] for r in report["signals"]}
    expected = {"bus.clk": "1", "bus.pad": "z"}
    if scope == "connected":
        expected["bus.ack"] = "0"
    elif scope == "aliases":
        expected.update({"bus.req": "0", "bus.ack": "1", "bus.nibble": "xz01", "bus.mix": "0110"})
    elif scope == "array_dut":
        expected = {"buses[0].clk": "1", "buses[0].req": "0", "buses[0].data": "00110110", "buses[0].pad": "0",
                    "buses[1].clk": "1", "buses[1].req": "1", "buses[1].data": "11001001", "buses[1].pad": "1"}
    elif scope == "shared":
        expected = {"bus_"+port+"."+name: value for port in ("a", "b")
                    for name, value in (("clk", "1"), ("req", "1"), ("data", "10xz0101"), ("pad", "z"))}
    else:
        expected.update({"rst_n": "1", "bus.req": "1", "bus.data": "10xz0101"})
    assert values == expected, (name, values, expected)
    assert report["complete"]
    print("PASS " + str(out), flush=True)
    return {"case": name, "scope": scope, "status": "pass", "signals": len(values)}


def replay(out, sources):
    filelist = out/"design.f"
    filelist.write_text("".join(str(sources/f)+"\n" for f in ("bus.sv", "dut.sv", "tb.sv")))
    run(["bash", out/"run_vcs.sh", filelist], out, out/"replay.log")
    assert "WAVE_INIT_SNAPSHOT_PASS" in (out/"replay.log").read_text(encoding="utf-8")


def main():
    verdi = Path(os.environ["VERDI_HOME"])
    pli = ["-P", verdi/"share/PLI/VCS/LINUX64/novas.tab", verdi/"share/PLI/VCS/LINUX64/pli.a"]
    results = []
    for mode in ("filelist", "three_step"):
        work = RUN/mode
        work.mkdir()
        shutil.copytree(str(ROOT/"tests/fixtures/split_interface"), str(work/"rtl"))
        (work/"design.f").write_text("rtl/bus.sv\nrtl/dut.sv\nrtl/tb.sv\n")
        if mode == "three_step":
            for filename in ("bus.sv", "dut.sv", "tb.sv"):
                run(["vlogan", "-full64", "-sverilog", "-kdb", "-debug_access+all", "rtl/"+filename],
                    work, work/(filename+".analysis.log"))
            args = ["vcs", "-full64", "-kdb", "-lca", "-debug_access+all", "split_top"]
        else:
            args = ["vcs", "-full64", "-sverilog", "-kdb", "-lca", "-debug_access+all", "-f", "design.f", "-top", "split_top"]
        run(args+pli+["-o", "simv"], work, work/"compile.log")
        run([work/"simv"], work, work/"simulation.log")
        for scope in ("dut", "legacy", "connected"):
            result = extract(work, "original_"+scope, scope)
            result["compile_mode"] = mode
            results.append(result)
        if mode == "filelist":
            for flag, scope in (("DUT_ONLY", "dut"), ("REMAP_ONLY", "aliases"),
                                ("ARRAY_ONLY", "array_dut"), ("SHARED_ONLY", "shared")):
                limited = work/flag.lower()
                limited.mkdir()
                run([work/"simv", "+"+flag], limited, limited/"simulation.log")
                result = extract(limited, "snapshot", scope, work/"simv.daidir")
                report = json.loads((limited/"snapshot/snapshot.json").read_text(encoding="utf-8"))
                assert any(r["waveform_paths"] != r["design_paths"] for r in report["signals"])
                replay(limited/"snapshot", work/"rtl")
                result.update(case=flag, compile_mode=mode, vcs_replay="pass")
                results.append(result)
            limited = work/"no_interface"
            limited.mkdir()
            run([work/"simv", "+NO_INTERFACE"], limited, limited/"simulation.log")
            report = extract(limited, "snapshot", "dut", work/"simv.daidir", expect=2)
            missing = [r for r in report["signals"] if r["interface_path"]]
            assert len(missing) == 4
            assert all(r["status"] == "not_dumped" and r["value_bin"] is None and
                       "NPI-bound paths" in r["detail"] and not r["waveform_paths"] for r in missing)
            assert any("$fsdbDumpvars" in text for text in report["diagnostics"])
            assert (limited/"snapshot/diagnostics.txt").is_file()
            results.append({"case": "genuinely_missing_interface", "status": "pass", "missing": 4})
        # Leave the compiled design intact and make its recorded source paths
        # unavailable. This simulates moving the database to another machine.
        (work/"rtl").rename(work/"relocated_rtl")
        for scope in ("dut", "legacy", "connected"):
            result = extract(work, "missing_source_"+scope, scope)
            result["compile_mode"] = mode
            results.append(result)
    # A separately analyzed interface without -kdb reproduces npiModule/npiNIY
    # bindings. Verify that no signal direction or value is fabricated.
    work = RUN/"missing_interface_kdb"
    work.mkdir()
    for filename in ("bus.sv", "dut.sv", "tb.sv"):
        flags = [] if filename == "bus.sv" else ["-kdb"]
        run(["vlogan", "-full64", "-sverilog", "-debug_access+all"]+flags+
            [ROOT/"tests/fixtures/split_interface"/filename], work, work/(filename+".log"))
    run(["vcs", "-full64", "-kdb", "-lca", "-debug_access+all", "split_top"]+pli+["-o", "simv"],
        work, work/"compile.log")
    run([work/"simv"], work, work/"simulation.log")
    for scope in ("dut", "legacy", "connected"):
        report = extract(work, scope, scope, expect=2)
        errors = [r for r in report["signals"] if r["status"] != "ok"]
        assert errors and all("vlogan -sverilog -kdb" in r["detail"] for r in errors)
        assert all(r["value_bin"] is None and r["direction"] == "unknown" for r in errors)
        assert any("vlogan" in text for text in report["diagnostics"])
        results.append({"case": "missing_interface_kdb", "scope": scope, "status": "pass"})
    (RUN/"results.json").write_text(json.dumps(results, indent=2)+"\n")
    print(json.dumps(results, indent=2))
    print("RESULTS " + str(RUN))


if __name__ == "__main__":
    main()
