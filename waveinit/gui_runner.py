"""Python 3.8 GUI jobs. No Tk calls: all notifications go through an event queue."""
import codecs
import getpass
from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import posixpath
import shlex
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid

from .cli import parse_time
from .portable import cli_command, download_root, resource_root

ROOT = resource_root()
ARTIFACTS = ("snapshot.json", "snapshot.csv", "tb_snapshot.sv", "snapshot.svh",
             "README.txt", "run_vcs.sh", "error.json", "verdi.log", "diagnostics.txt")


@dataclass
class Task:
    mode: str = "local"
    fsdb: str = ""
    kdb: str = ""
    scope: str = ""
    when: str = "7ns"
    out: str = ""
    timeout: float = 300
    verdi: str = ""
    sv_target: str = ""
    interface_maps: tuple = ()
    force_unknown: bool = False

    def validate(self):
        if self.mode not in ("local", "ssh"):
            raise ValueError("请选择本机或 SSH 执行模式。")
        for name, label in (("fsdb", "FSDB 文件"), ("kdb", "KDB 目录"),
                            ("scope", "模块实例层次"), ("out", "输出目录")):
            value = getattr(self, name)
            if not value.strip() or any(c in value for c in "\n\r\x00"):
                raise ValueError("请填写有效的{}。".format(label))
        parse_time(self.when)
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("超时必须是大于 0 的有限秒数。")
        ports = set()
        for item in self.interface_maps:
            if "=" not in item:
                raise ValueError("Interface 映射每行使用 PORT=HIERARCHY。")
            port, target = item.split("=", 1)
            if not port or not target or port in ports:
                raise ValueError("Interface 映射的端口/层次为空或端口重复。")
            ports.add(port)
        if self.mode == "ssh":
            for value in (self.fsdb, self.kdb, self.out):
                if not value.startswith("/"):
                    raise ValueError("SSH 模式使用远端服务器上的绝对路径，例如 /home/user/project/...。")
        else:
            # Preserve paths entered relative to the launch directory even when
            # the worker runs from the app/resource directory.
            for name in ("fsdb", "kdb", "out"):
                setattr(self, name, str(Path(getattr(self, name)).expanduser().resolve()))
            if not Path(self.fsdb).is_file():
                raise ValueError("FSDB 文件不存在。")
            kdb = Path(self.kdb)
            if (kdb / "kdb.elab++").is_dir():
                kdb = kdb / "kdb.elab++"
            if not kdb.is_dir() or not any(kdb.iterdir()):
                raise ValueError("请选择非空 kdb.elab++ 目录或包含它的 simv.daidir。")
            output = Path(self.out)
            if output.exists() and (not output.is_dir() or any(output.iterdir())):
                raise ValueError("输出目录必须是新目录或空目录，请换一个名称。")

    def arguments(self, cancel_file):
        args = ["--fsdb", self.fsdb, "--kdb", self.kdb, "--scope", self.scope,
                "--time", self.when, "--out", self.out, "--timeout", str(self.timeout),
                "--cancel-file", cancel_file]
        if self.verdi:
            args.extend(("--verdi", self.verdi))
        if self.sv_target:
            args.extend(("--sv-target", self.sv_target))
        for item in self.interface_maps:
            args.extend(("--sv-interface-map", item))
        if self.force_unknown:
            args.append("--force-unknown")
        return args


@dataclass
class SSHSettings:
    host: str = ""
    port: int = 22
    user: str = field(default_factory=getpass.getuser)
    password: str = field(default="", repr=False)
    directory: str = ""
    python: str = "python3"
    environment: str = ""

    def validate(self):
        if not self.host.strip() or not self.user.strip() or not 1 <= self.port <= 65535:
            raise ValueError("请填写 SSH 主机、用户名和有效端口。")
        if not self.directory.startswith("/") or not self.python.strip():
            raise ValueError("远端工具目录须为绝对路径，并填写 Python 可执行文件。")
        for value in (self.host, self.user, self.directory, self.python, self.environment):
            if any(c in value for c in "\r\n\x00"):
                raise ValueError("SSH 设置不能包含换行或 NUL 字符。")


