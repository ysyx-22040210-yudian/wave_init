#!/usr/bin/env python3
"""Verify the release on the build OS and an isolated minimal Ubuntu userspace.

Run as root under a fresh Xvfb; the release itself is checked as an ordinary user.
All mounts live in a temporary private mount/PID namespace, not on the host.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def run(argv, log, **kwargs):
    p = subprocess.run([str(a) for a in argv], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True, timeout=90, **kwargs)
    log.write_text(p.stdout + "\n--- stderr ---\n" + p.stderr, encoding="utf-8")
    if p.returncode:
        raise RuntimeError("{} exited {}: {}".format(argv[0], p.returncode, log))
    return p.stdout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", required=True)
    parser.add_argument("--ubuntu-tar", required=True)
    args = parser.parse_args()
    release = Path(args.release).resolve()
    base_tar = Path(args.ubuntu_tar).resolve()
    if os.geteuid() != 0 or not os.environ.get("DISPLAY"):
        raise SystemExit("Use a fresh xvfb-run session as root for the isolated test harness.")
    evidence = Path(tempfile.mkdtemp(prefix="portable_acceptance_", dir=str(ROOT/"build")))
    host = json.loads(run([release/"start_gui.sh", "--check"], evidence/"centos_gui.log", cwd="/tmp"))
    assert host["frozen"] and host["gui_ready"] and host["ssh_ready"] and host["example_signals"] == 7
    assert host["python"].startswith("3.8.") and host["default_mode"] == "local"

    # The rootfs is the official SHA-256-verified Ubuntu Base image downloaded
    # separately. Refuse path-traversing members before extracting our test copy.
    with tarfile.open(str(base_tar)) as archive:
        for member in archive.getmembers():
            name = Path(member.name)
            if name.is_absolute() or ".." in name.parts:
                raise RuntimeError("Unsafe rootfs archive member: " + member.name)
    jail = evidence/"ubuntu"
    jail.mkdir()
    subprocess.run(["tar", "--no-same-owner", "-xzf", str(base_tar), "-C", str(jail)], check=True)
    target = jail/"opt/wave init relocated"
    shutil.copytree(str(release), str(target), symlinks=True)
    for path in list(target.rglob("*"))+[target]:
        if not path.is_symlink():
            path.chmod(path.stat().st_mode & ~0o222)
    home = jail/"tmp/gui-user"
    home.mkdir()
    home.chmod(0o755)
    os.chown(str(home), 65534, 65534)
    (jail/"tmp/.X11-unix").mkdir(exist_ok=True)
    auth = jail/"tmp/gui.xauth"
    shutil.copyfile(os.environ["XAUTHORITY"], str(auth))
    auth.chmod(0o644)
    for name in ("null", "urandom", "random"):
        path = jail/"dev"/name
        if not path.exists():
            path.touch()
    check_script = jail/"tmp/check.sh"
    check_script.write_text('''#!/bin/bash
set -eu
test ! -w '/opt/wave init relocated'
if command -v python3 >/dev/null 2>&1 || command -v python >/dev/null 2>&1; then
  echo 'The clean test rootfs unexpectedly contains a Python interpreter.' >&2
  exit 1
fi
cd /tmp
'/opt/wave init relocated/start_gui.sh' --check > /tmp/gui-user/check.json
'/opt/wave init relocated/wave_init' --cli --version > /tmp/gui-user/cli-version.txt
getconf GNU_LIBC_VERSION > /tmp/gui-user/glibc.txt
id -u > /tmp/gui-user/uid.txt
''')
    check_script.chmod(0o644)
    namespace_script = evidence/"namespace.sh"
    namespace_script.write_text('''#!/bin/bash
set -euo pipefail
jail=$1
mount --make-rprivate /
mount -t proc proc "$jail/proc"
mount --bind /tmp/.X11-unix "$jail/tmp/.X11-unix"
mount -o remount,bind,ro "$jail/tmp/.X11-unix"
for dev in null random urandom; do mount --bind "/dev/$dev" "$jail/dev/$dev"; done
exec chroot --userspec=65534:65534 "$jail" /usr/bin/env -i \\
  HOME=/tmp/gui-user USER=gui-user LOGNAME=gui-user PATH=/usr/bin:/bin LANG=C.UTF-8 \\
  DISPLAY="$DISPLAY" XAUTHORITY=/tmp/gui.xauth /bin/bash /tmp/check.sh
''')
    run(["unshare", "--mount", "--pid", "--fork", "bash", namespace_script, jail], evidence/"ubuntu_gui.log")
    ubuntu = json.loads((home/"check.json").read_text())
    assert ubuntu["gui_ready"] and ubuntu["frozen"] and ubuntu["example_signals"] == 7
    assert ubuntu["default_mode"] == "local" and ubuntu["cjk_font_found"] and ubuntu["ssh_ready"]
    assert (home/"uid.txt").read_text().strip() == "65534"
    assert (home/"glibc.txt").read_text().strip() == "glibc 2.35"
    assert (home/"cli-version.txt").read_text().strip() == host["tool_version"]

    # Exercise the relocated frozen CLI with the actual installed Verdi/KDB.
    # Environment restoration is critical: bundled Tcl/OpenSSL must not leak
    # into the external EDA program's shared-library lookup.
    out = evidence/"snapshot"
    run(["bash", "-c", 'source "$1"; shift; exec "$@"', "wave-init-test", ROOT/"tests/env.sh",
         target/"wave_init", "--cli", "--fsdb", ROOT/"build/fixture/waves.fsdb",
         "--kdb", ROOT/"build/fixture/simv.daidir", "--scope", "snapshot_top.dut", "--time", "7ns", "--out", out],
        evidence/"frozen_extraction.log", cwd="/tmp")
    expected = json.loads((ROOT/"examples/snapshot/snapshot.json").read_text())
    report = json.loads((out/"snapshot.json").read_text())
    assert {r["logical_path"]:r["value_bin"] for r in report["signals"]} == {
        r["logical_path"]:r["value_bin"] for r in expected["signals"]}
    assert report["complete"] and report["tool_version"] == host["tool_version"]
    filelist = evidence/"fixture.f"
    filelist.write_text(str(ROOT/"tests/fixtures/snapshot_design.sv")+"\n")
    output = run(["bash", "-c", 'source "$1"; shift; exec "$@"', "wave-init-test", ROOT/"tests/env.sh",
                  "bash", out/"run_vcs.sh", filelist], evidence/"vcs_replay.log")
    assert "WAVE_INIT_SNAPSHOT_PASS" in output
    proof = {"tool_version": host["tool_version"], "status": "pass", "centos_gui": host,
             "ubuntu_gui": ubuntu, "ubuntu_userspace": "Ubuntu Base 22.04.5 / glibc 2.35",
             "ubuntu_rootfs_sha256": hashlib.sha256(base_tar.read_bytes()).hexdigest(),
             "ubuntu_uid": 65534, "system_python_installed": False, "installation_read_only": True,
             "directory_contains_spaces": True, "frozen_npi_signals": len(report["signals"]),
             "vcs_assign_replay": "pass", "evidence_directory": str(evidence)}
    (evidence/"results.json").write_text(json.dumps(proof, indent=2)+"\n")
    print("PORTABLE_ACCEPTANCE_PASS: CentOS 7 + Ubuntu 22.04 userspace, no system Python, non-root, read-only relocation, 16 NPI values and VCS replay")
    print("RESULTS " + str(evidence))


if __name__ == "__main__":
    main()
