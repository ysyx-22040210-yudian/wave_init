import json
from pathlib import Path
import tempfile
import unittest

from waveinit.cli import parse_time, read_backend, write_reports
from waveinit.sv import hierarchy, targets, task_source


class BoundaryContracts(unittest.TestCase):
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
