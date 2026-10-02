"""Runtime paths and subprocess environments for source and frozen releases."""
import atexit
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import tempfile
from xml.sax.saxutils import escape

from . import __version__

_font_configuration = None


def resource_root():
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def output_root():
    return Path(os.environ.get("WAVE_INIT_OUTPUT_DIR", str(Path.home() / "wave_init_output"))).expanduser()


def download_root():
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
    return base / "wave_init" / "downloads"


def cli_command(arguments):
    if getattr(sys, "frozen", False):
        return [sys.executable, "--cli"] + list(arguments)
    return [sys.executable, "-u", str(resource_root() / "wave_init.py")] + list(arguments)


def prepare_gui_environment():
    global _font_configuration
    if getattr(sys, "frozen", False) and sys.platform.startswith("linux"):
        config = Path(sys.executable).parent / "fonts" / "fonts.conf"
        if config.is_file():
            os.environ.setdefault("WAVE_INIT_FONTCONFIG_ORIG", os.environ.get("FONTCONFIG_FILE", ""))
            # CentOS 7's fontconfig does not understand prefix="relative".
            # Resolve the font directory ourselves, without writing to the
            # installation directory or changing the user's font settings.
            if _font_configuration is None:
                _font_configuration = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                                                 prefix="wave_init_fonts_", suffix=".conf")
                _font_configuration.write(config.read_text(encoding="utf-8").replace(
                    "@WAVE_INIT_FONT_DIR@", escape(str(config.parent))))
                _font_configuration.flush()
                atexit.register(_font_configuration.close)
            os.environ["FONTCONFIG_FILE"] = _font_configuration.name


def external_environment():
    """Do not inject the frozen app's shared libraries into Verdi or xdg-open."""
    env = os.environ.copy()
    if getattr(sys, "frozen", False):
        original = env.pop("LD_LIBRARY_PATH_ORIG", None)
        if original is None:
            env.pop("LD_LIBRARY_PATH", None)
        else:
            env["LD_LIBRARY_PATH"] = original
        bundle = str(resource_root())
        for key in ("TCL_LIBRARY", "TK_LIBRARY"):
            value = env.get(key, "")
            if value == bundle or value.startswith(bundle + os.sep):
                env.pop(key, None)
        if "WAVE_INIT_FONTCONFIG_ORIG" in env:
            original_font = env.pop("WAVE_INIT_FONTCONFIG_ORIG")
            if original_font:
                env["FONTCONFIG_FILE"] = original_font
            else:
                env.pop("FONTCONFIG_FILE", None)
    return env


def check_environment():
    """Check the actual GUI runtime. Verdi is optional for viewing reports."""
    prepare_gui_environment()
    info = {"tool_version": __version__, "frozen": bool(getattr(sys, "frozen", False)),
            "python": platform.python_version(), "platform": platform.platform(),
            "resource_root": str(resource_root()), "output_root": str(output_root()),
            "gui_ready": False, "verdi": shutil.which("verdi"), "errors": []}
    if sys.platform.startswith("linux"):
        info["glibc"] = os.confstr("CS_GNU_LIBC_VERSION")
    if not info["verdi"] and os.environ.get("VERDI_HOME"):
        candidate = Path(os.environ["VERDI_HOME"]) / "bin" / "verdi"
        if candidate.is_file():
            info["verdi"] = str(candidate)
    if not (resource_root() / "backend" / "snapshot.tcl").is_file():
        info["errors"].append("Missing backend/snapshot.tcl; copy the complete release directory.")
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        info["tk"] = root.tk.call("info", "patchlevel")
        info["cjk_font_found"] = any("WenQuanYi" in name for name in root.tk.call("font", "families"))
        # Exercise the complete widget tree and bundled sample, not just Tcl.
        from .gui import WaveInitApp
        from .gui_runner import load_report
        app = WaveInitApp(root)
        example = resource_root() / "examples" / "assign"
        app.install_report(load_report(example / "snapshot.json"), example)
        root.update_idletasks()
        info["example_signals"] = len(app.tree.get_children())
        info["default_mode"] = app.vars["mode"].get()
        app.destroy()
        info["gui_ready"] = not info["errors"]
    except (ImportError, RuntimeError) as exc:
        info["errors"].append(str(exc))
    except Exception as exc:
        info["errors"].append("A Linux desktop/X11 display is required: " + str(exc))
    try:
        import paramiko
        info["ssh_ready"] = True
        info["paramiko"] = paramiko.__version__
    except ImportError:
        info["ssh_ready"] = False
    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0 if info["gui_ready"] else 1
