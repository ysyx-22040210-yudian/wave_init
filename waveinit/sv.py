"""Generate force/release tasks and a standalone testbench with constant assigns."""
import re


def ident(name):
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", name):
        return name
    if name.startswith("\\"):
        return name.rstrip() + " "
    if any(c.isspace() for c in name):
        raise ValueError("identifier contains unsupported whitespace: " + repr(name))
    return "\\" + name + " "


def hierarchy(path):
    """Preserve already escaped names and add the required terminator space."""
    if any(c in path for c in "\n\r\x00"):
        raise ValueError("invalid hierarchy")
    parts, token, escaped = [], "", False
    for c in path:
        if escaped:
            token += c
            if c.isspace():
                escaped = False
        elif c == "\\":
            escaped = True
            token += c
        elif c == ".":
            parts.append(token)
            token = ""
        else:
            token += c
    parts.append(token)
    result = []
    for p in parts:
        if p.startswith("\\"):
            result.append(p.rstrip() + " ")
        elif re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*(?:\[-?\d+(?::-?\d+)?\])*", p):
            result.append(p)
        else:
            result.append(ident(p))
    return ".".join(result)


def dimensions(ranges):
    return "".join("[{}:{}]".format(*r) for r in ranges)


def declaration(shape, name, net=True):
    if not shape or shape["width"] < 1:
        raise ValueError("data type unavailable for " + name)
    if shape["unpacked_struct"]:
        if not shape["typedef"]:
            raise ValueError("unpacked struct requires an accessible package typedef: " + name)
        data_type = shape["typedef"]
        prefix = ""  # unpacked structs are variables, with exact nominal type
    else:
        if shape["type"] in ("npiRealTypespec", "npiShortRealTypespec", "npiStringTypespec"):
            raise ValueError("non-integral SV connection unsupported: " + name)
        rs = shape["packed_ranges"]
        product = 1
        for left, right in rs:
            product *= abs(left-right)+1
        # Packed structs/integers can be connected bit-for-bit. Preserve ordinary
        # vector dimensions where they account for the entire packed width.
        if not rs or product != shape["width"]:
            rs = [[shape["width"]-1, 0]] if shape["width"] > 1 else []
        data_type = ("signed " if shape["signed"] else "") + dimensions(rs)
        prefix = "wire " if net else "logic "
    return "{}{} {}{};".format(prefix, data_type, ident(name), dimensions(shape["unpacked_ranges"])).strip()


def targets(expr, value):
    kind = expr["kind"]
    if kind == "signal":
        return [(expr["path"], value)]
    if kind == "constant":
        if expr["value"] != value:
            raise ValueError("constant expression mismatch")
        return []
    if kind == "concat":
        result, offset = [], 0
        for sub in expr["operands"]:
            end = offset + sub["width"]
            result += targets(sub, value[offset:end])
            offset = end
        return result
    if kind == "select":
        path = target_path(expr)
        return [(path, value)]
    raise ValueError("not an assignable expression")


def target_path(expr):
    if expr["kind"] == "signal":
        return expr["path"]
    if expr["kind"] == "select":
        return target_path(expr["parent"]) + expr["suffix"]
    raise ValueError("selection of a non-lvalue expression cannot be driven")


def replace_prefix(path, prefix, replacement):
    if path == prefix or path.startswith(prefix + ".") or path.startswith(prefix + "["):
        return replacement + path[len(prefix):]
    return None


def map_path(path, mappings):
    for source, dest in sorted(mappings.items(), key=lambda p: -len(p[0])):
        mapped = replace_prefix(path, source, dest)
        if mapped is not None:
            return mapped
    raise ValueError("no SV hierarchy mapping for " + path)


def drive_list(result, force_unknown):
    drives, skipped, errors = {}, [], []
    for row in result["signals"]:
        name = row["logical_path"]
        if row["status"] != "ok":
            errors.append("{}: {} {}".format(name, row["status"], row["detail"]))
            continue
        if row["direction"] not in ("input", "inout") and not (
                force_unknown and row["direction"] == "unknown" and row["direction_source"] == "unqualified_interface"):
            skipped.append("{}: direction {}; exported without an SV driver".format(name, row["direction"]))
            continue
        try:
            for path, value in targets(row["expression"], row["value_bin"]):
                if path in drives and drives[path] != value:
                    raise ValueError("conflicting alias values for " + path)
                drives[path] = value
        except ValueError as e:
            errors.append(str(e))
    return drives, skipped, errors


