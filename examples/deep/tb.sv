`timescale 1ns/1ps
module deep_top;
  logic clk=1, rst_n=1;
  deep_soc #(.DEPTH(8)) soc(.clk(clk), .rst_n(rst_n));
  initial begin
    $fsdbDumpfile("waves.fsdb");
    if ($test$plusargs("DUT_ONLY")) $fsdbDumpvars(0, deep_top.soc.g_tile[1].tile.u_chain.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_leaf.dut, "+all");
    else if ($test$plusargs("MIDDLE_ONLY")) begin
      $fsdbDumpvars(0, deep_top.soc.g_tile[1].tile.u_chain.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child, "+all");
    end
    else if ($test$plusargs("MIDDLE_PROXY_ONLY")) begin
      $fsdbDumpvars(0, deep_top.soc.g_tile[1].tile.u_chain.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.upstream, "+all");
      $fsdbDumpvars(0, deep_top.soc.g_tile[1].tile.u_chain.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_leaf.dut.rst_n);
    end
    else if ($test$plusargs("ARRAY_ONLY")) $fsdbDumpvars(0, deep_top.soc.g_tile[1].tile.u_chain.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_leaf.array_dut, "+all");
    else if ($test$plusargs("SHARED_ONLY")) $fsdbDumpvars(0, deep_top.soc.g_tile[1].tile.u_chain.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_leaf.shared.bus_b, "+all");
    else $fsdbDumpvars(0, deep_top, "+all");
    #9 $finish;
  end
endmodule
