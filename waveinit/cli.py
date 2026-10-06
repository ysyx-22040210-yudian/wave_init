"""Python 3.6-compatible CLI; vendor APIs are isolated in the Tcl backend."""
import argparse
from collections import Counter
import csv
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import traceback

from . import __version__
from .sv import generate
from .portable import external_environment, resource_root
from .diagnostics import LOG_FILES, RunLog, TraceTail, console_text, file_info, runtime_info, save_runtime

FACTORS = {"fs": 1, "ps": 10**3, "ns": 10**6, "us": 10**9,
           "ms": 10**12, "s": 10**15}


class CancelledError(RuntimeError):
    pass


def check_cancelled(args):
    path = getattr(args, "cancel_file", None)
    if path and Path(path).exists():
        raise CancelledError("Extraction cancelled by the GUI; any partial reports are retained")


def parse_time(text):
    m = re.fullmatch(r"\s*(\d+(?:\.\d*)?|\.\d+)\s*(fs|ps|ns|us|ms|s|ticks?)\s*", text)
    if not m:
        raise ValueError("time must be nonnegative and include a unit, e.g. 12.5ns or 12500ticks")
    try:
        value = Fraction(Decimal(m.group(1)))
    except (ValueError, InvalidOperation):
        raise ValueError("invalid time")
    unit = m.group(2)
    if unit.startswith("tick"):
        if value.denominator != 1:
            raise ValueError("ticks must be an integer")
        return "ticks", value.numerator, 1
    value *= FACTORS[unit]
    return "physical", value.numerator, value.denominator


def paths_in_expression(expr):
    if not expr:
        return []
    kind = expr["kind"]
    if kind == "signal":
        return [expr["path"]]
    if kind == "select":
        return paths_in_expression(expr["parent"])
    if kind == "concat":
        return sorted(set(p for op in expr["operands"] for p in paths_in_expression(op)))
    return []


def read_backend(path):
    result = {"ports": [], "interfaces": [], "bindings": [], "signals": [], "dependencies": []}
    done = False
    with path.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            kind = row.pop("kind")
            if kind == "fatal":
                raise RuntimeError(row["message"] + "\n" + row.get("detail", ""))
            if kind == "metadata":
                result.update(row)
            elif kind == "port":
                result["ports"].append(row["description"])
            elif kind == "interface":
                result["interfaces"].append(row)
            elif kind == "binding":
                result["bindings"].append(row)
            elif kind == "signal":
                row["design_paths"] = paths_in_expression(row["expression"])
                if "waveform_reads" in row:
                    row["waveform_paths"] = sorted({read["waveform_path"] for read in row["waveform_reads"]
                                                    if read.get("waveform_path")})
                else:
                    row["waveform_paths"] = list(row["design_paths"])
                row["width"] = row["expression"]["width"] if row["expression"] else None
                key = "dependencies" if row["direction_source"] == "interface_constructor" else "signals"
                result[key].append(row)
            elif kind == "done":
                done = True
                if row["count"] != len(result["signals"]) + len(result["dependencies"]):
                    raise RuntimeError("backend record count mismatch")
    if not done or "scope" not in result:
        raise RuntimeError("Verdi did not finish the NPI query; inspect verdi.log")
    keys = [r["logical_path"] for r in result["signals"]]
    if len(set(keys)) != len(keys):
        raise RuntimeError("duplicate logical signal paths from NPI")
    result["signals"].sort(key=lambda r: r["logical_path"])
    result["values_complete"] = all(r["status"] == "ok" for r in result["signals"])
    result["directions_complete"] = all(r["direction"] != "unknown" for r in result["signals"])
    result["declared_directions_complete"] = all(
        r["direction"] != "unknown" or r["direction_source"] == "unqualified_interface"
        for r in result["signals"])
    result["diagnostics"] = []
    if any(r["direction"] == "unknown" and r["direction_source"] == "modport" for r in result["signals"]):
        result["diagnostics"].append(
            "存在已声明 modport 但仍未解析的成员方向，结果标为不完整。请查看 npi_trace.log 中的 "
            "modport.declaration、modport.member 和 interface.unresolved；不能把这些成员当作 input 驱动。")
    if int(result.get("tick", 0)) < int(result.get("min_tick", 0)):
        result["diagnostics"].append(
            "采样时间早于 FSDB 报告的起始时间（{} ticks）。查询已接受并逐信号读取；没有更早记录的信号显示 "
            "no_initial_value 和空值，不使用后续时刻的值。".format(result["min_tick"]))
    if any(r["direction_source"] == "unresolved_binding" for r in result["signals"]):
        result["diagnostics"].append(
            "KDB 未能提供完整的 interface/modport 绑定信息。分文件编译时，interface、DUT 和 TB 的 "
            "vlogan 分析阶段都需使用 -sverilog -kdb，随后用 vcs -kdb 重新 elaboration。"
            "仅在最后 vcs 命令添加 -kdb，无法补回此前未生成的 interface 数据。")
    missing_interfaces = sorted({r["interface_path"] for r in result["signals"] + result["dependencies"]
                                 if r["interface_path"] and r["status"] == "not_dumped"})
    for instance in missing_interfaces:
        result["diagnostics"].append(
            "在当前 FSDB 中未找到 interface {} 的部分值；已检查 KDB 证明的实际实例、形式端口和 modport 路径。"
            "请核对 FSDB/KDB 是否匹配；必要时在原仿真中加入 $fsdbDumpvars(0, {}, \"+all\"); 并重新生成 FSDB。"
            "已有 FSDB 中不存在的值不能恢复。".format(instance, instance))
    return result


