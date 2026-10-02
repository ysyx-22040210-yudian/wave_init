`timescale 1ns/1ps
interface assign_if(input logic clk);
  logic [3:0] req, resp;
  modport slv(input clk, req, output resp);
endinterface

module assign_dut(
  input var logic [7:0] a,
  input wire dut, check_snapshot, wi_bus_clk,
  inout wire pad,
  assign_if.slv bus,
  output wire [7:0] observed
);
  assign observed = a ^ {4'b0, bus.req};
  assign bus.resp = a[3:0];
  assign pad = 1'bz;
endmodule

module assign_top;
  logic [7:0] a = 8'h96;
  logic clk = 0;
  tri pad;
  assign pad = 1'b1;
  assign_if link(clk);
  assign_dut u(.a(a), .dut(1'b0), .check_snapshot(1'b1), .wi_bus_clk(1'b0),
               .pad(pad), .bus(link), .observed());
  initial begin
    link.req = 4'ha;
    $fsdbDumpfile("waves.fsdb");
    $fsdbDumpvars(0, assign_top, "+all");
    #5; a = 8'b10xz0101; clk = 1;
    #5; $finish;
  end
endmodule
