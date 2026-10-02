"""Python 3.6-compatible CLI; vendor APIs are isolated in the Tcl backend."""
import argparse
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

from . import __version__
from .sv import generate
from .portable import external_environment, resource_root

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
                row["waveform_paths"] = paths_in_expression(row["expression"])
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
    return result


def run_backend(args, out, mode, num, den):
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
    run_dir = Path(tempfile.mkdtemp(prefix="npi_", dir=str(out)))
    raw = run_dir / "records.jsonl"
    env = external_environment()
    env.update(WI_FSDB=str(fsdb), WI_KDB=str(kdb), WI_SCOPE=args.scope,
               WI_TIME_MODE=mode, WI_TIME_NUM=str(num), WI_TIME_DEN=str(den), WI_RESULT=str(raw))
    start = time.monotonic()
    print("Reading {} at {} through Verdi NPI...".format(args.scope, args.time), flush=True)
    with (out / "verdi.log").open("w", encoding="utf-8") as log:
        proc = subprocess.Popen([verdi, "-batch", "-nologo", "-play", str(backend)],
                                cwd=str(run_dir), env=env, stdout=log, stderr=subprocess.STDOUT,
                                start_new_session=True)
        try:
            while True:
                check_cancelled(args)
                remaining = args.timeout - (time.monotonic() - start)
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(proc.args, args.timeout)
                try:
                    rc = proc.wait(timeout=min(0.2, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
        except (subprocess.TimeoutExpired, KeyboardInterrupt, CancelledError) as exc:
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
    check_cancelled(args)
    if not raw.is_file():
        raise RuntimeError("Verdi produced no NPI results (exit {}); inspect verdi.log".format(rc))
    result = read_backend(raw)
    if rc != 0:
        raise RuntimeError("Verdi exited with status {}; inspect verdi.log".format(rc))
    result.update(schema_version=1, tool_version=__version__, fsdb=str(fsdb), kdb=str(kdb),
                  requested_time=args.time, elapsed_seconds=round(time.monotonic()-start, 3))
    return result


def write_reports(result, out):
    (out / "snapshot.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fields = ["logical_path", "port", "interface_path", "modport", "direction", "direction_source",
              "waveform_paths", "width", "shape", "value_bin", "status", "change_tick", "detail"]
    with (out / "snapshot.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in result["signals"]:
            csv_row = dict(row)
            for name in ("shape", "waveform_paths"):
                csv_row[name] = json.dumps(row[name], ensure_ascii=False, separators=(",", ":"))
            writer.writerow(csv_row)


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
    try:
        mode, num, den = parse_time(args.time)
        if not math.isfinite(args.timeout) or args.timeout <= 0:
            raise ValueError("--timeout must be positive")
        if out.exists() and any(out.iterdir()):
            raise ValueError("output directory is not empty: {}; choose a new directory".format(out))
        out.mkdir(parents=True, exist_ok=True)
        owns_output = True
        result = run_backend(args, out, mode, num, den)
        check_cancelled(args)
        result["sv"] = generate(result, out, args)
        result["complete"] = result["values_complete"] and result["sv"]["complete"]
        write_reports(result, out)
        ok = sum(r["status"] == "ok" for r in result["signals"])
        print("{} @ {} ({} ticks, {}): {}/{} values read".format(
            result["scope"], args.time, result["tick"], result["timescale"], ok, len(result["signals"])))
        for r in result["signals"]:
            val = r["value_bin"] if r["status"] == "ok" else "<{}>".format(r["status"])
            if len(val) > 72:
                val = val[:32] + "..." + val[-24:]
            print("  {:7} {:48} {}".format(r["direction"], r["logical_path"], val))
        for problem in result["sv"]["diagnostics"]:
            print("SV: " + problem, file=sys.stderr)
        print("Reports: {}".format(out))
        return 0 if result["complete"] else 2
    except (ValueError, RuntimeError, OSError) as exc:
        print("wave_init: {}".format(exc), file=sys.stderr)
        if owns_output and not (out / "snapshot.json").exists():
            status = "cancelled" if isinstance(exc, CancelledError) else "fatal"
            (out / "error.json").write_text(json.dumps({"status": status, "message": str(exc)}, indent=2)+"\n", encoding="utf-8")
        return 130 if isinstance(exc, CancelledError) else 1
