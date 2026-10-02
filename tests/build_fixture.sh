#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source tests/env.sh
project_dir=$PWD
mkdir -p build/fixture
cd build/fixture
vcs -full64 -sverilog -debug_access+all -kdb -lca \
  -P "$VERDI_HOME/share/PLI/VCS/LINUX64/novas.tab" \
     "$VERDI_HOME/share/PLI/VCS/LINUX64/pli.a" \
  "$project_dir/tests/fixtures/snapshot_design.sv" \
  -top snapshot_top -o simv -l compile.log
./simv -l simulation.log
