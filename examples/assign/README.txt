wave_init snapshot

Source instance: assign_top.u
Source time: 7ns = 7000 ticks of 1ps

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
