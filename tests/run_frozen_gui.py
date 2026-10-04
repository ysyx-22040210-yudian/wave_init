#!/usr/bin/env python3
"""Exercise the shipped GUI executable through Tk's authenticated X11 send.

The driver uses system Tk solely for UI automation; the app and its CLI child
use the bundled Python runtime. Run this harness under a fresh xvfb-run.
"""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import time
import tkinter as tk

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", required=True)
    parser.add_argument("--split-case", help="DUT-only split-interface fixture directory containing waves.fsdb")
    parser.add_argument("--split-kdb", help="matching split-interface simv.daidir")
    args = parser.parse_args()
    release = Path(args.release).resolve()
    evidence = Path(tempfile.mkdtemp(prefix="frozen_gui_", dir=str(ROOT / "build")))
    output = evidence / "snapshot"
    root = tk.Tk()
    root.withdraw()
    before = set(root.tk.splitlist(root.tk.call("winfo", "interps")))
    log = (evidence / "gui.log").open("w")
    proc = subprocess.Popen(["bash", "-c", 'source "$1"; exec "$2"', "gui-test",
                             str(ROOT / "tests/env.sh"), str(release / "start_gui.sh")],
                            cwd="/tmp", stdout=log, stderr=subprocess.STDOUT)
    interpreter = None

    def wait_until(predicate, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            assert proc.poll() is None, "GUI process exited; see " + str(evidence / "gui.log")
            root.update()
            value = predicate()
            if value:
                return value
            time.sleep(.04)
        raise AssertionError("GUI operation timed out; evidence: " + str(evidence))

    def remote(*argv):
        # One Tcl list preserves spaces and metacharacters in every argument.
        return root.tk.call("send", interpreter, root.tk.call("list", *argv))

    def descendants(widget):
        result = []
        for child in root.tk.splitlist(remote("winfo", "children", widget)):
            result.append(child)
            result.extend(descendants(child))
        return result

    def find_text(text):
        for widget in descendants("."):
            try:
                if remote(widget, "cget", "-text") == text:
                    return widget
            except tk.TclError:
                pass
        raise AssertionError("Widget missing: " + text)

    def set_field(label_text, value):
        label = find_text(label_text)
        parent = remote("winfo", "parent", label)
        grid = root.tk.splitlist(remote("grid", "info", label))
        row = int(dict(zip(grid[::2], grid[1::2]))["-row"])
        frame, = root.tk.splitlist(remote("grid", "slaves", parent, "-row", row + 1))
        entries = [w for w in descendants(frame) if remote("winfo", "class", w) == "TEntry"]
        entry, = entries
        variable = remote(entry, "cget", "-textvariable")
        remote("set", variable, str(value))

    try:
        interpreter = wait_until(lambda: next(iter(set(root.tk.splitlist(
            root.tk.call("winfo", "interps"))) - before), None), 15)
        wait_until(lambda: len(descendants(".")) > 40, 15)
        split = Path(args.split_case).resolve() if args.split_case else None
        set_field("FSDB 波形文件", split/"waves.fsdb" if split else ROOT / "build/fixture/waves.fsdb")
        set_field("KDB 目录 / simv.daidir", Path(args.split_kdb).resolve() if split else ROOT / "build/fixture/simv.daidir")
        set_field("模块实例层次", "split_top.dut" if split else "snapshot_top.dut")
        if split:
            set_field("采样时刻", "1")
        set_field("输出目录（新目录或空目录）", output)
        button = find_text("提取快照并生成 SV")
        remote(button, "invoke")
        wait_until(lambda: "disabled" in root.tk.splitlist(remote(button, "state")), 5)
        # Querying the actual app's Tk interpreter while extraction runs also
        # verifies that its event loop continues to service events.
        responses = [0]

        def complete():
            responses[0] += 1
            return "disabled" not in root.tk.splitlist(remote(button, "state"))

        wait_until(complete, 90)
        report = json.loads((output / "snapshot.json").read_text(encoding="utf-8"))
        assert report["complete"]
        if split:
            expected = {"split_top.dut.rst_n": "1", "split_top.dut.bus.clk": "1", "split_top.dut.bus.req": "1",
                        "split_top.dut.bus.pad": "z", "split_top.dut.bus.data": "10xz0101"}
            assert any(r["waveform_paths"] != r["design_paths"] for r in report["signals"])
        else:
            expected = {r["logical_path"]: r["value_bin"] for r in json.loads(
                (ROOT / "examples/snapshot/snapshot.json").read_text())["signals"]}
        assert {r["logical_path"]: r["value_bin"] for r in report["signals"]} == expected
        widgets = descendants(".")
        tree, = [w for w in widgets if remote("winfo", "class", w) == "Treeview"]
        assert len(root.tk.splitlist(remote(tree, "children", ""))) == len(expected)
        previews = [remote(w, "get", "1.0", "end") for w in widgets
                    if remote("winfo", "class", w) == "Text"]
        if split:
            assert any("assign bus.data = 8'b10xz0101;" in text for text in previews)
        else:
            assert any("assign scalar = 8'b10010110;" in text and
                       "assign bus.wdata = 8'b10100101;" in text for text in previews)
        assert responses[0] >= 5
        proof = {"status": "pass", "mode": "frozen_gui_local", "signals": len(expected), "interface_alias_case": bool(split),
                 "responsive_ui_queries": responses[0], "assign_preview": True,
                 "release": str(release), "evidence_directory": str(evidence)}
        (evidence / "results.json").write_text(json.dumps(proof, indent=2) + "\n")
        print(json.dumps(proof, indent=2))
        print("FROZEN_GUI_PASS: Run button, bundled CLI child, {} real NPI values and assign preview".format(len(expected)))
    finally:
        if interpreter and proc.poll() is None:
            try:
                remote("eval", remote("wm", "protocol", ".", "WM_DELETE_WINDOW"))
            except tk.TclError:
                pass
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.terminate()
            proc.wait(timeout=5)
        root.destroy()
        log.close()


if __name__ == "__main__":
    main()