def task_source(drives, skipped, errors):
    lines = ["// Generated boundary snapshot. Call apply_snapshot() explicitly.",
             "// Values are resolved FSDB values, including X/Z. Inout driver ownership is not reconstructed."]
    lines += ["// " + s.replace("\n", " ").replace("\r", " ") for s in skipped]
    lines += ["// INCOMPLETE: " + s.replace("\n", " ").replace("\r", " ") for s in errors]
    lines.append("task automatic apply_snapshot();")
    if errors:
        lines.append('  $fatal(1, "Incomplete wave_init SV snapshot; see snapshot.json diagnostics");')
    for path, value in sorted(drives.items()):
        lines.append("  force {} = {}'b{};".format(hierarchy(path), len(value), value))
    lines += ["endtask", "", "task automatic release_snapshot();"]
    for path in sorted(drives):
        lines.append("  release {};".format(hierarchy(path)))
    lines += ["endtask", "", check_source(drives)]
    return "\n".join(lines)


def check_source(drives, name="check_snapshot"):
    lines = ["task automatic {}();".format(name)]
    for index, (path, value) in enumerate(sorted(drives.items())):
        lines.append("  if ({} !== {}'b{}) $fatal(1, \"snapshot mismatch at generated item {}\");".format(
            hierarchy(path), len(value), value, index))
    lines += ["endtask", ""]
    return "\n".join(lines)


def fresh_name(preferred, used):
    candidate, index = preferred, 0
    while ident(candidate).rstrip() in used:
        index += 1
        candidate = "{}_{}".format(preferred.rstrip(), index)
    used.add(ident(candidate).rstrip())
    return ident(candidate)


def add_drive(drives, path, value):
    if path in drives and drives[path] != value:
        raise ValueError("conflicting mapped values for " + path)
    drives[path] = value


def parameter_override(parameters):
    if not parameters:
        return ""
    values = []
    for p in parameters:
        if not p["value"]:
            raise ValueError("cannot reconstruct parameter " + p["name"])
        values.append(".{}({})".format(ident(p["name"]), p["value"]))
    return " #({})".format(", ".join(values))


