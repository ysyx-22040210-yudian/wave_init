"""GUI contracts and process lifecycle; run under Python 3.8+ and a Tk display."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from waveinit.gui import WaveInitApp, read_profile, save_profile
from waveinit.gui_runner import ROOT, SSHSettings, Task, collect_result, load_report, remote_command, run_local


class GUIContracts(unittest.TestCase):
    def test_profile_never_saves_or_loads_password(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"profile.json"
            save_profile(path, {"mode": "ssh", "host": "127.0.0.1", "password": "TEST_SECRET_DO_NOT_SAVE",
                                "force_unknown": True, "future_secret": "ALSO_SECRET"})
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("SECRET", text)
            saved = json.loads(text)
            saved["settings"]["password"] = "injected"
            path.write_text(json.dumps(saved), encoding="utf-8")
            self.assertNotIn("password", read_profile(path))
            self.assertTrue(read_profile(path)["force_unknown"])
            self.assertNotIn("TEST_SECRET", repr(SSHSettings(password="TEST_SECRET")))

    def test_ssh_paths_time_and_timeout_are_validated(self):
        task = Task(mode="ssh", fsdb="/tmp/a.fsdb", kdb="/tmp/kdb", scope="tb.dut", out="/tmp/new", when="125.5ns")
        task.validate()
        task.fsdb = "D:/windows/a.fsdb"
        with self.assertRaises(ValueError):
            task.validate()
        task.fsdb = "/tmp/a.fsdb"
        task.when = "1.5ticks"
        with self.assertRaises(ValueError):
            task.validate()
        task.when = "12ticks"
        for timeout in (float("nan"), float("inf"), -1, 0):
            task.timeout = timeout
            with self.assertRaises(ValueError):
                task.validate()

    def test_failed_run_does_not_display_a_stale_report(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"snapshot.json"
            path.write_text((ROOT/"examples/assign/snapshot.json").read_text(encoding="utf-8"), encoding="utf-8")
            self.assertIsNone(collect_result(1, directory)["report"])
            self.assertIsNotNone(collect_result(2, directory)["report"])

    def test_missing_success_report_is_an_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RuntimeError):
                collect_result(0, directory)

    @unittest.skipUnless(os.name == "posix", "requires a POSIX shell")
    def test_remote_shell_preserves_literal_paths_and_scope(self):
        with tempfile.TemporaryDirectory(prefix="wave init ' ") as directory:
            marker = Path(directory)/"injected"
            value = "tb.\\port;$(touch {});`touch {}` [2]".format(marker, marker)
            settings = SSHSettings(directory=directory, environment="")
            command = remote_command(settings, [sys.executable, "-c", "import json,sys;print(json.dumps(sys.argv[1:]))", value])
            text = subprocess.check_output(["bash", "-c", command], universal_newlines=True)
            self.assertEqual(json.loads(text), [value])
            self.assertFalse(marker.exists())

    @unittest.skipUnless(os.name == "posix", "requires process groups")
    def test_cancel_terminates_vendor_process_group(self):
        with tempfile.TemporaryDirectory(prefix="wave_gui_cancel_") as directory:
            base = Path(directory)
            (base/"wave.fsdb").touch()
            (base/"kdb").mkdir()
            (base/"kdb/db").touch()
            fake = base/"fake verdi.py"
            marker = base/"vendor.json"
            fake.write_text("#!"+sys.executable+"\n"+'''import json,os,subprocess,sys,time
from pathlib import Path
child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
Path(%r).write_text(json.dumps([os.getpid(),child.pid]))
time.sleep(60)
''' % str(marker))
            fake.chmod(0o700)
            task = Task(fsdb=str(base/"wave.fsdb"), kdb=str(base/"kdb"), scope="tb.dut",
                        out=str(base/"result"), verdi=str(fake), timeout=30)
            task.validate()
            stop, result = threading.Event(), []
            def worker():
                try:
                    result.append(run_local(task, stop, lambda *args: None))
                except Exception as exc:
                    result.append(exc)
            thread = threading.Thread(target=worker, daemon=True)
            thread.start()
            deadline = time.monotonic()+10
            while not marker.exists() and thread.is_alive() and time.monotonic()<deadline:
                time.sleep(.05)
            stop.set()
            thread.join(10)
            self.assertFalse(thread.is_alive(), "cancellation did not complete")
            self.assertTrue(marker.exists(), result)
            self.assertIsInstance(result[0], dict)
            self.assertEqual(result[0]["code"], 130)
            error = json.loads((base/"result/error.json").read_text())
            self.assertEqual(error["status"], "cancelled")
            for pid in json.loads(marker.read_text()):
                status = Path("/proc")/str(pid)/"stat"
                self.assertTrue(not status.exists() or status.read_text().split(") ", 1)[1].startswith("Z"),
                                "vendor process survived cancellation: " + str(pid))


class TkContracts(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest("Tk display unavailable: " + str(exc))
        self.root.withdraw()
        self.app = WaveInitApp(self.root)

    def tearDown(self):
        if hasattr(self, "app"):
            self.app.destroy()

    def test_filter_details_and_assign_preview_keep_four_states(self):
        directory = ROOT/"examples/assign"
        report = load_report(directory/"snapshot.json")
        self.app.install_report(report, directory)
        self.assertEqual(len(self.app.tree.get_children()), 7)
        self.app.filter_text.set("assign_top.u.a")
        self.app.filter_signals()
        rows = self.app.tree.get_children()
        self.assertEqual(len(rows), 1)
        self.app.tree.selection_set(rows[0])
        self.app.show_detail()
        self.assertIn("10xz0101", self.app.detail.get("1.0", "end"))
        self.assertIn("assign a = 8'b10xz0101;", self.app.preview_text)

    def test_partial_report_remains_inspectable(self):
        directory = ROOT/"examples/assign"
        report = load_report(directory/"snapshot.json")
        report["signals"][0].update(status="not_dumped", value_bin=None, detail="test missing signal")
        self.app.events.put(("finished", {"code": 2, "directory": str(directory), "report": report, "error": ""}))
        # Exercise the same completion path that a background extraction uses.
        self.root.after_cancel(self.app.poll_id)
        self.app.poll()
        self.assertIn("部分完成", self.app.status.get())
        self.app.only_issues.set(True)
        self.app.filter_signals()
        rows = self.app.tree.get_children()
        self.assertEqual(len(rows), 1)
        self.assertEqual(self.app.tree.item(rows[0], "values")[4], "—")
        self.assertIn("not_dumped", self.app.diagnostics.get("1.0", "end"))


if __name__ == "__main__":
    unittest.main()