def run_backend(args, out, mode, num, den, log, runtime):
    check_cancelled(args)
    kdb = Path(args.kdb).resolve()
    if (kdb / "kdb.elab++").is_dir():
        kdb = kdb / "kdb.elab++"
    if not kdb.is_dir() or not any(kdb.iterdir()):
        raise ValueError("--kdb must be a nonempty kdb.elab++ directory (or its simv.daidir parent)")
    fsdb = Path(args.fsdb).resolve()
    if not fsdb.is_file():
        raise ValueError("FSDB file does not exist: {}".format(fsdb))
    verdi = args.verdi or shutil.which("verdi")
    if not verdi and os.environ.get("VERDI_HOME"):
        verdi = str(Path(os.environ["VERDI_HOME"]) / "bin" / "verdi")
    if not verdi:
        raise ValueError("Verdi not found; set VERDI_HOME, PATH, or --verdi")
    # Verdi dispatches by argv[0]; resolving its .wrapper symlink breaks launch.
    verdi = os.path.abspath(verdi)
    backend = resource_root() / "backend" / "snapshot.tcl"
    runtime.update(verdi_executable=verdi, resolved_kdb=str(kdb), resolved_fsdb=str(fsdb),
                   resolved_inputs={"fsdb": file_info(fsdb), "kdb": file_info(kdb)},
                   time_conversion={"mode": mode, "numerator": num, "denominator": den}, stage="launch_verdi")
    save_runtime(out, runtime)
    log.event("INFO", "inputs.resolved", fsdb=str(fsdb), fsdb_bytes=fsdb.stat().st_size, kdb=str(kdb))
    run_dir = Path(tempfile.mkdtemp(prefix="npi_", dir=str(out)))
    raw = run_dir / "records.jsonl"
    env = external_environment()
    env.update(WI_FSDB=str(fsdb), WI_KDB=str(kdb), WI_SCOPE=args.scope,
               WI_TIME_MODE=mode, WI_TIME_NUM=str(num), WI_TIME_DEN=str(den), WI_RESULT=str(raw),
               WI_TRACE=str(out / "npi_trace.log"), WI_RUN_ID=runtime["run_id"])
    start = time.monotonic()
    argv = [verdi, "-batch", "-nologo", "-play", str(backend)]
    log.event("INFO", "verdi.launch", argv=argv, cwd=str(run_dir), scope=args.scope,
              requested_time=args.time, timeout_seconds=args.timeout, raw_records=str(raw))
    tail = TraceTail(out / "npi_trace.log", log)
    heartbeat = start
    with (out / "verdi.log").open("w", encoding="utf-8") as vendor_log:
        proc = subprocess.Popen(argv,
                                cwd=str(run_dir), env=env, stdout=vendor_log, stderr=subprocess.STDOUT,
                                start_new_session=True)
        log.event("INFO", "verdi.started", pid=proc.pid)
        try:
            while True:
                tail.poll()
                check_cancelled(args)
                if time.monotonic() - heartbeat >= 10:
                    heartbeat = time.monotonic()
                    log.event("INFO", "verdi.running", pid=proc.pid, elapsed_seconds=round(heartbeat-start, 1))
                remaining = args.timeout - (time.monotonic() - start)
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(proc.args, args.timeout)
                try:
                    rc = proc.wait(timeout=min(0.2, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
        except (subprocess.TimeoutExpired, KeyboardInterrupt, CancelledError) as exc:
            log.event("WARNING", "verdi.terminate", pid=proc.pid, reason=type(exc).__name__)
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
            if isinstance(exc, CancelledError):
                raise
            raise RuntimeError("Verdi query cancelled or exceeded {} seconds; inspect verdi.log".format(args.timeout))
        finally:
            tail.poll(final=True)
            if raw.is_file():
                shutil.copyfile(str(raw), str(out / "npi_records.jsonl"))
            log.event("INFO", "verdi.exited", pid=proc.pid, exit_code=proc.returncode,
                      elapsed_seconds=round(time.monotonic()-start, 3))
            vendor_log.flush()
            with (out / "verdi.log").open(encoding="utf-8", errors="replace") as stream:
                release = re.search(r"Release\s+([^\r\n]+)", stream.read(65536))
            if release:
                runtime["verdi_release"] = release.group(1)
                log.event("INFO", "verdi.version", release=runtime["verdi_release"])
    runtime.update(stage="read_records", verdi_exit_code=rc, raw_records=str(raw))
    save_runtime(out, runtime)
    check_cancelled(args)
    if not raw.is_file():
        raise RuntimeError("Verdi produced no NPI results (exit {}); inspect verdi.log".format(rc))
    result = read_backend(raw)
    log.event("INFO", "records.loaded", ports=len(result["ports"]), interfaces=len(result["interfaces"]),
              bindings=len(result["bindings"]), signals=len(result["signals"]),
              dependencies=len(result["dependencies"]), statuses=dict(Counter(r["status"] for r in result["signals"])))
    if rc != 0:
        raise RuntimeError("Verdi exited with status {}; inspect verdi.log".format(rc))
    result.update(schema_version=1, tool_version=__version__, fsdb=str(fsdb), kdb=str(kdb),
                  requested_time=args.time, elapsed_seconds=round(time.monotonic()-start, 3),
                  run_id=runtime["run_id"], log_files=list(LOG_FILES))
    return result


def write_reports(result, out):
    (out / "snapshot.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fields = ["logical_path", "port", "interface_path", "modport", "direction", "direction_source",
              "waveform_paths", "design_paths", "waveform_reads", "width", "shape", "value_bin", "status", "change_tick", "detail"]
    with (out / "snapshot.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in result["signals"]:
            csv_row = dict(row)
            for name in ("shape", "waveform_paths", "design_paths", "waveform_reads"):
                csv_row[name] = json.dumps(row.get(name, []), ensure_ascii=False, separators=(",", ":"))
            writer.writerow(csv_row)
    lines = ["wave_init {}".format(result.get("tool_version", __version__)),
             "scope: " + result.get("scope", ""),
             "time: " + result.get("requested_time", ""),
             "KDB: " + result.get("kdb", ""), "FSDB: " + result.get("fsdb", ""), ""]
    lines.extend(result.get("diagnostics", []))
    if result.get("run_id"):
        lines.extend(["run_id: " + result["run_id"], "Logs: " + ", ".join(result.get("log_files", []))])
    lines.extend("SV: " + d for d in result.get("sv", {}).get("diagnostics", []))
    lines.extend(["", "Interface bindings:"])
    for binding in result.get("bindings", []):
        lines.append("{} -> {} (modport: {})".format(binding["logical_path"], binding["interface_path"], binding["modport"] or "unknown"))
        if binding.get("modport_source"):
            lines.append("  Modport selected from: " + binding["modport_source"])
    lines.extend(["", "Signal lookups (design and waveform paths can differ):"])
    for row in result["signals"]:
        lines.append("{} [{}] {}".format(row["logical_path"], row["direction"], row["status"]))
        lines.append("  KDB: " + ", ".join(row.get("design_paths", paths_in_expression(row.get("expression")))))
        lines.append("  FSDB: " + ", ".join(row.get("waveform_paths", [])))
        if row.get("detail"):
            lines.append("  " + row["detail"])
        for read in row.get("waveform_reads", []):
            lines.append("  Tried: " + ", ".join(read.get("candidates", [])))
            for attempt in read.get("attempts", []):
                lines.append("    {}: {} (first_tick={}, change_tick={}, method={})".format(
                    attempt["path"], attempt["status"], attempt.get("first_tick") or "unavailable",
                    attempt.get("change_tick") or "unavailable", attempt.get("read_method") or "unavailable"))
                if attempt.get("detail"):
                    lines.append("      " + attempt["detail"])
    (out/"diagnostics.txt").write_text("\n".join(lines)+"\n", encoding="utf-8")


def parser():
    p = argparse.ArgumentParser(description="Snapshot RTL input/inout ports and interface members through Verdi NPI.")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--fsdb", required=True)
    p.add_argument("--kdb", required=True)
    p.add_argument("--scope", required=True, help="exact elaborated module instance path")
    p.add_argument("--time", required=True, help="physical time with unit, or integer ticks")
    p.add_argument("--out", required=True, help="new output directory; use a different directory for each run")
    p.add_argument("--verdi", help="Verdi executable (defaults to PATH or VERDI_HOME)")
    p.add_argument("--timeout", type=float, default=300, help="maximum Verdi query time in seconds")
    p.add_argument("--debug", action="store_true",
                   help="also print detailed NPI binding/FSDB lookup events live; detailed npi_trace.log is always saved")
    p.add_argument("--sv-target", help="replacement DUT hierarchy for snapshot.svh")
    p.add_argument("--sv-interface-map", action="append", default=[], metavar="PORT=HIERARCHY",
                   help="replacement interface instance for snapshot.svh; repeat as needed")
    p.add_argument("--force-unknown", action="store_true",
                   help="also drive unqualified-interface members marked unknown (force in SVH, assign in standalone SV)")
    p.add_argument("--cancel-file", help=argparse.SUPPRESS)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    out = Path(args.out).resolve()
    owns_output = False
    log, runtime = None, None
    try:
        if out.exists() and any(out.iterdir()):
            raise ValueError("output directory is not empty: {}; choose a new directory".format(out))
        out.mkdir(parents=True, exist_ok=True)
        owns_output = True
        log = RunLog(out / "wave_init.log", debug=args.debug)
        runtime = runtime_info(args, out)
        save_runtime(out, runtime)
        log.event("INFO", "run.start", run_id=runtime["run_id"], tool_version=__version__,
                  python=runtime["python"], frozen=runtime["frozen"], platform=runtime["platform"])
        log.event("INFO", "run.request", **runtime["request"])
        log.event("INFO", "logs.saved", directory=str(out), files=list(LOG_FILES))
        mode, num, den = parse_time(args.time)
        if not math.isfinite(args.timeout) or args.timeout <= 0:
            raise ValueError("--timeout must be positive")
        result = run_backend(args, out, mode, num, den, log, runtime)
        check_cancelled(args)
        runtime["stage"] = "generate_sv"
        save_runtime(out, runtime)
        log.event("INFO", "sv.generate", drive="assign", signals=len(result["signals"]))
        result["sv"] = generate(result, out, args)
        result["complete"] = result["values_complete"] and result["sv"]["complete"] and result["declared_directions_complete"]
        write_reports(result, out)
        ok = sum(r["status"] == "ok" for r in result["signals"])
        console_text("{} @ {} ({} ticks, {}): {}/{} values read\n".format(
            result["scope"], args.time, result["tick"], result["timescale"], ok, len(result["signals"])))
        for r in result["signals"]:
            val = r["value_bin"] if r["status"] == "ok" else "<{}>".format(r["status"])
            if len(val) > 72:
                val = val[:32] + "..." + val[-24:]
            console_text("  {:7} {:48} {}\n".format(r["direction"], r["logical_path"], val))
        for problem in result.get("diagnostics", []):
            log.event("WARNING", "snapshot.diagnostic", detail=problem)
        for problem in result["sv"]["diagnostics"]:
            log.event("WARNING", "sv.diagnostic", detail=problem)
        console_text("Reports: {}\n".format(out))
        code = 0 if result["complete"] else 2
        runtime.update(stage="finished", exit_code=code, complete=result["complete"],
                       signal_statuses=dict(Counter(r["status"] for r in result["signals"])))
        save_runtime(out, runtime)
        log.event("INFO" if code == 0 else "WARNING", "run.finished", exit_code=code,
                  values_read=ok, signals=len(result["signals"]), sv_complete=result["sv"]["complete"])
        return code
    except Exception as exc:
        console_text("wave_init: {}\n".format(exc), stream=sys.stderr)
        code = 130 if isinstance(exc, CancelledError) else 1
        if log:
            log.event("ERROR", "run.failed", stage=(runtime or {}).get("stage"),
                      exit_code=code, error_type=type(exc).__name__, detail=str(exc), stack=traceback.format_exc())
        if runtime:
            runtime.update(exit_code=code, error=str(exc))
            save_runtime(out, runtime)
        if owns_output and not (out / "snapshot.json").exists():
            status = "cancelled" if isinstance(exc, CancelledError) else "fatal"
            (out / "error.json").write_text(json.dumps({"status": status, "message": str(exc)}, indent=2)+"\n", encoding="utf-8")
        return code
    finally:
        if log:
            log.close()
