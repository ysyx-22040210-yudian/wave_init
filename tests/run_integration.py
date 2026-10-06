#!/usr/bin/env python3
"""Real Verdi/VCS acceptance tests. Run from a shell with tests/env.sh sourced."""
import argparse
import csv
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
RUN = Path(tempfile.mkdtemp(prefix="acceptance_", dir=str(ROOT / "build")))
RESULTS = []


def run(argv, cwd, log, expect=0):
    with log.open("w") as output:
        p = subprocess.run([str(a) for a in argv], cwd=str(cwd), stdout=output, stderr=subprocess.STDOUT, timeout=120)
    if p.returncode != expect:
        raise AssertionError("{}: exit {}, expected {}\n{}".format(
            log, p.returncode, expect, log.read_text(errors="replace")[-9000:]))
    return log.read_text(errors="replace")


def compile_design(source, top, output):
    output.mkdir(parents=True, exist_ok=True)
    verdi = Path(os.environ["VERDI_HOME"])
    return run(["vcs", "-full64", "-sverilog", "-debug_access+all", "-kdb", "-lca",
                "-P", verdi/"share/PLI/VCS/LINUX64/novas.tab", verdi/"share/PLI/VCS/LINUX64/pli.a",
                source, "-top", top, "-o", "simv"], output, output/"compile.log")


