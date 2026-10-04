#!/usr/bin/env python3
"""Exercise deep interface forwarding with real Verdi/VCS and independent values."""
import argparse
import csv
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def run(argv, cwd, log, expect=0):
    with log.open("w", encoding="utf-8") as stream:
        p = subprocess.run([str(a) for a in argv], cwd=str(cwd), stdout=stream,
                           stderr=subprocess.STDOUT, timeout=180)
    if p.returncode != expect:
        raise AssertionError("{} exited {} (expected {}): {}\n{}".format(
            argv[0], p.returncode, expect, log,
            log.read_text(encoding="utf-8", errors="replace")[-5000:]))


def prefix(depth, lane=1):
    return "deep_top.soc.g_tile[{}].tile.u_chain".format(lane) + ".g_next.u_child" * depth


def scope(depth, leaf="dut", lane=1):
    return prefix(depth, lane) + ".g_leaf." + leaf


def expected(leaf, lane, tick):
    after = tick >= 5
    req = ("0" if lane else "1") if after else ("1" if lane else "0")
    ack = "1" if req == "0" else "0"
    data = (("z01x1010" if lane else "11001001") if after else
            ("10xz0101" if lane else "00110110"))
    pad = "z" if lane else "0"
    fields = {"bus.clk": "1", "bus.pad": pad}
    if leaf == "dut":
        fields.update({"rst_n": "1", "bus.req": req, "bus.data": data})
    elif leaf == "connected":
        fields["bus.ack"] = ack
    elif leaf == "aliases":
        fields.update({"bus.req": ack, "bus.ack": req,
                       "bus.nibble": data[2:6], "bus.mix": data[6:8] + data[0:2]})
    elif leaf == "shared":
        fields = {"bus_"+port+"."+name: value for port in ("a", "b")
                  for name, value in (("clk", "1"), ("pad", pad), ("req", req), ("data", data))}
    elif leaf == "array_dut":
        vals = (("10010011", "01001100") if lane else ("01010111", "10111000")) if after else (
            ("01101001", "10100110") if lane else ("00010010", "11100011"))
        fields = {}
        for index in (0, 1):
            array_req = str((lane + index + int(after) + 1) % 2)
            array_pad = (("1", "0") if lane else ("z", "1"))[index]
            for name, value in (("clk", "1"), ("pad", array_pad), ("req", array_req), ("data", vals[index])):
                fields["buses[{}].{}".format(index, name)] = value
    else:
        raise ValueError(leaf)
    return fields


def extract(cli, work, dump, depth, leaf="dut", lane=1, tick=1, missing=False):
    query = scope(depth, leaf, lane)
    name = "{}_lane{}_{}ns".format(leaf, lane, tick)
    out = dump/name
    run(cli + ["--fsdb", dump/"waves.fsdb", "--kdb", work/"simv.daidir",
               "--scope", query, "--time", "{}ns".format(tick), "--out", out],
        work, dump/(name+".log"), expect=2 if missing else 0)
    report = json.loads((out/"snapshot.json").read_text(encoding="utf-8"))
    want = expected(leaf, lane, tick)
    rows = {r["logical_path"][len(query)+1:]: r for r in report["signals"]}
    assert set(rows) == set(want), (set(rows), set(want))
    if missing:
        absent = [r for r in rows.values() if missing == "all" or r["interface_path"]]
        assert absent and all(r["status"] == "not_dumped" and r["value_bin"] is None for r in absent)
        if missing == "interface":
            assert rows["rst_n"]["status"] == "ok" and rows["rst_n"]["value_bin"] == "1"
            assert all(r["direction"] in ("input", "inout") for r in absent)
        assert not report["complete"]
    else:
        assert report["complete"]
        assert {name: r["value_bin"] for name, r in rows.items()} == want
        assert all(r["direction"] == ("inout" if name.endswith(".pad") else "input")
                   for name, r in rows.items())
        actual_prefix = "deep_top.soc.g_tile[{}].tile.link".format(lane)
        assert all(path.startswith(actual_prefix) for r in rows.values() if r["interface_path"]
                   for path in r["design_paths"]), rows
        with (out/"snapshot.csv").open(encoding="utf-8", newline="") as f:
            csv_values = {r["logical_path"][len(query)+1:]: r["value_bin"] for r in csv.DictReader(f)}
        assert csv_values == want
    return {"status": "pass", "scope": query, "module_levels": depth+5,
            "hierarchy_segments": len(query.split(".")), "dump": dump.name,
            "time": "{}ns".format(tick), "signals": len(rows), "negative_missing_case": bool(missing),
            "missing_kind": missing or "",
            "expected_values": want, "snapshot": str(out/"snapshot.json"),
            "alias_reads": sum(r.get("design_paths") != r["waveform_paths"] for r in rows.values())}


