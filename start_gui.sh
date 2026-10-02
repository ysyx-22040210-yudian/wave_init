#!/usr/bin/env bash
# Relocatable launcher: prefer the bundled runtime, then a source installation.
set -euo pipefail
launcher_path=${BASH_SOURCE[0]}
while [ -L "$launcher_path" ]; do
    launcher_dir=$(cd -- "$(dirname -- "$launcher_path")" && pwd -P)
    launcher_path=$(readlink -- "$launcher_path")
    case "$launcher_path" in /*) ;; *) launcher_path="$launcher_dir/$launcher_path" ;; esac
done
app_dir=$(cd -- "$(dirname -- "$launcher_path")" && pwd -P)

if [ -x "$app_dir/wave_init" ]; then
    if [ "$(uname -s)" != Linux ] || [ "$(uname -m)" != x86_64 ]; then
        echo 'This binary release requires Linux x86_64. Use the Python source release on other architectures.' >&2
        exit 1
    fi
    exec "$app_dir/wave_init" "$@"
fi

if [ -n "${WAVE_INIT_PYTHON:-}" ]; then
    candidates=("$WAVE_INIT_PYTHON")
else
    candidates=(python3.8 python3 python3.9 python3.10 python3.11 python3.12 python3.13 python3.14 python)
fi
for candidate in "${candidates[@]}"; do
    if interpreter=$(command -v -- "$candidate" 2>/dev/null); then
        if "$interpreter" -c 'import sys; assert sys.version_info >= (3,8); import tkinter' >/dev/null 2>&1; then
            exec "$interpreter" "$app_dir/wave_init_gui.py" "$@"
        fi
    fi
done
echo 'No Python 3.8+ with Tk was found. Use the Linux binary archive (Python/Tk included),' >&2
echo 'or set WAVE_INIT_PYTHON=/absolute/path/to/python3.8 with its matching Tk module.' >&2
exit 1
