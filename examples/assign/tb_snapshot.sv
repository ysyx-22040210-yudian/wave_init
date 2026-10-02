`timescale 1ns/1ps
// Compile with the original RTL/package filelist.
// Continuous assignments hold the sampled values throughout simulation.
// Source: assign_top.u @ 7ns (7000 ticks of 1ps).
// Internal sequential state and individual inout drivers are not reconstructed.
module wave_init_tb;
  wire  wi_bus_clk_1;
  assign_if bus (.clk(wi_bus_clk_1));
  wire [7:0] a;
  wire  dut;
  wire  check_snapshot;
  wire  wi_bus_clk;
  wire  pad;
  wire [7:0] observed;
  assign_dut dut_1 (
    .a(a),
    .dut(dut),
    .check_snapshot(check_snapshot),
    .wi_bus_clk(wi_bus_clk),
    .pad(pad),
    .bus(bus),
    .observed(observed)
  );

  // Constant FSDB snapshot drivers (input/inout; output ports are not driven).
  // assign_top.u.a (input)
  assign a = 8'b10xz0101;
  // assign_top.u.bus.req (input)
  assign bus.req = 4'b1010;
  // assign_top.u.check_snapshot (input)
  assign check_snapshot = 1'b1;
  // assign_top.u.dut (input)
  assign dut = 1'b0;
  // assign_top.u.pad (inout)
  assign pad = 1'b1;
  // assign_top.u.wi_bus_clk (input)
  assign wi_bus_clk = 1'b0;
  // assign_top.u.bus.clk (input)
  assign wi_bus_clk_1 = 1'b1;

task automatic check_snapshot_1();
  if (bus.clk !== 1'b1) $fatal(1, "snapshot mismatch at generated item 0");
  if (bus.req !== 4'b1010) $fatal(1, "snapshot mismatch at generated item 1");
  if (dut_1.a !== 8'b10xz0101) $fatal(1, "snapshot mismatch at generated item 2");
  if (dut_1.check_snapshot !== 1'b1) $fatal(1, "snapshot mismatch at generated item 3");
  if (dut_1.dut !== 1'b0) $fatal(1, "snapshot mismatch at generated item 4");
  if (dut_1.pad !== 1'b1) $fatal(1, "snapshot mismatch at generated item 5");
  if (dut_1.wi_bus_clk !== 1'b0) $fatal(1, "snapshot mismatch at generated item 6");
endtask

initial begin
  #0.001;
  check_snapshot_1();
  $display("WAVE_INIT_SNAPSHOT_PASS");
  #0.001;
  $finish;
end
endmodule
