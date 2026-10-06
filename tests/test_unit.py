import csv
import json
from pathlib import Path
import tempfile
import unittest

from waveinit.cli import parse_time, read_backend, write_reports
from waveinit.sv import hierarchy, targets, task_source


class BoundaryContracts(unittest.TestCase):
    def test_missing_declared_direction_is_incomplete_but_unqualified_is_distinct(self):
        for origin, expected in (("modport", False), ("unqualified_interface", True)):
            row = {"kind": "signal", "logical_path": "tb.dut.bus.data", "direction": "unknown",
                   "direction_source": origin, "interface_path": "tb.link", "expression": None,
                   "status": "ok", "value_bin": "1", "waveform_reads": []}
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory)/"records.jsonl"
                path.write_text("\n".join(json.dumps(x) for x in (
                    {"kind": "metadata", "scope": "tb.dut"}, row, {"kind": "done", "count": 1}))+"\n")
                report = read_backend(path)
                self.assertEqual(report["declared_directions_complete"], expected)
                self.assertEqual(bool(report["diagnostics"]), not expected)

    def test_time_before_first_fsdb_record_retains_a_partial_report(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"records.jsonl"
            path.write_text('{"kind":"metadata","scope":"tb.dut","tick":"0","min_tick":"60000"}\n'
                            '{"kind":"done","count":0}\n')
            report = read_backend(path)
            self.assertEqual(report["tick"], "0")
            self.assertIn("no_initial_value", report["diagnostics"][0])

    def test_time_exact_decimal_and_units(self):
        self.assertEqual(parse_time("125.5ns"), ("physical", 125500000, 1))
        self.assertEqual(parse_time(".0001ps"), ("physical", 1, 10))
        self.assertEqual(parse_time("9007199254740993ticks"), ("ticks", 9007199254740993, 1))
        self.assertEqual(parse_time("1s"), ("physical", 10**15, 1))

    def test_bad_time_is_rejected(self):
        for value in ("1", "-1ns", "1.5ticks", "nan", "inf", "1ns;puts x"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_time(value)

    def test_incomplete_backend_is_not_success(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "records.jsonl"
            path.write_text('{"kind":"metadata","scope":"tb.dut"}\n', encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "did not finish"):
                read_backend(path)

    def test_missing_value_does_not_become_x(self):
        row = {"logical_path": "tb.dut.a", "port": "a", "interface_path": "", "modport": "",
               "direction": "input", "direction_source": "port", "waveform_paths": ["tb.dut.a"],
               "width": 4, "shape": {}, "value_bin": None, "status": "not_dumped", "change_tick": "", "detail": ""}
        with tempfile.TemporaryDirectory() as d:
            write_reports({"signals": [row]}, Path(d))
            saved = json.loads((Path(d)/"snapshot.json").read_text(encoding="utf-8"))
            self.assertIsNone(saved["signals"][0]["value_bin"])

    def test_interface_alias_reports_the_waveform_path_without_changing_sv_target(self):
        row = {"kind": "signal", "logical_path": "tb.dut.bus.data", "port": "bus",
               "interface_path": "tb.link", "modport": "slv", "direction": "input",
               "direction_source": "modport", "shape": {}, "status": "ok", "value_bin": "10xz",
               "change_tick": "0", "detail": "",
               "expression": {"kind": "signal", "path": "tb.link.data", "width": 4},
               "waveform_reads": [{"design_paths": ["tb.link.data"], "waveform_path": "tb.dut.bus.data",
                                   "candidates": ["tb.link.data", "tb.dut.bus.data"]}]}
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            path = out/"records.jsonl"
            path.write_text("\n".join(json.dumps(x) for x in (
                {"kind": "metadata", "scope": "tb.dut"}, row, {"kind": "done", "count": 1}))+"\n")
            report = read_backend(path)
            signal, = report["signals"]
            self.assertEqual(signal["waveform_paths"], ["tb.dut.bus.data"])
            self.assertEqual(signal["design_paths"], ["tb.link.data"])
            self.assertEqual(targets(signal["expression"], signal["value_bin"]), [("tb.link.data", "10xz")])
            write_reports(report, out)
            with (out/"snapshot.csv").open(newline="") as stream:
                saved, = csv.DictReader(stream)
            self.assertEqual(json.loads(saved["waveform_paths"]), signal["waveform_paths"])
            self.assertEqual(json.loads(saved["waveform_reads"]), signal["waveform_reads"])
            self.assertIn("FSDB: tb.dut.bus.data", (out/"diagnostics.txt").read_text(encoding="utf-8"))

    def test_unresolved_interface_is_not_reported_as_an_absent_waveform(self):
        row = {"kind": "signal", "logical_path": "tb.dut.bus", "port": "bus", "interface_path": "",
               "direction": "unknown", "direction_source": "unresolved_binding", "modport": "",
               "expression": None, "waveform_reads": [], "status": "unsupported_type", "value_bin": None,
               "detail": "unresolved interface binding (npiModule)"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"records.jsonl"
            path.write_text("\n".join(json.dumps(x) for x in (
                {"kind": "metadata", "scope": "tb.dut"}, row, {"kind": "done", "count": 1}))+"\n")
            report = read_backend(path)
            self.assertFalse(report["values_complete"])
            self.assertFalse(report["directions_complete"])
            self.assertEqual(report["signals"][0]["waveform_paths"], [])
            self.assertIn("vlogan", report["diagnostics"][0])

    def test_alias_literal_partition_preserves_xz(self):
        expr = {"kind": "concat", "width": 6, "operands": [
            {"kind": "signal", "path": "tb.ifc.a", "width": 2},
            {"kind": "select", "width": 4, "suffix": "[5:2]", "offsets": [2,3,4,5],
             "parent": {"kind": "signal", "path": "tb.ifc.b", "width": 8}}]}
        self.assertEqual(targets(expr, "xz1010"), [("tb.ifc.a", "xz"), ("tb.ifc.b[5:2]", "1010")])

    def test_escaped_identifier_is_not_split_at_embedded_dot(self):
        self.assertEqual(hierarchy("tb.\\odd.port .a[0]"), "tb.\\odd.port .a[0]")

    def test_partial_snapshot_cannot_be_applied_silently(self):
        source = task_source({"tb.dut.a": "01xz"}, [], ["missing b"])
        self.assertIn('$fatal(1, "Incomplete', source)
        self.assertIn("4'b01xz", source)
        self.assertIn("release tb.dut.a", source)


if __name__ == "__main__":
    unittest.main()
