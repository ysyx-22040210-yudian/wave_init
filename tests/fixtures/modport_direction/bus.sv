`timescale 1us/1ns
interface a(input logic clk);
  logic req, ack;
  logic [7:0] data;
  tri pad;
  modport slv(input clk, req, data, inout pad, output ack);
  modport mst(input clk, ack, inout pad, output req, data);
  // A view matching the module's port NAME must never override its TYPE.
  modport xxx(input ack, output req, data);
endinterface
