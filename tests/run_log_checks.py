#!/usr/bin/env python3
"""Check actionable logs on real deep-hierarchy and incomplete NPI queries."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from waveinit import __version__
from run_deep_interfaces import scope, expected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--deep-case", required=True, help="existing depth_8 FSDB/KDB fixture directory")
    parser.add_argument("--missing-kdb-case", required=True)
    parser.add_argument("--cli", help="optional frozen executable")
    args = parser.parse_args()
    deep, missing = Path(args.deep_case), Path(args.missing_kdb_case)
    cli = [args.cli, "--cli"] if args.cli else [sys.executable, str(ROOT/"wave_init.py")]
    evidence = Path(tempfile.mkdtemp(prefix="logging_", dir=str(ROOT/"build")))
    results = []
    cases = [
        ("deep_default", deep/"dut_only", deep/"simv.daidir", scope(8), "1ns", False, 0),
        ("deep_debug", deep/"dut_only", deep/"simv.daidir", scope(8), "1ns", True, 0),
        ("deep_not_dumped", deep/"middle_proxy_only", deep/"simv.daidir", scope(8), "1ns", False, 2),
        ("missing_interface_kdb", missing, missing/"simv.daidir", "split_top.dut", "1ns", False, 2),
        ("bad_scope", deep/"dut_only", deep/"simv.daidir", scope(8)+".missing", "1ns", False, 1),
        ("time_out_of_range", deep/"dut_only", deep/"simv.daidir", scope(8), "1s", False, 1),
    ]
    for name, dump, kdb, query, when, debug, code in cases:
        out = evidence/name
        command = cli + ["--fsdb", str(dump/"waves.fsdb"), "--kdb", str(kdb), "--scope", query,
                         "--time", when, "--out", str(out)] + (["--debug"] if debug else [])
        proc = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              universal_newlines=True, encoding="utf-8", timeout=120)
        (evidence/(name+".console.log")).write_text(proc.stdout, encoding="utf-8")
        assert proc.returncode == code, proc.stdout
        for filename in ("wave_init.log", "npi_trace.log", "runtime.json", "verdi.log", "npi_records.jsonl"):
            assert (out/filename).is_file(), filename
        trace = [json.loads(line) for line in (out/"npi_trace.log").read_text(encoding="utf-8").splitlines()]
        runtime = json.loads((out/"runtime.json").read_text(encoding="utf-8"))
        assert runtime["exit_code"] == code and runtime["tool_version"] == __version__
        assert "O-2018.09-SP2" in runtime["verdi_release"]
        assert trace[0]["run_id"] == runtime["run_id"]
        if name.startswith("deep_"):
            bindings = [r for r in trace if r["event"] == "binding.port"]
            assert len(bindings) >= 10 and any("g_tile[1]" in r["logical_path"] for r in bindings)
            assert any(r["event"] == "modport.member" and r["action"] == "skip_output" for r in trace)
            candidates = [r for r in trace if r["event"] == "fsdb.candidates"]
            assert candidates
            report = json.loads((out/"snapshot.json").read_text(encoding="utf-8"))
            if code == 0:
                assert {r["logical_path"][len(query)+1:]: r["value_bin"] for r in report["signals"]} == expected("dut", 1, 1)
                assert any(r["event"] == "fsdb.absent" for r in trace)
                assert any(r["event"] == "fsdb.selected" and ".g_leaf.dut.bus." in r["waveform_path"] for r in trace)
            else:
                assert sum(r["status"] == "not_dumped" for r in report["signals"]) == 4
                assert "not_dumped" in proc.stdout
        if name == "missing_interface_kdb":
            warning = next(r for r in trace if r["event"] == "interface.unresolved")
            assert "vlogan" in warning["detail"] and "connection_" in warning["stack"]
            assert "interface.unresolved" in proc.stdout
        if code == 1:
            assert trace[-1]["event"] == "backend.fatal"
            assert "run.failed" in (out/"wave_init.log").read_text(encoding="utf-8")
        if name in ("deep_default", "deep_debug"):
            assert ("npi.fsdb.candidates" in proc.stdout) == debug
        results.append({"case": name, "status": "pass", "exit_code": code,
                        "trace_events": len(trace), "out": str(out)})
        print("PASS " + name, flush=True)
    (evidence/"results.json").write_text(json.dumps(results, indent=2)+"\n", encoding="utf-8")
    print("EVIDENCE " + str(evidence), flush=True)


if __name__ == "__main__":
    main()
