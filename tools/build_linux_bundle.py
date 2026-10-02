#!/usr/bin/env python3
"""Build a relocatable Linux x86_64 release on the oldest supported glibc host."""
import argparse
import ast
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tkinter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from waveinit import __version__


def license_name(name):
    return name.lower().startswith(("license", "licence", "copying", "copyright", "notice"))


def copy_notices(destination, binaries, font_path):
    """Retain installed package notices with the redistributed runtime."""
    packages = []
    for dist in importlib.metadata.distributions():
        name = dist.metadata.get("Name", "unknown")
        packages.append({"name": name, "version": dist.version})
        for item in dist.files or []:
            if license_name(Path(str(item)).name):
                source = Path(dist.locate_file(item))
                if source.is_file():
                    target = destination / "python-packages" / name / str(item).replace("/", "__")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(str(source), str(target))
    system = []
    owners = set()
    if shutil.which("rpm"):
        for source in binaries + [sys.executable, font_path]:
            p = subprocess.run(["rpm", "-qf", str(Path(source).resolve()), "--qf", "%{NAME}\n"],
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True)
            if p.returncode == 0:
                owners.update(p.stdout.splitlines())
        for owner in sorted(owners):
            data = subprocess.check_output(["rpm", "-q", owner, "--qf", "%{NAME}|%{VERSION}-%{RELEASE}|%{LICENSE}|%{SOURCERPM}"], universal_newlines=True)
            name, version, license_, source_rpm = data.split("|", 3)
            system.append({"name": name, "version": version, "license": license_, "source_rpm": source_rpm})
            for item in subprocess.check_output(["rpm", "-ql", owner], universal_newlines=True).splitlines():
                source = Path(item)
                if source.is_file() and license_name(source.name) and ("/doc/" in item or "/licenses/" in item):
                    target = destination / "system-packages" / owner / source.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(str(source), str(target))
    (destination / "packages.json").write_text(json.dumps({"python": packages, "system": system}, indent=2)+"\n")


def original_binaries(toc):
    result = []
    def visit(value):
        if isinstance(value, (tuple, list)):
            if len(value) == 3 and value[2] in ("BINARY", "EXTENSION") and isinstance(value[1], str):
                result.append(value[1])
            else:
                for part in value:
                    visit(part)
    visit(ast.literal_eval(toc.read_text()))
    return result


