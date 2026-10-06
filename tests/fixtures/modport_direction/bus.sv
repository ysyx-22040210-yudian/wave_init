`timescale 1us/1ns
interface a(input logic clk);
  logic req, ack;
  logic [7:0] data;
  tri pad;
  modport slv(input clk, req, data, inout pad, output ack);
  modport mst(input clk, ack, inout pad, output req, data);
  // A view matching the module's port NAME must never override its TYPE.
  modport xxx(input ack, output req, data);
  modport remap(input clk, .req(ack), .ack(req),
                .nibble(data[5:2]), .mix({data[1:0], data[7:6]}), inout pad);
endinterface
