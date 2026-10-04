"""Tkinter frontend. Widgets are only accessed on the Tk main thread."""
import argparse
import getpass
import json
import os
from pathlib import Path
import posixpath
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, font, messagebox, ttk

from . import __version__
from .gui_runner import (ROOT, SSHSettings, Task, list_remote, load_report,
                         run_local, run_ssh, test_connection)
from .portable import external_environment, output_root

PROFILE_KEYS = ("mode", "fsdb", "kdb", "scope", "time_value", "time_unit", "out",
                "timeout", "verdi", "sv_target", "interface_maps", "force_unknown", "debug",
                "host", "port", "user", "directory", "python", "environment")
PREVIEW_LIMIT = 1024 * 1024


def save_profile(path, values):
    # An explicit allowlist keeps passwords and future secret fields out of files.
    data = {key: values[key] for key in PROFILE_KEYS if key in values}
    Path(path).write_text(json.dumps({"gui_profile_version": 1, "settings": data},
                                    ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_profile(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("gui_profile_version") != 1 or not isinstance(data.get("settings"), dict):
        raise ValueError("请选择 wave_init GUI 保存的配置 JSON。")
    values = {key: data["settings"][key] for key in PROFILE_KEYS if key in data["settings"]}
    for key, value in values.items():
        if (key in ("force_unknown", "debug") and not isinstance(value, bool)) or (key not in ("force_unknown", "debug") and not isinstance(value, str)):
            raise ValueError("配置字段类型错误：" + key)
    if values.get("mode", "local") not in ("local", "ssh") or values.get("time_unit", "ns") not in ("fs", "ps", "ns", "us", "ms", "s", "ticks"):
        raise ValueError("配置中的执行方式或时间单位无效。")
    return values


def open_path(path):
    path = str(Path(path).resolve())
    if os.name == "nt":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path], env=external_environment())
    else:
        subprocess.Popen(["xdg-open", path], env=external_environment(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class RemoteBrowser(tk.Toplevel):
    """Read-only SFTP browser with all network work outside Tk callbacks."""
    def __init__(self, parent, settings, directory, files, selected):
        super().__init__(parent)
        self.title("虚拟机文件选择 · " + settings.host)
        self.geometry("760x510")
        self.transient(parent)
        self.settings, self.files, self.selected = settings, files, selected
        self.events, self.serial, self.closed = queue.Queue(), 0, False
        self.current = directory
        self.path = tk.StringVar(self, value=directory)
        self.status = tk.StringVar(self, value="")
        bar = ttk.Frame(self, padding=10)
        bar.pack(fill="x")
        ttk.Button(bar, text="上一级", command=self.up).pack(side="left", padx=(0, 8))
        entry = ttk.Entry(bar, textvariable=self.path)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda event: self.load(self.path.get()))
        ttk.Button(bar, text="转到", command=lambda: self.load(self.path.get())).pack(side="left", padx=(8, 0))
        frame = ttk.Frame(self, padding=(10, 0))
        frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(frame, columns=("name", "kind"), show="headings", selectmode="browse")
        self.tree.heading("name", text="名称")
        self.tree.heading("kind", text="类型")
        self.tree.column("name", width=560)
        self.tree.column("kind", width=90, stretch=False)
        scroll = ttk.Scrollbar(frame, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", self.enter)
        self.tree.bind("<Return>", self.enter)
        footer = ttk.Frame(self, padding=10)
        footer.pack(fill="x")
        ttk.Label(footer, textvariable=self.status).pack(side="left", fill="x", expand=True)
        self.choose = ttk.Button(footer, text="选择 FSDB" if files else "选择此目录", command=self.accept)
        self.choose.pack(side="right")
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.grab_set()
        self.load(directory)
        self.poll_id = self.after(100, self.poll)

    def load(self, path):
        self.serial += 1
        serial = self.serial
        self.choose.configure(state="disabled")
        self.status.set("正在读取虚拟机目录…")
        def worker():
            try:
                result = list_remote(self.settings, path, self.files)
                self.events.put((serial, result, ""))
            except Exception as exc:
                self.events.put((serial, None, str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        if self.closed:
            return
        try:
            while True:
                serial, result, error = self.events.get_nowait()
                if serial != self.serial:
                    continue
                if error:
                    self.status.set("目录读取失败")
                    messagebox.showerror("SSH 文件浏览", error, parent=self)
                    continue
                self.current, entries = result
                self.path.set(self.current)
                self.tree.delete(*self.tree.get_children())
                for index, (name, is_dir) in enumerate(entries):
                    self.tree.insert("", "end", iid=str(index), values=(name, "目录" if is_dir else "FSDB"))
                self.status.set("{} 项；双击目录进入".format(len(entries)))
                self.choose.configure(state="normal")
        except queue.Empty:
            pass
        self.poll_id = self.after(100, self.poll)

    def up(self):
        self.load(posixpath.dirname(self.current.rstrip("/")) or "/")

    def enter(self, event=None):
        chosen = self.tree.selection()
        if not chosen:
            return
        name, kind = self.tree.item(chosen[0], "values")
        if kind == "目录":
            self.load(posixpath.join(self.current, name))
        elif self.files:
            self.accept()

    def accept(self):
        chosen = self.tree.selection()
        path = self.current
        if chosen:
            name, kind = self.tree.item(chosen[0], "values")
            if (self.files and kind != "FSDB") or (not self.files and kind != "目录"):
                return
            path = posixpath.join(self.current, name)
        elif self.files:
            return
        self.selected(path)
        self.close()

    def close(self):
        self.closed = True
        if hasattr(self, "poll_id"):
            self.after_cancel(self.poll_id)
        self.destroy()


class WaveInitApp:
    def __init__(self, root):
        self.root = root
        root.title("wave_init · FSDB 端口快照")
        root.geometry("1280x820")
        root.minsize(1020, 700)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.events, self.stop = queue.Queue(), threading.Event()
        self.busy = self.closing = False
        self.report, self.result_directory = None, None
        self.controls, self.ssh_controls = [], []
        self.filter_after = None
        self.preview_text = ""
        self.run_result = None
        defaults = dict(mode="ssh" if os.name == "nt" else "local", fsdb="", kdb="", scope="",
                        time_value="7", time_unit="ns", out="", timeout="300", verdi="", sv_target="",
                        interface_maps="", host="", port="22", user=getpass.getuser(), password="",
                        directory="", python="python3", environment="")
        self.vars = {key: tk.StringVar(root, value=value) for key, value in defaults.items()}
        self.vars["force_unknown"] = tk.BooleanVar(root, value=False)
        self.vars["debug"] = tk.BooleanVar(root, value=False)
        self.status = tk.StringVar(root, value="就绪 · 选择文件并填写完整模块实例层次")
        self.result_summary = tk.StringVar(root, value="尚未加载快照")
        self.filter_text = tk.StringVar(root, value="")
        self.only_issues = tk.BooleanVar(root, value=False)
        self.visible_count = tk.StringVar(root, value="")
        self.preview_file = tk.StringVar(root, value="tb_snapshot.sv")
        self.configure_style()
        self.build_menu()
        self.build_layout()
        self.mode_changed()
        self.filter_text.trace_add("write", self.schedule_filter)
        self.poll_id = root.after(80, self.poll)

    def configure_style(self):
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        available = set(font.families(self.root))
        family = next((n for n in ("Microsoft YaHei UI", "Microsoft YaHei", "WenQuanYi Zen Hei", "Noto Sans CJK SC") if n in available), None)
        if family:
            for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
                font.nametofont(name).configure(family=family, size=10)
        fixed_family = next((n for n in ("Consolas", "DejaVu Sans Mono", "Liberation Mono") if n in available), None)
        font.nametofont("TkFixedFont").configure(size=11)
        if fixed_family:
            font.nametofont("TkFixedFont").configure(family=fixed_family)
        style.configure("TFrame", background="#f4f6fa")
        style.configure("TLabel", background="#f4f6fa")
        style.configure("TButton", background="#ffffff", foreground="#23384e", bordercolor="#cbd5e1", padding=(8, 5))
        style.map("TButton", background=[("active", "#e9f1fb"), ("disabled", "#e7ebf1")])
        style.configure("TNotebook", background="#f4f6fa", bordercolor="#d7dfe9")
        style.configure("TNotebook.Tab", background="#e9eef5", foreground="#23384e")
        style.map("TNotebook.Tab", background=[("selected", "#ffffff")])
        style.configure("Title.TLabel", font=(family or "TkDefaultFont", 20, "bold"), foreground="#16324f")
        style.configure("Muted.TLabel", foreground="#526478")
        style.configure("Accent.TButton", foreground="white", background="#2166b2", padding=(14, 8))
        style.map("Accent.TButton", background=[("disabled", "#b0bccb"), ("active", "#174f8b")])
        style.configure("Treeview", rowheight=28, background="white", fieldbackground="white")
        style.configure("Treeview.Heading", padding=(5, 7), background="#e9eef5", foreground="#23384e")
        style.configure("TNotebook.Tab", padding=(12, 7))
        self.root.configure(background="#f4f6fa")

    def build_menu(self):
        menu = tk.Menu(self.root)
        files = tk.Menu(menu, tearoff=False)
        files.add_command(label="打开配置…", command=self.load_configuration)
        files.add_command(label="保存配置…", command=self.save_configuration)
        files.add_separator()
        files.add_command(label="打开已有 snapshot.json…", command=self.open_report)
        files.add_command(label="查看 assign 示例", command=lambda: self.load_snapshot(ROOT / "examples/assign/snapshot.json"))
        files.add_separator()
        files.add_command(label="退出", command=self.close)
        menu.add_cascade(label="文件", menu=files)
        menu.add_command(label="使用说明", command=lambda: self.open_local_path(ROOT / "README.md"))
        self.root.configure(menu=menu)

    def build_layout(self):
        header = ttk.Frame(self.root, padding=(20, 15, 20, 12))
        header.pack(fill="x")
        ttk.Label(header, text="wave_init", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="FSDB 端口快照  /  assign SystemVerilog", style="Muted.TLabel").pack(side="left", padx=18)
        ttk.Label(header, text="v" + __version__, style="Muted.TLabel").pack(side="right")
        panes = ttk.Panedwindow(self.root, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=16)
        sidebar = ttk.Frame(panes, width=350, padding=(0, 0, 12, 0))
        side_tabs = ttk.Notebook(sidebar)
        side_tabs.pack(fill="both", expand=True)
        task = ttk.Frame(side_tabs, padding=14)
        options = ttk.Frame(side_tabs, padding=14)
        side_tabs.add(task, text="提取设置")
        side_tabs.add(options, text="SSH / 高级")
        task.columnconfigure(0, weight=1)
        ttk.Label(task, text="执行位置").grid(row=0, column=0, sticky="w")
        self.mode_select = ttk.Combobox(task, values=("ssh", "local"), state="readonly", textvariable=self.vars["mode"])
        self.mode_select.grid(row=1, column=0, sticky="ew", pady=(3, 5))
        self.mode_select.bind("<<ComboboxSelected>>", lambda event: self.mode_changed())
        self.controls.append(self.mode_select)
        self.path_hint = ttk.Label(task, text="", style="Muted.TLabel", wraplength=310)
        self.path_hint.grid(row=2, column=0, sticky="w", pady=(0, 12))
        row = 3
        for key, title, browse in (("fsdb", "FSDB 波形文件", True), ("kdb", "KDB 目录 / simv.daidir", True),
                                   ("scope", "模块实例层次", False)):
            row = self.field(task, row, title, key, (lambda k=key: self.browse(k)) if browse else None)
        ttk.Label(task, text="采样时刻").grid(row=row, column=0, sticky="w")
        time_box = ttk.Frame(task)
        time_box.grid(row=row+1, column=0, sticky="ew", pady=(3, 12))
        time_box.columnconfigure(0, weight=1)
        entry = ttk.Entry(time_box, textvariable=self.vars["time_value"])
        entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        unit = ttk.Combobox(time_box, width=6, state="readonly", textvariable=self.vars["time_unit"],
                            values=("fs", "ps", "ns", "us", "ms", "s", "ticks"))
        unit.grid(row=0, column=1)
        self.controls.extend((entry, unit))
        row = self.field(task, row+2, "输出目录（新目录或空目录）", "out", lambda: self.browse("out"))
        new_out = ttk.Button(task, text="生成新的输出目录名", command=self.new_output)
        new_out.grid(row=row, column=0, sticky="w", pady=(0, 10))
        self.controls.append(new_out)
        note = "SV 会将已确认的 input/inout 写成 assign 常量；interface 按实际 modport 方向筛选。"
        ttk.Label(task, text=note, style="Muted.TLabel", wraplength=310).grid(row=row+1, column=0, sticky="nw", pady=8)
        task.rowconfigure(row+2, weight=1)
        self.build_options(options)
        actions = ttk.Frame(sidebar, padding=(0, 12, 0, 0))
        actions.pack(fill="x")
        self.run_button = ttk.Button(actions, text="提取快照并生成 SV", style="Accent.TButton", command=self.start)
        self.run_button.pack(side="left", fill="x", expand=True)
        self.cancel_button = ttk.Button(actions, text="取消", command=self.cancel, state="disabled")
        self.cancel_button.pack(side="left", padx=(8, 0))
        panes.add(sidebar, weight=0)
        right = ttk.Frame(panes)
        panes.add(right, weight=1)
        toolbar = ttk.Frame(right, padding=(0, 3, 0, 10))
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="打开已有快照", command=self.open_report).pack(side="left")
        ttk.Button(toolbar, text="查看示例", command=lambda: self.load_snapshot(ROOT / "examples/assign/snapshot.json")).pack(side="left", padx=6)
        self.folder_button = ttk.Button(toolbar, text="打开结果目录", command=self.open_result, state="disabled")
        self.folder_button.pack(side="right")
        ttk.Label(right, textvariable=self.result_summary, wraplength=760, style="Muted.TLabel").pack(anchor="w", pady=(0, 10))
        self.tabs = ttk.Notebook(right)
        self.tabs.pack(fill="both", expand=True)
        signals_tab = ttk.Frame(self.tabs, padding=8)
        sv_tab = ttk.Frame(self.tabs, padding=8)
        diagnostics_tab = ttk.Frame(self.tabs, padding=8)
        logs_tab = ttk.Frame(self.tabs, padding=8)
        for frame, name in ((signals_tab, "信号结果"), (sv_tab, "SV 预览"), (diagnostics_tab, "诊断"), (logs_tab, "运行日志")):
            self.tabs.add(frame, text=name)
        self.signals_tab, self.logs_tab = signals_tab, logs_tab
        filters = ttk.Frame(signals_tab)
        filters.pack(fill="x", pady=(0, 8))
        ttk.Label(filters, text="筛选").pack(side="left")
        ttk.Entry(filters, textvariable=self.filter_text).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Checkbutton(filters, text="仅异常 / 未知", variable=self.only_issues, command=self.filter_signals).pack(side="right")
        grid = ttk.Frame(signals_tab)
        grid.pack(fill="both", expand=True)
        grid.columnconfigure(0, weight=1)
        grid.rowconfigure(0, weight=1)
        columns = ("path", "direction", "modport", "width", "value", "status")
        self.tree = ttk.Treeview(grid, columns=columns, show="headings", selectmode="browse")
        for key, title, width in zip(columns, ("逻辑端口路径", "方向", "Modport", "位宽", "四态值 · 二进制", "状态"), (300, 75, 75, 55, 235, 110)):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=40, stretch=(key in ("path", "value")))
        self.tree.grid(row=0, column=0, sticky="nsew")
        vs = ttk.Scrollbar(grid, orient="vertical", command=self.tree.yview)
        hs = ttk.Scrollbar(grid, orient="horizontal", command=self.tree.xview)
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.tree.tag_configure("error", foreground="#b52b32")
        self.tree.tag_configure("unknown", foreground="#9b6500")
        self.tree.bind("<<TreeviewSelect>>", self.show_detail)
        ttk.Label(signals_tab, textvariable=self.visible_count, style="Muted.TLabel").pack(anchor="w", pady=5)
        self.detail = self.text_widget(signals_tab, height=7, wrap="word")
        preview_bar = ttk.Frame(sv_tab)
        preview_bar.pack(fill="x", pady=(0, 8))
        choice = ttk.Combobox(preview_bar, textvariable=self.preview_file, state="readonly", width=20,
                              values=("tb_snapshot.sv", "snapshot.svh"))
        choice.pack(side="left")
        choice.bind("<<ComboboxSelected>>", lambda event: self.show_preview())
        ttk.Button(preview_bar, text="复制预览内容", command=self.copy_preview).pack(side="right")
        self.preview = self.text_widget(sv_tab, wrap="none")
        self.diagnostics = self.text_widget(diagnostics_tab, wrap="word")
        self.log = self.text_widget(logs_tab, wrap="word")
        footer = ttk.Frame(self.root, padding=(18, 10))
        footer.pack(fill="x")
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=140)
        self.progress.pack(side="right", padx=(10, 0))
        ttk.Label(footer, textvariable=self.status).pack(side="left", fill="x", expand=True)

    def field(self, parent, row, title, key, browse=None, secret=False):
        ttk.Label(parent, text=title, wraplength=295).grid(row=row, column=0, sticky="w")
        line = ttk.Frame(parent)
        line.grid(row=row+1, column=0, sticky="ew", pady=(3, 11))
        line.columnconfigure(0, weight=1)
        entry = ttk.Entry(line, textvariable=self.vars[key], show="*" if secret else "")
        entry.grid(row=0, column=0, sticky="ew")
        self.controls.append(entry)
        if browse:
            button = ttk.Button(line, text="浏览…", width=6, command=browse)
            button.grid(row=0, column=1, padx=(7, 0))
            self.controls.append(button)
        return row+2

    def build_options(self, parent):
        # A canvas keeps every advanced field reachable on smaller displays.
        canvas = tk.Canvas(parent, highlightthickness=0, background="#f4f6fa", width=300)
        scroll = ttk.Scrollbar(parent, command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        body = ttk.Frame(canvas, padding=(0, 0, 10, 0))
        body.columnconfigure(0, weight=1)
        window = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))
        row = 0
        for key, title in (("host", "SSH 主机"), ("port", "SSH 端口"), ("user", "SSH 用户"),
                           ("password", "密码（仅保存在内存）"), ("directory", "远端工具目录"),
                           ("python", "远端 Python 可执行文件"), ("environment", "远端环境脚本（可留空）")):
            before = len(self.controls)
            row = self.field(body, row, title, key, secret=(key == "password"))
            self.ssh_controls.extend(self.controls[before:])
        button = ttk.Button(body, text="测试 SSH 连接", command=self.test_ssh)
        button.grid(row=row, column=0, sticky="ew", pady=(0, 14))
        self.ssh_controls.append(button)
        self.controls.append(button)
        row += 1
        for key, title in (("timeout", "查询超时（秒）"), ("verdi", "Verdi 可执行路径（可留空）"),
                           ("sv_target", "SVH 目标实例重映射（可留空）"), ("interface_maps", "SVH Interface 映射（分号分隔 PORT=PATH）")):
            row = self.field(body, row, title, key)
        unknown = ttk.Checkbutton(body, text="驱动未知方向成员（无 modport）", variable=self.vars["force_unknown"])
        unknown.grid(row=row, column=0, sticky="w", pady=8)
        self.controls.append(unknown)
        detailed = ttk.Checkbutton(body, text="实时显示详细日志（绑定 / FSDB 查询）", variable=self.vars["debug"])
        detailed.grid(row=row+1, column=0, sticky="w", pady=8)
        self.controls.append(detailed)
        ttk.Label(body, text="提取时使用本设备的 Verdi 环境。\nSSH 只取回报告，不传输 FSDB / KDB。",
                  wraplength=285, style="Muted.TLabel").grid(row=row+2, column=0, sticky="w", pady=8)

    def text_widget(self, parent, height=None, wrap="none"):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=height is None)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        widget = tk.Text(frame, wrap=wrap, height=height or 12, relief="flat", padx=10, pady=8,
                         background="white", foreground="#23384e", font="TkFixedFont", state="disabled")
        widget.grid(row=0, column=0, sticky="nsew")
        vs = ttk.Scrollbar(frame, command=widget.yview)
        vs.grid(row=0, column=1, sticky="ns")
        widget.configure(yscrollcommand=vs.set)
        if wrap == "none":
            hs = ttk.Scrollbar(frame, orient="horizontal", command=widget.xview)
            hs.grid(row=1, column=0, sticky="ew")
            widget.configure(xscrollcommand=hs.set)
        return widget

    def set_text(self, widget, text):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def append_log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text)
        if int(self.log.index("end-1c").split(".")[0]) > 3000:
            self.log.delete("1.0", "500.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def mode_changed(self):
        remote = self.vars["mode"].get() == "ssh"
        self.path_hint.configure(text="SSH：文件与输出路径均在虚拟机上。" if remote else "本机：在安装 Verdi 的 Linux 上执行。")
        for widget in self.ssh_controls:
            widget.configure(state="disabled" if self.busy or not remote else "normal")

    def ssh_settings(self):
        settings = SSHSettings(host=self.vars["host"].get().strip(), port=int(self.vars["port"].get()),
                               user=self.vars["user"].get().strip(), password=self.vars["password"].get(),
                               directory=self.vars["directory"].get().strip(), python=self.vars["python"].get().strip(),
                               environment=self.vars["environment"].get().strip())
        settings.validate()
        return settings

    def make_task(self):
        task = Task(mode=self.vars["mode"].get(), fsdb=self.vars["fsdb"].get().strip(),
                    kdb=self.vars["kdb"].get().strip(), scope=self.vars["scope"].get().strip(),
                    when=self.vars["time_value"].get().strip()+self.vars["time_unit"].get(),
                    out=self.vars["out"].get().strip(), timeout=float(self.vars["timeout"].get()),
                    verdi=self.vars["verdi"].get().strip(), sv_target=self.vars["sv_target"].get().strip(),
                    interface_maps=tuple(x.strip() for x in self.vars["interface_maps"].get().split(";") if x.strip()),
                    force_unknown=self.vars["force_unknown"].get(), debug=self.vars["debug"].get())
        task.validate()
        return task

    def browse(self, key):
        if self.busy:
            return
        def choose(path):
            if key == "out":
                join = posixpath.join if self.vars["mode"].get() == "ssh" else os.path.join
                path = join(path, "snapshot_" + time.strftime("%Y%m%d_%H%M%S"))
            self.vars[key].set(path)
        if self.vars["mode"].get() == "ssh":
            try:
                settings = self.ssh_settings()
                current = self.vars[key].get().strip()
                directory = posixpath.dirname(current) if current else settings.directory
                RemoteBrowser(self.root, settings, directory or "/", key == "fsdb", choose)
            except (ValueError, OSError) as exc:
                messagebox.showerror("SSH 设置", str(exc), parent=self.root)
        else:
            if key == "fsdb":
                path = filedialog.askopenfilename(parent=self.root, title="选择 FSDB", filetypes=(("FSDB", "*.fsdb"), ("所有文件", "*")))
            else:
                path = filedialog.askdirectory(parent=self.root, title="选择输出父目录" if key == "out" else "选择 KDB / simv.daidir")
            if path:
                choose(path)

    def new_output(self):
        name = "snapshot_" + time.strftime("%Y%m%d_%H%M%S")
        if self.vars["mode"].get() == "ssh":
            base = self.vars["directory"].get().strip()
            if not base.startswith("/"):
                messagebox.showerror("输出目录", "请先填写远端工具目录，或直接输入远端输出绝对路径。", parent=self.root)
                return
            self.vars["out"].set(posixpath.join(base, "out", name))
        else:
            self.vars["out"].set(str(output_root() / name))

    def set_busy(self, busy):
        self.busy = busy
        for widget in self.controls:
            state = "disabled" if busy else ("readonly" if isinstance(widget, ttk.Combobox) else "normal")
            widget.configure(state=state)
        self.mode_changed()
        self.run_button.configure(state="disabled" if busy else "normal")
        self.cancel_button.configure(state="normal" if busy else "disabled")
        if busy:
            self.progress.start(12)
        else:
            self.progress.stop()

    def start_job(self, function, label):
        if self.busy:
            return
        self.stop = threading.Event()
        self.set_busy(True)
        self.status.set(label)
        def worker():
            try:
                value = function(lambda kind, data: self.events.put((kind, data)))
                self.events.put(("finished", value))
            except Exception as exc:
                self.events.put(("failed", str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def start(self):
        if self.busy:
            return
        try:
            task = self.make_task()
            settings = self.ssh_settings() if task.mode == "ssh" else None
        except (ValueError, OSError) as exc:
            messagebox.showerror("请检查提取设置", str(exc), parent=self.root)
            return
        self.run_result = None
        self.set_text(self.log, "")
        self.clear_result()
        self.tabs.select(self.logs_tab)
        def extract(emit):
            if task.mode == "ssh":
                return run_ssh(task, settings, self.stop, emit)
            return run_local(task, self.stop, emit)
        self.start_job(extract, "正在提取 {} @ {}…".format(task.scope, task.when))

    def test_ssh(self):
        try:
            settings = self.ssh_settings()
        except ValueError as exc:
            messagebox.showerror("SSH 设置", str(exc), parent=self.root)
            return
        self.tabs.select(self.logs_tab)
        def test(emit):
            text = test_connection(settings)
            emit("log", text)
            return {"connection": True}
        self.start_job(test, "正在测试 SSH 连接…")

    def cancel(self):
        if self.busy:
            self.stop.set()
            self.cancel_button.configure(state="disabled")
            self.status.set("正在取消，请等待子进程退出…")

    def poll(self):
        try:
            # Bound work per tick so a noisy process cannot starve the UI.
            for _ in range(100):
                kind, data = self.events.get_nowait()
                if kind == "log":
                    self.append_log(data)
                elif kind == "failed":
                    self.set_busy(False)
                    self.status.set("运行失败 · 请查看日志")
                    self.append_log("\n错误：" + data + "\n")
                    self.set_text(self.diagnostics, data)
                    self.tabs.select(self.logs_tab)
                    self.run_result = {"code": 1, "error": data}
                elif kind == "finished":
                    self.set_busy(False)
                    if data.get("connection"):
                        self.status.set("SSH 连接与远端 Python 检查通过")
                    elif data.get("loaded"):
                        self.install_report(data["report"], Path(data["directory"]))
                        self.status.set("已打开快照 · 未执行提取")
                    else:
                        self.run_result = data
                        if data.get("directory"):
                            self.result_directory = Path(data["directory"])
                            self.folder_button.configure(state="normal")
                        if data.get("report") is not None:
                            self.install_report(data["report"], self.result_directory)
                        if data["code"] == 0:
                            self.status.set("完成 · JSON / CSV / assign SV 已生成")
                        elif data["code"] == 2:
                            self.status.set("部分完成 · 报告已保存，请查看诊断")
                        elif data["code"] == 130:
                            self.status.set("已取消 · 已保留生成的日志")
                        else:
                            self.status.set("提取失败 · 请查看日志")
                        if data.get("remote_directory"):
                            self.append_log("虚拟机结果目录：" + data["remote_directory"] + "\n")
                        if data.get("gui_log"):
                            self.append_log("GUI / SSH 日志：" + data["gui_log"] + "\n")
                        if data.get("error"):
                            self.append_log(data["error"] + "\n")
                            self.set_text(self.diagnostics, data["error"])
        except queue.Empty:
            pass
        if self.closing and not self.busy:
            self.destroy()
            return
        self.poll_id = self.root.after(80, self.poll)

    def clear_result(self):
        self.report, self.result_directory = None, None
        self.tree.delete(*self.tree.get_children())
        self.result_summary.set("等待本次提取结果…")
        self.visible_count.set("")
        self.folder_button.configure(state="disabled")
        for widget in (self.detail, self.preview, self.diagnostics):
            self.set_text(widget, "")
        self.preview_text = ""

    def install_report(self, report, directory):
        self.report, self.result_directory = report, Path(directory)
        self.folder_button.configure(state="normal")
        ok = sum(row["status"] == "ok" for row in report["signals"])
        unknown = sum(row["direction"] in ("unknown", "ref") for row in report["signals"])
        self.result_summary.set("{}  @ {}  |  {}/{} 个值读取成功  |  {} 个未知/ref\n{}".format(
            report["scope"], report.get("requested_time", ""), ok, len(report["signals"]), unknown, directory))
        messages = list(report.get("diagnostics", []))
        messages += report.get("sv", {}).get("diagnostics", [])
        messages += report.get("sv", {}).get("skipped", [])
        messages += ["{}: {} {}".format(r["logical_path"], r["status"], r.get("detail", ""))
                     for r in report["signals"] if r["status"] != "ok"]
        if report.get("log_files"):
            messages += ["诊断日志目录：" + str(directory), "run_id: " + report.get("run_id", ""),
                         "排查时请提供：" + ", ".join(report["log_files"]) + "（SSH 模式另含 gui.log）。"]
        self.set_text(self.diagnostics, "\n".join(messages) if messages else "没有发现不完整项。SV 的编译验证需要使用该设计原始 RTL / package / filelist。")
        self.filter_signals()
        self.show_preview()
        self.tabs.select(self.signals_tab)

    def schedule_filter(self, *args):
        if self.filter_after:
            self.root.after_cancel(self.filter_after)
        self.filter_after = self.root.after(180, self.filter_signals)

    def filter_signals(self):
        self.filter_after = None
        self.tree.delete(*self.tree.get_children())
        self.set_text(self.detail, "选择信号查看完整四态值、真实波形路径、方向依据与类型信息。")
        if self.report is None:
            return
        search = self.filter_text.get().lower().strip()
        matches = []
        for index, row in enumerate(self.report["signals"]):
            issue = row["status"] != "ok" or row["direction"] in ("unknown", "ref")
            if self.only_issues.get() and not issue:
                continue
            text = " ".join(str(row.get(k, "")) for k in ("logical_path", "direction", "modport", "status", "waveform_paths")).lower()
            if not search or search in text:
                matches.append((index, row))
        for index, row in matches[:5000]:
            value = row.get("value_bin")
            display = "—" if value is None else (value if len(value) <= 96 else value[:64]+"…"+value[-16:])
            tag = "error" if row["status"] != "ok" else ("unknown" if row["direction"] in ("unknown", "ref") else "")
            self.tree.insert("", "end", iid=str(index), values=(row["logical_path"], row["direction"],
                             row.get("modport", ""), row.get("width", ""), display, row["status"]), tags=(tag,))
        text = "匹配 {} / {} 项；选中行可查看完整值".format(len(matches), len(self.report["signals"]))
        if len(matches) > 5000:
            text += "（仅显示前 5000 项，请缩小筛选范围；文件包含全部结果）"
        self.visible_count.set(text)

    def show_detail(self, event=None):
        selected = self.tree.selection()
        if selected and self.report:
            row = self.report["signals"][int(selected[0])]
            self.set_text(self.detail, json.dumps(row, ensure_ascii=False, indent=2))

    def show_preview(self):
        if not self.result_directory:
            return
        path = self.result_directory / self.preview_file.get()
        try:
            with path.open("r", encoding="utf-8") as handle:
                text = handle.read(PREVIEW_LIMIT+1)
            if len(text) > PREVIEW_LIMIT:
                text = text[:PREVIEW_LIMIT] + "\n// 预览已截断；完整内容请打开结果目录中的文件。\n"
        except (OSError, UnicodeError) as exc:
            text = "尚无此文件：{}\n{}".format(path, exc)
        self.preview_text = text
        self.set_text(self.preview, text)

    def copy_preview(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.preview_text)
        self.status.set("已复制预览内容")

    def open_report(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(parent=self.root, title="打开 snapshot.json", filetypes=(("JSON", "*.json"),))
        if path:
            self.load_snapshot(Path(path))

    def load_snapshot(self, path):
        if self.busy:
            return
        path = Path(path)
        self.start_job(lambda emit: {"loaded": True, "report": load_report(path), "directory": str(path.parent)}, "正在打开快照…")

    def save_configuration(self):
        path = filedialog.asksaveasfilename(parent=self.root, title="保存配置（不含密码）", defaultextension=".json", filetypes=(("JSON", "*.json"),))
        if path:
            try:
                save_profile(path, {key: var.get() for key, var in self.vars.items()})
                self.status.set("配置已保存，未保存 SSH 密码")
            except OSError as exc:
                messagebox.showerror("保存配置", str(exc), parent=self.root)

    def load_configuration(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(parent=self.root, title="打开 GUI 配置", filetypes=(("JSON", "*.json"),))
        if path:
            try:
                for key, value in read_profile(path).items():
                    self.vars[key].set(value)
                self.vars["password"].set("")
                self.mode_changed()
                self.status.set("已载入配置；如需密码，请在 SSH / 高级中填写")
            except (ValueError, OSError) as exc:
                messagebox.showerror("打开配置", str(exc), parent=self.root)

    def open_local_path(self, path):
        try:
            open_path(path)
        except OSError as exc:
            messagebox.showerror("打开文件", str(exc), parent=self.root)

    def open_result(self):
        if self.result_directory:
            self.open_local_path(self.result_directory)

    def close(self):
        if self.busy:
            self.closing = True
            self.cancel()
            self.status.set("正在取消当前操作，结束后关闭窗口…")
        else:
            self.destroy()

    def destroy(self):
        self.root.after_cancel(self.poll_id)
        if self.filter_after:
            self.root.after_cancel(self.filter_after)
        self.vars["password"].set("")
        self.root.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Python 3.8+ Tkinter GUI for wave_init")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--report", help="open an existing local snapshot.json without running extraction")
    args = parser.parse_args(argv)
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print("无法创建 Tk 窗口：{}。请在桌面会话或可用 DISPLAY 下启动。".format(exc), file=sys.stderr)
        return 1
    app = WaveInitApp(root)
    if args.report:
        root.after(0, lambda: app.load_snapshot(Path(args.report)))
    root.mainloop()
    return 0