def replay(result, work):
    out = Path(result["snapshot"]).parent
    run(["bash", out/"run_vcs.sh", work/"design.f"], out, out/"replay.log")
    assert "WAVE_INIT_SNAPSHOT_PASS" in (out/"replay.log").read_text(encoding="utf-8")
    result["vcs_assign_replay"] = "pass"


def replay_force_release(cli, work, depth):
    dump = work/"dut_only"
    out = dump/"force_release"
    query = scope(depth)
    mapped = "existing_replay.original." + query.split(".", 1)[1]
    interface = "existing_replay.original.soc.g_tile[1].tile.link"
    run(cli + ["--fsdb", dump/"waves.fsdb", "--kdb", work/"simv.daidir",
               "--scope", query, "--time", "1ns", "--out", out, "--sv-target", mapped,
               "--sv-interface-map", "bus="+interface], work, dump/"force_extract.log")
    bench = out/"existing.sv"
    bench.write_text('''`timescale 1ns/1ps
module existing_replay;
  deep_top original();
  `include "%s"
  initial begin
    #6;
    if (%s.data !== 8'bz01x1010) $fatal(1,"original drive before force");
    apply_snapshot();
    #0.001;
    if (%s.data !== 8'b10xz0101 || %s.req !== 1'b1 || %s.pad !== 1'bz)
      $fatal(1,"deep input snapshot not applied");
    check_snapshot();
    release_snapshot();
    #2;
    if (%s.data !== 8'h5a || %s.req !== 1'b1 || %s.pad !== 1'b1)
      $fatal(1,"release did not restore later original drives");
    $display("DEEP_FORCE_RELEASE_PASS");
    $finish;
  end
endmodule
''' % (out/"snapshot.svh", interface, interface, interface, interface, interface, interface, interface), encoding="utf-8")
    run(["vcs", "-full64", "-sverilog", "-debug_access+all", "-f", work/"design.f",
         bench, "-top", "existing_replay", "-P", Path(os.environ["VERDI_HOME"])/"share/PLI/VCS/LINUX64/novas.tab",
         Path(os.environ["VERDI_HOME"])/"share/PLI/VCS/LINUX64/pli.a", "-o", out/"simv"], out, out/"compile.log")
    run([out/"simv"], out, out/"simulation.log")
    assert "DEEP_FORCE_RELEASE_PASS" in (out/"simulation.log").read_text(encoding="utf-8")
    return {"status": "pass", "scope": query, "module_levels": depth+5,
            "hierarchy_segments": len(query.split(".")), "vcs_force_release": "pass",
            "snapshot": str(out/"snapshot.json")}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--depths", type=int, nargs="+", default=[2, 8])
    parser.add_argument("--cli", help="optional frozen wave_init executable")
    args = parser.parse_args()
    cli = [str(Path(args.cli).resolve()), "--cli"] if args.cli else [sys.executable, str(ROOT/"wave_init.py")]
    evidence = Path(tempfile.mkdtemp(prefix="deep_interfaces_", dir=str(ROOT/"build")))
    results = []
    failures = []
    print("EVIDENCE " + str(evidence), flush=True)
    for depth in args.depths:
        work = evidence/("depth_"+str(depth))
        rtl = work/"rtl"
        rtl.mkdir(parents=True)
        for name in ("bus.sv", "dut.sv"):
            shutil.copyfile(str(ROOT/"tests/fixtures/split_interface"/name), str(rtl/name))
        shutil.copyfile(str(ROOT/"tests/fixtures/deep_interface/hierarchy.sv"), str(rtl/"hierarchy.sv"))
        middle = prefix(depth//2)
        (rtl/"tb.sv").write_text('''`timescale 1ns/1ps
module deep_top;
  logic clk=1, rst_n=1;
  deep_soc #(.DEPTH(%d)) soc(.clk(clk), .rst_n(rst_n));
  initial begin
    $fsdbDumpfile("waves.fsdb");
    if ($test$plusargs("DUT_ONLY")) $fsdbDumpvars(0, %s, "+all");
    else if ($test$plusargs("MIDDLE_ONLY")) begin
      $fsdbDumpvars(0, %s, "+all");
    end
    else if ($test$plusargs("MIDDLE_PROXY_ONLY")) begin
      $fsdbDumpvars(0, %s.upstream, "+all");
      $fsdbDumpvars(0, %s.rst_n);
    end
    else if ($test$plusargs("ARRAY_ONLY")) $fsdbDumpvars(0, %s, "+all");
    else if ($test$plusargs("SHARED_ONLY")) $fsdbDumpvars(0, %s.bus_b, "+all");
    else $fsdbDumpvars(0, deep_top, "+all");
    #9 $finish;
  end
endmodule
''' % (depth, scope(depth), middle, middle, scope(depth),
       scope(depth, "array_dut"), scope(depth, "shared")), encoding="utf-8")
        (work/"design.f").write_text("".join(str(rtl/name)+"\n" for name in (
            "bus.sv", "dut.sv", "hierarchy.sv", "tb.sv")), encoding="utf-8")
        verdi = Path(os.environ["VERDI_HOME"])
        run(["vcs", "-full64", "-sverilog", "-kdb", "-lca", "-debug_access+all", "-f", work/"design.f",
             "-top", "deep_top", "-P", verdi/"share/PLI/VCS/LINUX64/novas.tab",
             verdi/"share/PLI/VCS/LINUX64/pli.a", "-o", work/"simv"], work, work/"compile.log")
        cases = {
            "FULL": [("dut", 0, 1), ("dut", 1, 1), ("connected", 1, 1), ("aliases", 1, 1),
                     ("array_dut", 1, 1), ("shared", 1, 1)],
            "DUT_ONLY": [("dut", 1, 1), ("dut", 1, 5), ("dut", 1, 7), ("dut", 0, 1)],
            "MIDDLE_ONLY": [("dut", 1, 7), ("aliases", 1, 1)],
            "MIDDLE_PROXY_ONLY": [("dut", 1, 1)],
            "ARRAY_ONLY": [("array_dut", 1, 7)],
            "SHARED_ONLY": [("shared", 1, 7)],
        }
        for flag, queries in cases.items():
            dump = work/flag.lower()
            dump.mkdir()
            run([work/"simv", "+"+flag], dump, dump/"simulation.log")
            for leaf, lane, tick in queries:
                try:
                    missing = "all" if flag == "DUT_ONLY" and lane == 0 else (
                        "interface" if flag == "MIDDLE_PROXY_ONLY" else "")
                    result = extract(cli, work, dump, depth, leaf, lane, tick, missing=missing)
                    if (flag, leaf, lane, tick) in (("DUT_ONLY", "dut", 1, 5), ("FULL", "aliases", 1, 1),
                                                  ("ARRAY_ONLY", "array_dut", 1, 7), ("SHARED_ONLY", "shared", 1, 7)):
                        replay(result, work)
                    results.append(result)
                    print("PASS depth={} {} {} lane={} {}ns".format(depth, flag, leaf, lane, tick), flush=True)
                except Exception as exc:
                    failure = {"status": "fail", "depth": depth, "dump": flag, "leaf": leaf,
                               "lane": lane, "time_ns": tick, "error": str(exc)}
                    results.append(failure)
                    failures.append(failure)
                    print("FAIL " + json.dumps(failure), flush=True)
                (evidence/"results.json").write_text(json.dumps(results, indent=2)+"\n", encoding="utf-8")
        try:
            results.append(replay_force_release(cli, work, depth))
            print("PASS depth={} existing TB force/release".format(depth), flush=True)
        except Exception as exc:
            failure = {"status": "fail", "depth": depth, "case": "force_release", "error": str(exc)}
            results.append(failure)
            failures.append(failure)
            print("FAIL " + json.dumps(failure), flush=True)
        (evidence/"results.json").write_text(json.dumps(results, indent=2)+"\n", encoding="utf-8")
    print("RESULTS {}: {} passed, {} failed".format(evidence, len(results)-len(failures), len(failures)), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
