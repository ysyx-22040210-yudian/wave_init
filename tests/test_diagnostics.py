"""Failure evidence and incremental traces must survive without credentials."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from waveinit.cli import main
from waveinit.diagnostics import RunLog, TraceTail, console_text


class DiagnosticContracts(unittest.TestCase):
    def test_ascii_locale_does_not_break_chinese_error_printing(self):
        buffer = io.BytesIO()
        stream = io.TextIOWrapper(buffer, encoding="ascii")
        console_text("缺失 interface 绑定\n", stream=stream)
        self.assertEqual(buffer.getvalue().decode("utf-8"), "缺失 interface 绑定\n")
        stream.detach()

    def test_failed_validation_saves_environment_and_stack_without_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "failed"
            argv = ["--fsdb", directory + "/missing.fsdb", "--kdb", directory + "/missing_kdb",
                    "--scope", "top.g[1].dut", "--time", "1ns", "--out", str(out)]
            with patch.dict(os.environ, {"WAVE_INIT_SSH_PASSWORD": "test-password-never-log",
                                        "SNPSLMD_LICENSE_FILE": "test-private-license-server"}), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(argv), 1)
            runtime = json.loads((out / "runtime.json").read_text(encoding="utf-8"))
            self.assertEqual(runtime["exit_code"], 1)
            self.assertTrue(runtime["license_configured"]["SNPSLMD_LICENSE_FILE"])
            self.assertEqual(runtime["request"]["scope"], "top.g[1].dut")
            text = "\n".join(p.read_text(encoding="utf-8") for p in out.iterdir() if p.is_file())
            self.assertIn("run.failed", text)
            self.assertIn("Traceback", text)
            self.assertNotIn("test-password-never-log", text)
            self.assertNotIn("test-private-license-server", text)

    def test_nonempty_output_is_never_modified_by_logging(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "original.log"
            marker.write_text("keep this", encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["--fsdb", "absent", "--kdb", "absent", "--scope", "dut",
                                       "--time", "1ns", "--out", directory]), 1)
            self.assertEqual(list(Path(directory).iterdir()), [marker])
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep this")

    def test_trace_handles_split_utf8_and_retains_warning_with_debug_off(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            console = []
            log = RunLog(out / "run.log", console=console.append)
            tail = TraceTail(out / "trace.log", log)
            try:
                row = {"utc": "sample", "level": "WARNING", "event": "interface.unresolved", "detail": "缺失绑定"}
                data = (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")
                split = data.index("缺".encode("utf-8")) + 1
                tail.path.write_bytes(data[:split])
                tail.poll()
                self.assertFalse(console)
                with tail.path.open("ab") as stream:
                    stream.write(data[split:])
                    stream.write(b'{"level":"DEBUG","event":"fsdb.cache"}\n')
                tail.poll()
                self.assertIn("缺失绑定", console[0])
                self.assertNotIn("fsdb.cache", "".join(console))
                with tail.path.open("ab") as stream:
                    stream.write(b'{"unfinished":')
                tail.poll(final=True)
                self.assertIn("trace_interrupted", "".join(console))
            finally:
                log.close()


if __name__ == "__main__":
    unittest.main()
