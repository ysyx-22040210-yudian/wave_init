`timescale 1ns/1ps
module split_top;
  logic clk = 1, rst_n = 1;
  split_bus link(clk);
  split_bus links[1:0](clk);
  assign link.pad = 1'bz;
  assign links[0].pad = 1'b0;
  assign links[1].pad = 1'b1;
  split_slave dut(.rst_n(rst_n), .bus(link), .seen());
  split_legacy legacy(.rst_n(rst_n), .bus(link), .seen());
  split_generic connected(.bus(link.mst), .seen());
  split_remap aliases(.bus(link), .seen());
  split_array array_dut(.buses(links), .seen());
  split_shared shared(.bus_a(link), .bus_b(link), .seen());
  initial begin
    link.req = 1;
    link.data = 8'b10xz0101;
    links[0].req = 0; links[0].data = 8'h36;
    links[1].req = 1; links[1].data = 8'hc9;
    $fsdbDumpfile("waves.fsdb");
    if ($test$plusargs("DUT_ONLY"))
      $fsdbDumpvars(0, split_top.dut, "+all");
    else if ($test$plusargs("REMAP_ONLY"))
      $fsdbDumpvars(0, split_top.aliases, "+all");
    else if ($test$plusargs("ARRAY_ONLY"))
      $fsdbDumpvars(0, split_top.array_dut, "+all");
    else if ($test$plusargs("SHARED_ONLY"))
      $fsdbDumpvars(0, split_top.shared.bus_b, "+all");
    else if ($test$plusargs("NO_INTERFACE"))
      $fsdbDumpvars(0, split_top.dut.rst_n);
    else
      $fsdbDumpvars(0, split_top, "+all");
    #4 $finish;
  end
endmodule
