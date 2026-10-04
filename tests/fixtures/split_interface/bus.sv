`timescale 1ns/1ps
interface split_bus #(parameter W=8)(input logic clk);
  logic req, ack;
  logic [W-1:0] data;
  tri pad;
  modport slv(input clk, req, data, inout pad, output ack);
  modport mst(input clk, ack, inout pad, output req, data);
  modport remap(input clk, .req(ack), .ack(req),
                .nibble(data[5:2]), .mix({data[1:0], data[7:6]}), inout pad);
endinterface
