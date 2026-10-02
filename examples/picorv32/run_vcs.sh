#!/usr/bin/env bash
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
vcs -full64 -sverilog -debug_access+all -f "$rtl_filelist" \
  "$snapshot_dir/tb_snapshot.sv" -top wave_init_tb -o simv -l compile.log "$@"
./simv -l simulation.log
