#!/usr/bin/env python3
"""Launch the Python 3.8+ Tkinter frontend."""
import sys

if __name__ == "__main__":
    if sys.version_info < (3, 8):
        raise SystemExit("The GUI requires Python 3.8 or newer; the CLI still supports Python 3.6+.")
    if sys.argv[1:2] == ["--cli"]:
        from waveinit.cli import main
        raise SystemExit(main(sys.argv[2:]))
    if sys.argv[1:] == ["--check"]:
        from waveinit.portable import check_environment
        raise SystemExit(check_environment())
    if sys.argv[1:] == ["--version"]:
        from waveinit import __version__
        print(__version__)
        raise SystemExit(0)
    from waveinit.portable import prepare_gui_environment
    prepare_gui_environment()
    try:
        from waveinit.gui import main
    except ImportError as exc:
        if exc.name in ("tkinter", "_tkinter"):
            raise SystemExit("Tkinter is unavailable. Install the Tk package matching this Python interpreter.")
        raise
    raise SystemExit(main())