def connect_ssh(settings):
    settings.validate()
    try:
        import paramiko
    except ImportError:
        raise RuntimeError("SSH 模式需要 Paramiko。请在运行 GUI 的 Python 环境安装：python -m pip install paramiko")
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    try:
        client.connect(settings.host, port=settings.port, username=settings.user,
                       password=settings.password or None, look_for_keys=True, allow_agent=True,
                       timeout=10, banner_timeout=15, auth_timeout=15)
    except Exception as exc:
        client.close()
        raise RuntimeError("SSH 连接失败：{}。首次连接请先使用系统 ssh 校验并保存主机密钥。".format(exc))
    return client


def remote_command(settings, argv):
    lines = ["set -e", "cd -- " + shlex.quote(settings.directory)]
    if settings.environment:
        lines.append("source " + shlex.quote(settings.environment))
    lines.append("exec " + " ".join(shlex.quote(str(a)) for a in argv))
    return "bash --noprofile --norc -c " + shlex.quote("\n".join(lines))


def load_report(path):
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(report, dict) or not isinstance(report.get("scope"), str) or not isinstance(report.get("signals"), list):
        raise ValueError("该文件不是有效的 wave_init snapshot.json。")
    for row in report["signals"]:
        if not isinstance(row, dict) or not all(isinstance(row.get(k), str) for k in ("logical_path", "direction", "status")):
            raise ValueError("快照中的信号行缺少路径、方向或读取状态。")
        value = row.get("value_bin")
        if value is not None and (not isinstance(value, str) or any(c not in "01xz" for c in value)):
            raise ValueError("快照包含无效的四态二进制值。")
    return report


def collect_result(code, out, remote_out=""):
    out = Path(out)
    result = {"code": code, "directory": str(out), "remote_directory": remote_out,
              "report": None, "error": ""}
    if code in (0, 2) and (out / "snapshot.json").is_file():
        result["report"] = load_report(out / "snapshot.json")
    if (out / "error.json").is_file():
        error = json.loads((out / "error.json").read_text(encoding="utf-8"))
        result["error"] = error.get("message", "")
    if code in (0, 2) and result["report"] is None:
        raise RuntimeError("提取进程已退出，但未取得 snapshot.json；请检查日志和工具版本。")
    return result