def glibc_requirements(directory):
    versions, counts = set(), 0
    for path in directory.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        with path.open("rb") as stream:
            if stream.read(4) != b"\x7fELF":
                continue
        data = subprocess.check_output(["readelf", "--version-info", str(path)], universal_newlines=True)
        versions.update(tuple(map(int, v.split("."))) for v in re.findall(r"GLIBC_(\d+(?:\.\d+)+)", data))
        counts += 1
    maximum = max(versions) if versions else ()
    if maximum > (2, 17):
        raise RuntimeError("Bundled ELF requires GLIBC_{}; build/dependencies must target glibc 2.17".format(".".join(map(str, maximum))))
    return {"elf_files": counts, "max_glibc_required": ".".join(map(str, maximum))}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", default=str(ROOT / "dist"))
    args = p.parse_args()
    if sys.platform != "linux" or platform.machine() != "x86_64" or sys.version_info[:2] != (3, 8):
        raise SystemExit("Build this release with Python 3.8 on Linux x86_64 (glibc 2.17).")
    import PyInstaller
    import paramiko
    build = ROOT / "build"
    build.mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="linux_package_", dir=str(build)))
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    archive = out / "wave_init-{}-linux-x86_64.tar.gz".format(__version__)
    if archive.exists():
        raise SystemExit("Release already exists; select a fresh --output directory: " + str(archive))
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--onedir", "--name", "wave_init",
               "--distpath", str(work / "stage"), "--workpath", str(work / "pyinstaller"),
               "--specpath", str(work), "--copy-metadata", "paramiko", "--copy-metadata", "cryptography",
               "--add-data", str(ROOT/"backend")+os.pathsep+"backend",
               "--add-data", str(ROOT/"examples/assign")+os.pathsep+"examples/assign",
               "--add-data", str(ROOT/"LINUX.md")+os.pathsep+".",
               "--add-data", str(ROOT/"README.md")+os.pathsep+".", str(ROOT/"wave_init_gui.py")]
    env = os.environ.copy()
    for name in ("PYTHONPATH", "LD_LIBRARY_PATH", "LD_LIBRARY_PATH_ORIG", "TCL_LIBRARY", "TK_LIBRARY"):
        env.pop(name, None)
    env["PYTHONNOUSERSITE"] = "1"
    # PyInstaller treats libxcb as a system desktop library. Minimal Linux
    # installations may lack it even when an X11 display is reachable, so ship
    # the build host's compatible copy with the other Tk/X11 dependencies.
    tk_dependencies = subprocess.check_output(["ldd", tkinter._tkinter.__file__], env=env,
                                               universal_newlines=True)
    xcb = re.search(r"libxcb\.so\.1\s+=>\s+(/\S+)", tk_dependencies)
    if not xcb:
        raise RuntimeError("Cannot locate Tk's libxcb.so.1 dependency for the portable release.")
    command[-1:-1] = ["--add-binary", xcb.group(1) + os.pathsep + "."]
    print("Building Linux release; log: " + str(work / "pyinstaller.log"), flush=True)
    with (work / "pyinstaller.log").open("w") as log:
        subprocess.run(command, cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    directory = work / "stage" / "wave_init"
    release = directory.with_name("wave_init-linux-x86_64")
    directory.rename(release)
    for name in ("start_gui.sh", "wave_init.py", "wave_init_gui.py", "README.md", "LINUX.md"):
        shutil.copyfile(str(ROOT/name), str(release/name))
    (release/"start_gui.sh").chmod(0o755)
    for name in ("waveinit", "backend"):
        shutil.copytree(str(ROOT/name), str(release/name), ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(str(ROOT/"examples/assign"), str(release/"examples/assign"))
    # Include a CJK font so Chinese controls remain readable on minimal desktops.
    font_path = subprocess.check_output(["fc-match", "WenQuanYi Zen Hei", "-f", "%{file}"], universal_newlines=True).strip()
    if not font_path or "wqy" not in font_path.lower():
        raise RuntimeError("Install the WenQuanYi Zen Hei font in the build environment before packaging.")
    (release/"fonts").mkdir()
    shutil.copyfile(font_path, str(release/"fonts"/Path(font_path).name))
    (release/"fonts/fonts.conf").write_text('''<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <include ignore_missing="yes">/etc/fonts/fonts.conf</include>
  <dir>@WAVE_INIT_FONT_DIR@</dir>
  <cachedir prefix="xdg">fontconfig</cachedir>
</fontconfig>
''')
    notices = release/"licenses"
    notices.mkdir()
    originals = original_binaries(work/"pyinstaller/wave_init/COLLECT-00.toc")
    copy_notices(notices, originals, font_path)
    audit = glibc_requirements(release)
    lock = subprocess.check_output([sys.executable, "-m", "pip", "freeze"], universal_newlines=True)
    (release/"build-requirements.lock").write_text(lock)
    metadata = {"tool_version": __version__, "python": platform.python_version(), "tk_target": str(tkinter.TkVersion),
                "build_glibc": os.confstr("CS_GNU_LIBC_VERSION"),
                "architecture": "x86_64", "build_platform": platform.platform(), "pyinstaller": PyInstaller.__version__,
                "paramiko": paramiko.__version__, "minimum_glibc": "2.17", "native_audit": audit,
                "source_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                  for path in [ROOT/"wave_init_gui.py", ROOT/"start_gui.sh"]+sorted((ROOT/"waveinit").glob("*.py"))+[ROOT/"backend/snapshot.tcl"]}}
    (release/"bundle_info.json").write_text(json.dumps(metadata, indent=2)+"\n")
    with tarfile.open(str(archive), "w:gz") as tar:
        tar.add(str(release), arcname=release.name)
    sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_name(archive.name+".sha256").write_text(sha+"  "+archive.name+"\n")
    (out/"latest-build.json").write_text(json.dumps({"release_directory": str(release), "archive": str(archive),
                                                   "sha256": sha, "work_directory": str(work)}, indent=2)+"\n")
    print("RELEASE " + str(release))
    print("ARCHIVE " + str(archive))
    print("SIZE_MB {:.1f}".format(archive.stat().st_size/1024/1024))


if __name__ == "__main__":
    main()