def standalone(result, drives, skipped, base_errors):
    errors = list(base_errors)
    used = {ident(p["name"]).rstrip() for p in result["ports"]}
    dut_name = fresh_name("dut", used)
    check_name = fresh_name("check_snapshot", used)
    lines = ["`timescale 1ns/1ps", "// Compile with the original RTL/package filelist.",
             "// Continuous assignments hold the sampled values throughout simulation.",
             "// Source: {} @ {} ({} ticks of {}).".format(
                 result["scope"], result["requested_time"], result["tick"], result["timescale"]),
             "// Internal sequential state and individual inout drivers are not reconstructed.",
             "module wave_init_tb;"]
    mappings = {result["scope"]: dut_name}
    observations = dict(mappings)
    assigned = {}
    groups, interface_groups = {}, {}
    group_labels = set()
    # Preserve multiple formal ports referring to the same actual interface.
    for interface in result["interfaces"]:
        group = interface["array_path"] or interface["path"]
        if group not in groups:
            binding = next((b for b in result["bindings"] if b["interface_path"] == interface["path"]), None)
            label = ident(binding["port"]) if binding else ""
            if not label or label in group_labels:
                label = fresh_name("wi_if_{}".format(len(groups)), used)
            group_labels.add(label)
            groups[group] = (label, interface)
        label, representative = groups[group]
        if (interface["definition"], interface["parameters"]) != (
                representative["definition"], representative["parameters"]):
            errors.append("interface array has inconsistent element parameters: " + group)
        mappings[interface["path"]] = label + interface["path"][len(group):]
        observations[interface["path"]] = mappings[interface["path"]]
        interface_groups[interface["path"]] = group

    for group, (label, interface) in groups.items():
        connections = []
        try:
            for p in interface["ports"]:
                pn = fresh_name("wi_{}_{}".format(re.sub(r"\W", "_", label),
                                                  re.sub(r"\W", "_", p["name"])), used)
                lines.append("  " + declaration(p["shape"], pn))
                connections.append(".{}({})".format(ident(p["name"]), ident(pn)))
                # Drive the constructor connection, not an already connected
                # interface input variable. Array constructors broadcast it.
                for member in result["interfaces"]:
                    if interface_groups[member["path"]] == group:
                        mappings[member["path"] + "." + p["name"]] = pn
                if p["direction"] in ("input", "inout"):
                    samples = [r for r in result["dependencies"] if
                               interface_groups.get(r["interface_path"]) == group and r["port"] == p["name"]]
                    if not samples or any(r["status"] != "ok" for r in samples):
                        raise ValueError("interface constructor input not sampled: " + group + "." + p["name"])
                    if p["shape"]["unpacked_ranges"] or len(set(r["value_bin"] for r in samples)) != 1:
                        raise ValueError("constructor array/broadcast cannot be reconstructed: " + group + "." + p["name"])
                    value = samples[0]["value_bin"]
                    add_drive(assigned, pn, value)
            lines.append("  {}{} {}{} ({});".format(
                ident(interface["definition"]), parameter_override(interface["parameters"]), label,
                dimensions(interface["array_ranges"]), ", ".join(connections)))
        except ValueError as e:
            errors.append(str(e))

    connections = []
    for port in result["ports"]:
        name = port["name"]
        try:
            if port["port_type"] in ("npiInterfacePort", "npiModportPort"):
                bindings = [b for b in result["bindings"] if b["port"] == name]
                if not bindings:
                    raise ValueError("no interface binding for " + name)
                if len(bindings) == 1:
                    connection = mappings[bindings[0]["interface_path"]]
                else:
                    source_groups = set(interface_groups[b["interface_path"]] for b in bindings)
                    if len(source_groups) != 1:
                        raise ValueError("interface formal array spans different actual arrays: " + name)
                    group = next(iter(source_groups))
                    connection, representative = groups[group]
                    ranges = (port["shape"] or {}).get("unpacked_ranges")
                    if ranges != representative["array_ranges"]:
                        raise ValueError("interface formal/actual array ranges differ: " + name)
                modports = set(b["modport"] for b in bindings)
                if port["port_type"] == "npiInterfacePort" and modports != {""}:
                    if len(modports) != 1:
                        raise ValueError("inconsistent modport on generic interface array: " + name)
                    connection += "." + ident(next(iter(modports)))
            else:
                connection = ident(name)
                lines.append("  " + declaration(port["shape"], connection, port["direction"] != "ref"))
                # Assign the testbench-side connection so input variables and
                # normal nets receive the value through the DUT port itself.
                mappings[result["scope"] + "." + name] = connection
            connections.append(".{}({})".format(ident(name), connection))
        except (ValueError, KeyError) as e:
            errors.append(str(e))
    try:
        params = parameter_override(result["parameters"])
    except ValueError as e:
        params = ""
        errors.append(str(e))
    lines += ["  {}{} {} (".format(ident(result["definition"]), params, dut_name),
              "    " + ",\n    ".join(connections), "  );", ""]
    checks, origins = {}, {}
    for path, value in drives.items():
        try:
            add_drive(assigned, map_path(path, mappings), value)
            add_drive(checks, map_path(path, observations), value)
        except ValueError as e:
            errors.append(str(e))
    for row in result["signals"]:
        if row["status"] != "ok":
            continue
        try:
            for path, value in targets(row["expression"], row["value_bin"]):
                if path in drives:
                    target = map_path(path, mappings)
                    origins.setdefault(target, []).append("{} ({})".format(row["logical_path"], row["direction"]))
        except ValueError:
            pass  # Already diagnosed by drive_list or the mapping above.
    if errors:
        # A deliberate compilable failure stub is safer than malformed wiring.
        lines = ["`timescale 1ns/1ps", "module wave_init_tb;",
                 '  initial $fatal(1, "Standalone snapshot incomplete; see snapshot.json diagnostics");',
                 "endmodule", ""]
    else:
        lines += ["  // " + s.replace("\n", " ").replace("\r", " ") for s in skipped]
        lines.append("  // Constant FSDB snapshot drivers (input/inout; output ports are not driven).")
        for path, value in sorted(assigned.items()):
            for origin in origins.get(path, []):
                lines.append("  // " + origin.replace("\n", " ").replace("\r", " "))
            lines.append("  assign {} = {}'b{};".format(hierarchy(path), len(value), value))
        lines += ["", check_source(checks, check_name), "initial begin", "  #0.001;",
                  "  {}();".format(check_name), '  $display("WAVE_INIT_SNAPSHOT_PASS");',
                  "  #0.001;", "  $finish;", "end", "endmodule", ""]
    return "\n".join(lines), errors