def extract(name, scope, when="7ns", fsdb=None, kdb=None, expect=0, extra=()):
    out = RUN / name
    argv = [sys.executable, ROOT/"wave_init.py", "--fsdb", fsdb or ROOT/"build/fixture/waves.fsdb",
            "--kdb", kdb or ROOT/"build/fixture/simv.daidir", "--scope", scope, "--time", when, "--out", out]
    run(argv + list(extra), ROOT, RUN/(name+".log"), expect)
    if expect == 1:
        assert (out/"error.json").is_file()
        return None
    result = json.loads((out/"snapshot.json").read_text(encoding="utf-8"))
    with (out/"snapshot.csv").open(newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == len(result["signals"])
    assert [r["value_bin"] for r in rows] == [r["value_bin"] or "" for r in result["signals"]]
    return result


def signals(report):
    prefix = report["scope"] + "."
    return {r["logical_path"][len(prefix):]: r for r in report["signals"]}


def replay(name):
    out = RUN/name
    source = (out/"tb_snapshot.sv").read_text()
    assert not re.search(r"^\s*(?:force|release)\s", source, re.MULTILINE), source
    filelist = RUN/"fixture.f"
    filelist.write_text(str(ROOT/"tests/fixtures/snapshot_design.sv")+"\n")
    text = run(["bash", out/"run_vcs.sh", filelist], ROOT, out/"replay.log")
    assert "WAVE_INIT_SNAPSHOT_PASS" in text


def test_plain_and_shapes():
    r = extract("plain", "snapshot_top.dut")
    ss = signals(r)
    expected = {"clk":"1", "rst_n":"1", "scalar":"10010110", "ascending":"10100110",
                "packed_data":"10111001", "packet":"1100000100100011", "pad":"z",
                "bus.clk":"1", "bus.req":"1", "bus.wdata":"10100101", "bus.pad":"z",
                "matrix[1][2]":"00010001", "matrix[1][1]":"00010001", "matrix[0][2]":"00000010",
                "matrix[0][1]":"00000001"}
    expected["matrix[1][2]"] = "00010010"
    expected["wide"] = "xz" + format(int("0123456789abcdeffedcba9876543210", 16), "0128b")
    assert set(ss) == set(expected), (set(ss), set(expected))
    for key, value in expected.items():
        assert ss[key]["value_bin"] == value, (key, ss[key])
    assert ss["scalar"]["shape"]["signed"] == 1
    assert ss["ascending"]["shape"]["packed_ranges"] == [[0,7]]
    source = (RUN/"plain/tb_snapshot.sv").read_text()
    assert "assign scalar = 8'b10010110;" in source
    assert "assign matrix[1][2] = 8'b00010010;" in source
    assert "assign bus.wdata = 8'b10100101;" in source
    assert ".scalar(scalar)" in source
    assert not re.search(r"assign (?:bus\.(?:ack|rdata)|result)\s*=", source)
    assert r["sv"]["standalone_drive"] == "assign"
    replay("plain")


def test_modports_and_generics():
    for scope in ("master", "connected", "wrapper.nested"):
        r = extract(scope.replace(".", "_"), "snapshot_top."+scope)
        ss = signals(r)
        expected = {"bus.clk", "bus.pad", "bus.ack", "bus.rdata"} if scope != "wrapper.nested" else {
            "bus.clk", "bus.pad", "bus.req", "bus.wdata"}
        assert set(ss) == expected
        assert all(s["direction_source"] == "modport" for s in ss.values())
        replay(scope.replace(".", "_"))
    bare = extract("bare", "snapshot_top.bare")
    assert len(bare["signals"]) == 6
    assert all(r["direction"] == "unknown" for r in bare["signals"])
    assert bare["sv"]["forced_targets"] == 0
    assert not bare["directions_complete"] and bare["values_complete"]
    replay("bare")
    forced = extract("bare_forced", "snapshot_top.bare", extra=("--force-unknown",))
    assert forced["sv"]["forced_targets"] == 6
    replay("bare_forced")


def test_interface_array_and_aliases():
    r = extract("arrays", "snapshot_top.array_dut")
    ss = signals(r)
    assert len(ss) == 8
    assert ss["buses[0].wdata"]["value_bin"] == "00110110"
    assert ss["buses[1].wdata"]["value_bin"] == "11001001"
    assert ss["buses[0].pad"]["value_bin"] == "0"
    assert ss["buses[1].pad"]["value_bin"] == "1"
    replay("arrays")
    r = extract("aliases", "snapshot_top.aliases")
    ss = signals(r)
    assert ss["bus.nibble"]["value_bin"] == "1001"
    assert ss["bus.mix"]["value_bin"] == "0111"
    replay("aliases")


def test_time_and_xz():
    before = signals(extract("before", "snapshot_top.dut", "9.999ns"))
    exact = signals(extract("exact", "snapshot_top.dut", "10ns"))
    held = signals(extract("held", "snapshot_top.dut", "14.999ns"))
    tick = signals(extract("ticks", "snapshot_top.dut", "10000ticks"))
    zero = signals(extract("zero", "snapshot_top.dut", "0ns"))
    assert before["scalar"]["value_bin"] == "10010110"
    assert exact["scalar"]["value_bin"] == held["scalar"]["value_bin"] == tick["scalar"]["value_bin"] == "10xz0101"
    assert zero["clk"]["value_bin"] == "0"
    replay("exact")
    extract("subtick", "snapshot_top.dut", "0.1ps", expect=1)
    extract("outside", "snapshot_top.dut", "26ns", expect=1)
    extract("wrong_scope", "snapshot_top.missing", expect=1)


def test_dump_gaps_and_missing():
    fixture = RUN/"timing"
    compile_design(ROOT/"tests/fixtures/timing_design.sv", "timing_top", fixture)
    for variant, flag in (("gap", "+GAP"), ("late", "+LATE"), ("missing", "+MISSING"), ("late_signal", "+LATE_SIGNAL")):
        directory = fixture/variant
        directory.mkdir()
        run([fixture/"simv", flag], directory, directory/"simulation.log")
    kdb = fixture/"simv.daidir"
    for name, when, expected in (("gap_before", "24ps", "ok"), ("gap_start", "25ps", "dump_off"),
                                 ("gap_middle", "30ps", "dump_off"), ("gap_end", "45ps", "ok")):
        r = extract(name, "timing_top.dut", when, fixture/"gap/waves.fsdb", kdb, 0 if expected == "ok" else 2)
        assert signals(r)["data"]["status"] == expected
        if expected == "ok":
            assert signals(r)["data"]["value_bin"] == ("00110100" if name == "gap_before" else "01010110")
        else:
            assert signals(r)["data"]["value_bin"] is None
    r = extract("missing", "timing_top.dut", "20ps", fixture/"missing/waves.fsdb", kdb, 2)
    assert signals(r)["absent"]["status"] == "not_dumped"
    # A later first FSDB record must not impose a minimum query time.
    r = extract("late_signal", "timing_top.dut", "10ps", fixture/"late_signal/waves.fsdb", kdb, 2)
    assert all(s["status"] in ("no_initial_value", "not_dumped") and s["value_bin"] is None for s in r["signals"])
    # Late dumping may expose an earlier global range with an explicit dump-off
    # interval, or make the initial time the file minimum. Neither may use future data.
    out = RUN/"late_before"
    argv = [sys.executable, ROOT/"wave_init.py", "--fsdb", fixture/"late/waves.fsdb", "--kdb", kdb,
            "--scope", "timing_top.dut", "--time", "10ps", "--out", out]
    with (RUN/"late_before.log").open("w") as f:
        p = subprocess.run([str(x) for x in argv], stdout=f, stderr=subprocess.STDOUT)
    assert p.returncode == 2
    r = json.loads((out/"snapshot.json").read_text(encoding="utf-8"))
    assert all(s["value_bin"] is None for s in r["signals"])


def test_existing_include_and_release():
    out = RUN/"plain"
    bench = RUN/"existing.sv"
    bench.write_text('''`timescale 1ns/1ps
module existing_replay;
  snapshot_top original();
  `include "relocated/snapshot.svh"
  initial begin
    #1;
    apply_snapshot();
    #0.001;
    check_snapshot();
    if (original.dut.clk !== 1'b1) $fatal(1,"apply did not override original clock");
    release_snapshot();
    #0.001;
    if (original.dut.clk !== 1'b0) $fatal(1,"release did not restore original driver");
    if (original.dut.pad !== 1'bz) $fatal(1,"inout release did not restore Z");
    #10;
    if (original.dut.scalar !== 8'b10xz0101) $fatal(1,"released scalar did not follow driver");
    $display("WAVE_INIT_EXISTING_RELEASE_PASS");
    $finish;
  end
endmodule
''')
    extract("relocated", "snapshot_top.dut", extra=("--sv-target", "existing_replay.original.dut",
            "--sv-interface-map", "bus=existing_replay.original.link"))
    directory = RUN/"existing_run"
    directory.mkdir()
    verdi = Path(os.environ["VERDI_HOME"])
    run(["vcs", "-full64", "-sverilog", "-debug_access+all", "+incdir+"+str(RUN),
         "-P", verdi/"share/PLI/VCS/LINUX64/novas.tab", verdi/"share/PLI/VCS/LINUX64/pli.a",
         ROOT/"tests/fixtures/snapshot_design.sv", bench, "-top", "existing_replay", "-o", "simv"],
        directory, directory/"compile.log")
    text = run([directory/"simv"], directory, directory/"simulation.log")
    assert "WAVE_INIT_EXISTING_RELEASE_PASS" in text


def test_parameters_struct_union_shared_interface():
    fixture = RUN/"advanced"
    compile_design(ROOT/"tests/fixtures/advanced_design.sv", "advanced_top", fixture)
    run([fixture/"simv"], fixture, fixture/"simulation.log")
    r = extract("advanced_values", "advanced_top.dut", "1ns", fixture/"waves.fsdb", fixture/"simv.daidir")
    ss = signals(r)
    assert len(ss) == 13
    assert ss["record_data.tag"]["value_bin"] == "1011"
    assert ss["record_data.payload"]["value_bin"] == format(0x12345678, "032b")
    assert ss["union_data"]["value_bin"] == format(0x5678, "016b")
    assert ss["param_data"]["value_bin"] == format(0x1593, "013b")
    assert ss["bus_a.data"]["value_bin"] == format(0x123456, "024b")
    assert ss["bus_b.data"]["value_bin"] == ss["bus_a.data"]["value_bin"]
    escaped=[v for k,v in ss.items() if k.rstrip()=="\\escaped.port"]
    assert len(escaped)==1 and escaped[0]["value_bin"]=="1"
    assert len(r["interfaces"]) == 1
    assert r["sv"]["forced_targets"] < len(r["signals"])
    filelist = RUN/"advanced.f"
    filelist.write_text(str(ROOT/"tests/fixtures/advanced_design.sv")+"\n")
    out=RUN/"advanced_values"
    text=run(["bash",out/"run_vcs.sh",filelist],ROOT,out/"replay.log")
    assert "WAVE_INIT_SNAPSHOT_PASS" in text


def test_constant_assign_connections():
    fixture = RUN/"assign_fixture"
    source = ROOT/"tests/fixtures/assign_design.sv"
    compile_design(source, "assign_top", fixture)
    run([fixture/"simv"], fixture, fixture/"simulation.log")
    r = extract("assign_values", "assign_top.u", "7ns", fixture/"waves.fsdb", fixture/"simv.daidir")
    expected = {"a": "10xz0101", "dut": "0", "check_snapshot": "1", "wi_bus_clk": "0",
                "pad": "1", "bus.clk": "1", "bus.req": "1010"}
    assert {k: row["value_bin"] for k, row in signals(r).items()} == expected
    out = RUN/"assign_values"
    text = (out/"tb_snapshot.sv").read_text()
    assert not re.search(r"^\s*(?:force|release)\s", text, re.MULTILINE)
    assert "assign a = 8'b10xz0101;" in text
    assert ".a(a)" in text
    assert "assign bus.req = 4'b1010;" in text
    filelist = RUN/"assign.f"
    filelist.write_text(str(source)+"\n")
    log = run(["bash", out/"run_vcs.sh", filelist], ROOT, out/"replay.log")
    assert "WAVE_INIT_SNAPSHOT_PASS" in log

    # Independently observe the actual DUT and its combinational output after
    # 20 ns. Keep the generated TB alive; do not drive or force any signal here.
    held = RUN/"assign_held.sv"
    held.write_text(text.replace("  $finish;", "  // Finish controlled by the regression observer."))
    observer = RUN/"assign_observer.sv"
    observer.write_text('''`timescale 1ns/1ps
module assign_observer;
  wave_init_tb snapshot();
  initial begin
    #20;
    if (snapshot.dut_1.a !== 8'b10xz0101) $fatal(1,"input var did not retain the assigned sample");
    if (snapshot.dut_1.observed !== 8'b10xx1111) $fatal(1,"DUT did not consume assigned inputs");
    if (snapshot.dut_1.dut !== 1'b0 || snapshot.dut_1.check_snapshot !== 1'b1 ||
        snapshot.dut_1.wi_bus_clk !== 1'b0) $fatal(1,"generated name collided with an RTL port");
    if (snapshot.dut_1.pad !== 1'b1) $fatal(1,"inout assignment lost resolved input");
    if (snapshot.bus.clk !== 1'b1 || snapshot.bus.req !== 4'b1010)
      $fatal(1,"interface input or constructor connection incorrect");
    if (snapshot.bus.resp !== 4'b0101) $fatal(1,"interface output incorrectly driven");
    $display("WAVE_INIT_ASSIGN_HOLD_PASS");
    $finish;
  end
endmodule
''')
    directory = RUN/"assign_held_run"
    directory.mkdir()
    run(["vcs", "-full64", "-sverilog", source, held, observer, "-top", "assign_observer", "-o", "simv"],
        directory, directory/"compile.log")
    log = run([directory/"simv"], directory, directory/"simulation.log")
    assert "WAVE_INIT_ASSIGN_HOLD_PASS" in log


def test_sparse_fsdb_and_glitches():
    fixture=RUN/"sparse";fixture.mkdir()
    compile_design(ROOT/"tests/fixtures/timing_design.sv","timing_top",fixture)
    verdi=Path(os.environ["VERDI_HOME"])
    lib=verdi/"share/NPI/lib/LINUX64"
    run(["g++","-std=c++11","-I"+str(verdi/"share/NPI/inc"),ROOT/"tests/fixtures/sparse_fsdb.cpp",
         "-L"+str(lib),"-Wl,-rpath,"+str(lib),"-lNPI","-ldl","-lpthread","-o",fixture/"writer"],
        fixture,fixture/"writer_compile.log")
    for name,flag in (("sparse",[]),("mismatch",["mismatch"])):
        run([fixture/"writer",fixture/(name+".fsdb")]+flag,fixture,fixture/(name+"_write.log"))
    r=extract("sparse_before","timing_top.dut","10ps",fixture/"sparse.fsdb",fixture/"simv.daidir",2)
    ss=signals(r)
    assert ss["data"]["status"]=="no_initial_value" and ss["data"]["value_bin"] is None,ss["data"]
    assert ss["absent"]["status"]=="ok" and ss["pad"]["value_bin"]=="z"
    r=extract("sparse_after","timing_top.dut","15ps",fixture/"sparse.fsdb",fixture/"simv.daidir")
    assert signals(r)["data"]["value_bin"]=="10100101"
    r=extract("width_mismatch","timing_top.dut","20ps",fixture/"mismatch.fsdb",fixture/"simv.daidir",2)
    assert signals(r)["absent"]["status"]=="width_mismatch"

    fixture=RUN/"glitches"
    compile_design(ROOT/"tests/fixtures/glitch_design.sv","glitch_top",fixture)
    run([fixture/"simv","+fsdb+delta"],fixture,fixture/"simulation.log")
    r=extract("glitch_last","glitch_top.dut","1ns",fixture/"waves.fsdb",fixture/"simv.daidir")
    assert signals(r)["data"]["value_bin"]=="0011"
    # Independently verify the fixture really retained multiple changes at t=1000.
    script=fixture/"count.tcl"
    script.write_text('''set f [npi_fsdb_open -name {%s}]
set s [npi_fsdb_sig_by_name -file $f -name glitch_top.dut.data -scope ""]
set v [npi_fsdb_create_vct -sig $s]
set n 0
if {[npi_fsdb_goto_first -vct $v]} {
  while {1} {
    if {[npi_fsdb_vct_time -vct $v] == 1000} {incr n}
    if {![npi_fsdb_goto_next -vct $v]} {break}
  }
}
puts "GLITCH_CHANGES=$n"
debExit
''' % str(fixture/"waves.fsdb"))
    text=run(["verdi","-batch","-nologo","-play",script],fixture,fixture/"count.log")
    assert "GLITCH_CHANGES=3" in text,text[-3000:]


def test_partial_sv_parameter_diagnostic():
    fixture=RUN/"limitations"
    compile_design(ROOT/"tests/fixtures/limitations_design.sv","limitations_top",fixture)
    run([fixture/"simv"],fixture,fixture/"simulation.log")
    r=extract("string_parameter","limitations_top.dut","1ns",fixture/"waves.fsdb",fixture/"simv.daidir",2)
    assert r["values_complete"] and len(r["signals"])==1
    assert signals(r)["data"]["value_bin"]=="1010"
    assert r["sv"]["existing_tb_complete"] and not r["sv"]["standalone_complete"]
    assert any("LABEL" in e for e in r["sv"]["diagnostics"])
    assert '$fatal' in (RUN/"string_parameter/tb_snapshot.sv").read_text()


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--only",nargs="*",help="run only named test functions")
    args=p.parse_args()
    failures = 0
    for test in (test_plain_and_shapes, test_modports_and_generics, test_interface_array_and_aliases,
                 test_time_and_xz, test_dump_gaps_and_missing, test_existing_include_and_release,
                 test_parameters_struct_union_shared_interface, test_sparse_fsdb_and_glitches,
                 test_partial_sv_parameter_diagnostic, test_constant_assign_connections):
        if args.only and test.__name__ not in args.only:
            continue
        start = time.monotonic()
        try:
            test()
            state, error = "pass", ""
        except Exception as e:
            state, error = "fail", str(e)
            failures += 1
        row = {"test": test.__name__, "status": state, "seconds": round(time.monotonic()-start,2), "error": error}
        RESULTS.append(row)
        print("{} {} {}".format(state.upper(), test.__name__, error), flush=True)
        (RUN/"results.json").write_text(json.dumps(RESULTS, indent=2)+"\n")
    print("RESULTS {}".format(RUN), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
