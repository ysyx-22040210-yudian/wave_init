"""Persistent run evidence, without dumping credentials or the whole environment."""
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import threading
import time
import uuid

from . import __version__
from .portable import external_environment, resource_root


LOG_FILES = ("wave_init.log", "npi_trace.log", "npi_records.jsonl", "runtime.json", "verdi.log", "diagnostics.txt")


def timestamp():
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + ".{:03d}Z".format(int(time.time() * 1000) % 1000)


def console_text(text, stream=None):
    stream = stream or sys.stdout
    try:
        stream.write(text)
    except UnicodeEncodeError:
        # Old Python on LANG=C uses ASCII even when the terminal/pipe accepts
        # UTF-8. The persistent files always use UTF-8 as well.
        stream.flush()
        if hasattr(stream, "buffer"):
            stream.buffer.write(text.encode("utf-8", "replace"))
            stream.buffer.flush()
        else:
            encoding = getattr(stream, "encoding", None) or "ascii"
            stream.write(text.encode(encoding, "backslashreplace").decode(encoding))
    stream.flush()


class RunLog:
    """Flush each record so crashes/cancellation leave useful progress behind."""
    def __init__(self, path, debug=False, console=None):
        self.path = Path(path)
        self.debug = debug
        self.console = console or console_text
        self.stream = self.path.open("w", encoding="utf-8")
        self.started = time.monotonic()
        self.lock = threading.Lock()

    def event(self, level, event, **fields):
        line = "{} +{:.3f}s [{}] {} {}\n".format(
            timestamp(), time.monotonic() - self.started, level, event,
            json.dumps(fields, ensure_ascii=False, separators=(",", ":")))
        with self.lock:
            self.stream.write(line)
            self.stream.flush()
            if level != "DEBUG" or self.debug:
                self.console(line)

    def chunk(self, text):
        # Preserve subprocess text exactly, including split UTF-8/partial lines.
        with self.lock:
            self.stream.write(text)
            self.stream.flush()
            self.console(text)

    def close(self):
        self.stream.close()


def file_info(path):
    path = Path(path)
    info = {"path": str(path)}
    try:
        stat = path.stat()
        info.update(exists=True, size_bytes=stat.st_size, modified_ns=int(stat.st_mtime * 10**9),
                    kind="directory" if path.is_dir() else "file")
    except OSError as exc:
        info.update(exists=False, error=str(exc))
    return info


def runtime_info(args, out):
    root = resource_root()
    env = external_environment()
    # Paths aid EDA setup diagnosis; license/server values and SSH secrets do not.
    paths = ("VERDI_HOME", "VCS_HOME", "PATH", "LD_LIBRARY_PATH", "TCL_LIBRARY", "TK_LIBRARY")
    hashes = {}
    for name in ("backend/snapshot.tcl", "waveinit/cli.py", "waveinit/diagnostics.py"):
        path = root / name
        if path.is_file():
            hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "run_id": uuid.uuid4().hex, "started_utc": timestamp(), "tool_version": __version__,
        "python": sys.version, "executable": sys.executable,
        "frozen": bool(getattr(sys, "frozen", False)), "platform": platform.platform(),
        "machine": platform.machine(), "hostname": platform.node(), "libc": list(platform.libc_ver()),
        "cwd": os.getcwd(), "resource_root": str(root), "source_sha256": hashes,
        "environment_paths": {name: env.get(name, "") for name in paths},
        "license_configured": {name: bool(env.get(name)) for name in ("SNPSLMD_LICENSE_FILE", "LM_LICENSE_FILE")},
        "request": {"fsdb": args.fsdb, "kdb": args.kdb, "scope": args.scope, "time": args.time,
                    "out": str(out), "timeout_seconds": args.timeout, "verdi": args.verdi,
                    "debug_console": getattr(args, "debug", False), "sv_target": args.sv_target,
                    "interface_maps": args.sv_interface_map, "force_unknown": args.force_unknown},
        "inputs": {"fsdb": file_info(Path(args.fsdb).resolve()), "kdb": file_info(Path(args.kdb).resolve())},
        "logs": list(LOG_FILES), "stage": "initializing"
    }


def save_runtime(out, runtime):
    (Path(out) / "runtime.json").write_text(json.dumps(runtime, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class TraceTail:
    """Stream complete JSONL backend events; tolerate an interrupted final line."""
    def __init__(self, path, log):
        self.path, self.log = Path(path), log
        self.position, self.pending = 0, b""

    def poll(self, final=False):
        if not self.path.is_file():
            return
        with self.path.open("rb") as stream:
            stream.seek(self.position)
            data = stream.read()
            self.position = stream.tell()
        lines = (self.pending + data).split(b"\n")
        self.pending = lines.pop()
        for line in lines:
            if not line:
                continue
            try:
                row = json.loads(line.decode("utf-8"))
                level, event = row.pop("level"), row.pop("event")
                if level != "DEBUG" or self.log.debug:
                    self.log.event(level, "npi." + event, **row)
            except (ValueError, KeyError, UnicodeError) as exc:
                self.log.event("WARNING", "npi.trace_decode_error", detail=str(exc))
        if final and self.pending:
            self.log.event("WARNING", "npi.trace_interrupted", bytes=len(self.pending))
            self.pending = b""