def generate(result, out, args):
    drives, skipped, errors = drive_list(result, args.force_unknown)
    mappings = {result["scope"]: args.sv_target or result["scope"]}
    requested = {}
    for spec in args.sv_interface_map:
        if "=" not in spec:
            raise ValueError("--sv-interface-map requires PORT=HIERARCHY")
        port, path = spec.split("=", 1)
        if not path or port in requested:
            raise ValueError("invalid or duplicate interface mapping: " + spec)
        requested[port] = path
    used = set()
    for binding in result["bindings"]:
        source = binding["interface_path"]
        if binding["port"] in requested:
            logical_base = result["scope"] + "." + binding["port"]
            target = requested[binding["port"]] + binding["logical_path"][len(logical_base):]
            used.add(binding["port"])
        elif args.sv_target:
            # The physical interface may be outside the DUT. Remapping it by a
            # string suffix would silently target the wrong instance.
            errors.append("--sv-interface-map required when relocating interface " + binding["port"])
            continue
        else:
            target = source
        if source in mappings and mappings[source] != target:
            errors.append("conflicting mappings for shared interface " + source)
        mappings[source] = target
    if set(requested) != used:
        raise ValueError("interface mapping names unknown ports: " + ", ".join(sorted(set(requested)-used)))
    original = {}
    task_errors = list(errors)
    for path, value in drives.items():
        try:
            original[map_path(path, mappings)] = value
        except ValueError as e:
            task_errors.append(str(e))
    (out / "snapshot.svh").write_text(task_source(original, skipped, task_errors), encoding="utf-8")
    tb, bench_errors = standalone(result, drives, skipped, drive_list(result, args.force_unknown)[2])
    (out / "tb_snapshot.sv").write_text(tb, encoding="utf-8")
    script = '''#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -lt 1 ]; then
  echo "Usage: bash run_vcs.sh /absolute/original-rtl.f [additional VCS options]" >&2
  exit 1
fi
rtl_filelist=$(readlink -f "$1")
shift
snapshot_dir=$(cd "$(dirname "$0")" && pwd)
run_dir=$(mktemp -d "$snapshot_dir/replay.XXXXXX")
cd "$run_dir"
vcs -full64 -sverilog -debug_access+all -f "$rtl_filelist" \\
  "$snapshot_dir/tb_snapshot.sv" -top wave_init_tb -o simv -l compile.log "$@"
./simv -l simulation.log
'''
    (out / "run_vcs.sh").write_text(script, encoding="utf-8")
    text = """wave_init snapshot

Source instance: {scope}
Source time: {requested_time} = {tick} ticks of {timescale}

snapshot.json is the complete machine-readable report, including waveform paths,
declared shapes, unresolved records, and SV diagnostics. snapshot.csv contains
the same selected signal rows; import value_bin as TEXT to preserve leading zeros.

Existing testbench: include snapshot.svh inside a module. Call apply_snapshot(),
wait for a simulation delta/time step, then check_snapshot(). Call release_snapshot()
when ready to resume the original drivers. Nothing executes just by including it.
To relocate it, rerun extraction with --sv-target and --sv-interface-map PORT=PATH.

Standalone testbench: compile tb_snapshot.sv with the original RTL and packages.
Run: bash run_vcs.sh /absolute/design.f [additional VCS options]
Use absolute paths in design.f (and its nested filelists/include paths).
The generated top is wave_init_tb. Every sampled input/inout is driven by a
module-level assign with an exact-width binary literal (including X/Z).
Ordinary connections retain the RTL port names: assign a = 8'b10100101;
Interface members use their actual shared interface instance. Constructor
inputs are assigned through the wires connected to the interface's ports.
It checks the DUT boundary after 1 ps and finishes after 2 ps. Assignments
remain active throughout simulation. Replace the relevant assign before
adding a changing clock, reset, or other later stimulus.
This checks boundary values, not restoration of internal registers/memories.
Inout values are resolved net values, not separate drivers.

Unknown-direction and ref members are reported but not driven by default.
--force-unknown explicitly includes unqualified interface members only
(force in snapshot.svh; assign in tb_snapshot.sv).
Missing values cause a failure stub or an apply task that calls $fatal;
fix the reported data/binding problem before using the SV.

Exit codes: 0 = values and SV generated completely; 2 = partial report;
1 = invalid request, vendor/runtime failure, or invalid global timestamp.
Directions may remain unknown with exit 0 when that was the requested policy.
Generation is not itself compilation verification for a new customer design.

Troubleshooting: wave_init.log records stages and failures; npi_trace.log always
records detailed interface forwarding, direction decisions and FSDB candidates.
runtime.json records this run's ID, versions, environment paths and input metadata.
verdi.log is the vendor log; npi_records.jsonl preserves raw query records.
Send these files together with snapshot.json (or error.json) and diagnostics.txt.
GUI SSH jobs also keep gui.log locally, including connection/download failures.
Use --debug, or the GUI detailed-log checkbox, to display NPI details live.
""".format(**result)
    (out / "README.txt").write_text(text, encoding="utf-8")
    diagnostics = sorted(set(task_errors + bench_errors))
    return {"complete": not diagnostics, "existing_tb_complete": not task_errors,
            "standalone_complete": not bench_errors, "diagnostics": diagnostics,
            "standalone_drive": "assign",
            "skipped": skipped, "forced_targets": len(original), "force_unknown": args.force_unknown}