def run_local(task, stop, emit):
    if os.name != "posix":
        raise RuntimeError("本机提取需要 Linux 和 Verdi；Windows 请选 SSH 模式。已有报告可直接打开。")
    if stop.is_set():
        return {"code": 130, "directory": "", "remote_directory": "", "report": None, "error": "已取消。"}
    with tempfile.TemporaryDirectory(prefix="wave_init_gui_") as work:
        cancel_file = Path(work) / "cancel"
        argv = cli_command(task.arguments(str(cancel_file)))
        env = os.environ.copy()
        env.update(PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        emit("log", "开始提取：{} @ {}\n".format(task.scope, task.when))
        proc = subprocess.Popen(argv, cwd=str(ROOT), env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, universal_newlines=True,
                                encoding="utf-8", errors="replace")
        def read_output():
            for line in proc.stdout:
                emit("log", line)
        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        while proc.poll() is None:
            if stop.wait(0.1) and not cancel_file.exists():
                cancel_file.touch()
                emit("log", "正在取消并等待 Verdi 子进程退出…\n")
            if stop.is_set():
                time.sleep(0.1)
        reader.join(timeout=5)
        proc.stdout.close()
        return collect_result(proc.returncode, task.out)


def run_ssh(task, settings, stop, emit, cache_root=None):
    client = connect_ssh(settings)
    cancel_file = "/tmp/wave_init_gui_{}.cancel".format(uuid.uuid4().hex)
    sftp, channel, cancel_written, exited = None, None, False, False
    try:
        if stop.is_set():
            return {"code": 130, "directory": "", "remote_directory": task.out, "report": None, "error": "已取消。"}
        sftp = client.open_sftp()
        sftp.get_channel().settimeout(15)
        # Do not download an older report when the CLI rejects a nonempty output.
        try:
            mode = sftp.stat(task.out).st_mode
        except IOError as exc:
            if getattr(exc, "errno", None) != 2:
                raise
        else:
            if not stat.S_ISDIR(mode) or sftp.listdir(task.out):
                raise ValueError("远端输出目录不是空目录；请换一个新目录。")
        argv = [settings.python, "-u", "wave_init.py"] + task.arguments(cancel_file)
        channel = client.get_transport().open_session(timeout=15)
        channel.set_combine_stderr(True)
        channel.exec_command(remote_command(settings, argv))
        emit("log", "SSH {}：{} @ {}\n远端输出：{}\n".format(settings.host, task.scope, task.when, task.out))
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        deadline, cancelled_at = time.monotonic() + task.timeout + 45, None
        while True:
            if channel.recv_ready():
                emit("log", decoder.decode(channel.recv(65536)))
            elif channel.exit_status_ready():
                break
            if not client.get_transport().is_active():
                raise RuntimeError("SSH 已断开，无法确认远端状态；远端查询仍受设置的超时限制。")
            now = time.monotonic()
            if now > deadline:
                stop.set()
            if stop.is_set() and not cancel_written:
                with sftp.open(cancel_file, "wx") as handle:
                    handle.write("cancel\n")
                cancel_written, cancelled_at = True, now
                emit("log", "正在通知远端取消并清理 Verdi 子进程…\n")
            if cancelled_at is not None and now - cancelled_at > 20:
                raise RuntimeError("远端未确认取消；请检查连接与日志，Verdi 查询仍受超时限制。")
            time.sleep(0.05)
        emit("log", decoder.decode(b"", final=True))
        code = channel.recv_exit_status()
        exited = True
        parent = Path(cache_root) if cache_root else download_root()
        parent.mkdir(parents=True, exist_ok=True)
        local = Path(tempfile.mkdtemp(prefix=time.strftime("%Y%m%d_%H%M%S_"), dir=str(parent)))
        for name in ARTIFACTS:
            remote = posixpath.join(task.out, name)
            try:
                info = sftp.stat(remote)
            except IOError as exc:
                if getattr(exc, "errno", None) == 2:
                    continue
                raise
            if stat.S_ISREG(info.st_mode):
                sftp.get(remote, str(local / name))
        emit("log", "本机报告：{}\n".format(local))
        return collect_result(code, local, task.out)
    finally:
        # Keep the cancel marker if a lost connection prevented acknowledgement.
        if cancel_written and exited and sftp is not None:
            try:
                sftp.remove(cancel_file)
            except (IOError, EOFError):
                pass
        if channel is not None:
            channel.close()
        if sftp is not None:
            sftp.close()
        client.close()


def list_remote(settings, directory, files=False):
    client = connect_ssh(settings)
    try:
        sftp = client.open_sftp()
        sftp.get_channel().settimeout(15)
        canonical = sftp.normalize(directory)
        entries = []
        for item in sftp.listdir_attr(canonical):
            is_dir = stat.S_ISDIR(item.st_mode)
            if stat.S_ISLNK(item.st_mode):
                try:
                    is_dir = stat.S_ISDIR(sftp.stat(posixpath.join(canonical, item.filename)).st_mode)
                except IOError:
                    continue
            if is_dir or (files and item.filename.lower().endswith(".fsdb")):
                entries.append((item.filename, is_dir))
        return canonical, sorted(entries, key=lambda e: (not e[1], e[0].lower()))
    finally:
        client.close()


def test_connection(settings):
    client = connect_ssh(settings)
    try:
        code = "import sys,os; print('Python: '+sys.version); print('Tool: '+os.path.abspath('wave_init.py')); assert os.path.isfile('wave_init.py'), 'wave_init.py is missing'"
        _, stdout, _ = client.exec_command(remote_command(settings, [settings.python, "-c", code]), timeout=20)
        stdout.channel.set_combine_stderr(True)
        text = stdout.read().decode("utf-8", "replace")
        if stdout.channel.recv_exit_status() != 0:
            raise RuntimeError(text)
        return text
    finally:
        client.close()
