#!/usr/bin/env python3
"""Drive the actual Tk Run button against Verdi, locally or over SSH."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
import uuid

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from waveinit.gui import RemoteBrowser, WaveInitApp, read_profile


def pump(root, predicate, seconds=120):
    deadline = time.monotonic()+seconds
    while predicate() and time.monotonic()<deadline:
        root.update()
        time.sleep(.015)
    root.update()
    assert not predicate(), "GUI operation timed out"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ssh", action="store_true")
    parser.add_argument("--screenshot")
    args = parser.parse_args()
    evidence_dir = Path(tempfile.mkdtemp(prefix="gui_acceptance_", dir=str(ROOT/"build")))
    root = tk.Tk()
    root.withdraw()
    app = WaveInitApp(root)
    if args.ssh:
        for key, value in read_profile(ROOT/"examples/gui_vm.json").items():
            app.vars[key].set(value)
    errors = []
    root.report_callback_exception = lambda *exc: errors.append(str(exc))
    base = "/root/wave_init" if args.ssh else str(ROOT)
    output = base+"/out/gui_acceptance_"+uuid.uuid4().hex
    values = {"mode": "ssh" if args.ssh else "local", "fsdb": base+"/build/fixture/waves.fsdb",
              "kdb": base+"/build/fixture/simv.daidir", "scope": "snapshot_top.dut", "time_value": "7",
              "time_unit": "ns", "out": output}
    values["debug"] = True
    if args.ssh:
        values["password"] = os.environ.get("WAVE_INIT_SSH_PASSWORD", "")
    for key, value in values.items():
        app.vars[key].set(value)
    app.mode_changed()
    heartbeat = [0]
    def beat():
        heartbeat[0] += 1
        if app.busy:
            root.after(20, beat)
    try:
        if args.ssh:
            selected = []
            browser = RemoteBrowser(root, app.ssh_settings(), base+"/build/fixture", True, selected.append)
            pump(root, lambda: str(browser.choose["state"]) == "disabled", 30)
            matches = [i for i in browser.tree.get_children() if browser.tree.item(i, "values")[0] == "waves.fsdb"]
            assert len(matches) == 1
            browser.tree.selection_set(matches[0])
            browser.accept()
            assert selected == [base+"/build/fixture/waves.fsdb"]
        app.run_button.invoke()
        assert app.busy, app.status.get()
        root.after(20, beat)
        pump(root, lambda: app.busy)
        assert app.run_result and app.run_result["code"] == 0, (app.run_result, app.log.get("1.0", "end"))
        assert len(app.tree.get_children()) == 16
        signals = {r["logical_path"]: r for r in app.report["signals"]}
        assert signals["snapshot_top.dut.scalar"]["value_bin"] == "10010110"
        assert signals["snapshot_top.dut.bus.wdata"]["value_bin"] == "10100101"
        assert "assign scalar = 8'b10010110;" in app.preview_text
        assert "assign bus.wdata = 8'b10100101;" in app.preview_text
        for name in ("wave_init.log", "npi_trace.log", "npi_records.jsonl", "runtime.json", "gui.log"):
            assert (app.result_directory/name).is_file(), name
        assert "npi.fsdb.candidates" in app.log.get("1.0", "end")
        assert "interface.bound" in (app.result_directory/"npi_trace.log").read_text()
        assert heartbeat[0] >= 5, "Tk event loop did not remain responsive"
        assert not errors, errors
        if args.screenshot:
            from PIL import ImageGrab
            root.deiconify()
            root.lift()
            root.attributes("-topmost", True)
            root.update()
            app.tabs.select(1)
            root.update()
            time.sleep(.3)
            ImageGrab.grab(bbox=(root.winfo_rootx(), root.winfo_rooty(),
                                root.winfo_rootx()+root.winfo_width(), root.winfo_rooty()+root.winfo_height())).save(args.screenshot)
        evidence = {"status": "pass", "mode": "ssh" if args.ssh else "local", "python": sys.version,
                    "tk": root.tk.call("info", "patchlevel"), "signals": 16, "responsive_heartbeats": heartbeat[0],
                    "output": output, "local_report": str(app.result_directory), "sftp_browser": bool(args.ssh)}
        evidence["diagnostic_logs"] = "pass"
        (evidence_dir/"results.json").write_text(json.dumps(evidence, indent=2)+"\n", encoding="utf-8")
        (evidence_dir/"gui.log").write_text(app.log.get("1.0", "end"), encoding="utf-8")
        print(json.dumps(evidence, indent=2))
        print("RESULTS " + str(evidence_dir))
    finally:
        app.destroy()


if __name__ == "__main__":
    main()
