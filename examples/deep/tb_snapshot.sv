`timescale 1ns/1ps
// Compile with the original RTL/package filelist.
// Continuous assignments hold the sampled values throughout simulation.
// Source: deep_top.soc.g_tile[1].tile.u_chain.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_leaf.dut @ 5ns (5000 ticks of 1ps).
// Internal sequential state and individual inout drivers are not reconstructed.
module wave_init_tb;
  wire  wi_bus_clk;
  split_bus #(.W(32'sb00000000000000000000000000001000)) bus (.clk(wi_bus_clk));
  wire  rst_n;
  wire  seen;
  split_slave dut (
    .rst_n(rst_n),
    .bus(bus),
    .seen(seen)
  );

  // Constant FSDB snapshot drivers (input/inout; output ports are not driven).
  // deep_top.soc.g_tile[1].tile.u_chain.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_leaf.dut.bus.data (input)
  assign bus.data = 8'bz01x1010;
  // deep_top.soc.g_tile[1].tile.u_chain.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_leaf.dut.bus.pad (inout)
  assign bus.pad = 1'bz;
  // deep_top.soc.g_tile[1].tile.u_chain.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_leaf.dut.bus.req (input)
  assign bus.req = 1'b0;
  // deep_top.soc.g_tile[1].tile.u_chain.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_leaf.dut.rst_n (input)
  assign rst_n = 1'b1;
  // deep_top.soc.g_tile[1].tile.u_chain.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_leaf.dut.bus.clk (input)
  assign wi_bus_clk = 1'b1;

task automatic check_snapshot();
  if (bus.clk !== 1'b1) $fatal(1, "snapshot mismatch at generated item 0");
  if (bus.data !== 8'bz01x1010) $fatal(1, "snapshot mismatch at generated item 1");
  if (bus.pad !== 1'bz) $fatal(1, "snapshot mismatch at generated item 2");
  if (bus.req !== 1'b0) $fatal(1, "snapshot mismatch at generated item 3");
  if (dut.rst_n !== 1'b1) $fatal(1, "snapshot mismatch at generated item 4");
endtask

initial begin
  #0.001;
  check_snapshot();
  $display("WAVE_INIT_SNAPSHOT_PASS");
  #0.001;
  $finish;
end
endmodule
