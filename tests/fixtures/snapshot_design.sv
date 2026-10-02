`timescale 1ns/1ps
package snap_pkg;
  typedef struct packed {logic [3:0] tag; logic [11:0] payload;} packet_t;
endpackage

interface snap_if #(parameter W=8)(input logic clk);
  logic req, ack;
  logic [W-1:0] wdata, rdata;
  tri pad;
  modport mst(input clk, ack, rdata, output req, wdata, inout pad);
  modport slv(input clk, req, wdata, output ack, rdata, inout pad);
  modport alias_view(input clk, .nibble(wdata[5:2]), .mix({wdata[1:0],rdata[7:6]}));
endinterface

module snap_slave #(parameter W=8)(
  input logic clk, rst_n,
  input logic signed [W-1:0] scalar,
  input logic [0:7] ascending,
  input logic [1:0][3:0] packed_data,
  input snap_pkg::packet_t packet,
  input logic [7:0] matrix [1:0][2:1],
  input logic [129:0] wide,
  inout wire pad,
  snap_if.slv bus,
  output wire [W-1:0] result
);
  assign result = scalar ^ bus.wdata;
  assign bus.ack = bus.req;
  assign bus.rdata = 8'hd3;
endmodule

module snap_master(snap_if.mst bus, output wire observe);
  assign observe = bus.ack;
endmodule
module snap_generic(interface bus, output wire observe);
  assign observe = bus.clk;
endmodule
module snap_alias(snap_if.alias_view bus, output wire [7:0] observe);
  assign observe = {bus.nibble, bus.mix};
endmodule
module snap_array(snap_if.slv buses[1:0], output wire observe);
  assign observe = buses[0].req ^ buses[1].req;
endmodule
module snap_wrapper(snap_if.slv bus);
  snap_generic nested(.bus(bus));
endmodule

module snapshot_top;
  logic clk=0, rst_n=0;
  logic signed [7:0] scalar=8'h96;
  logic [0:7] ascending=8'ha6;
  logic [1:0][3:0] packed_data=8'hb9;
  snap_pkg::packet_t packet=16'hc123;
  logic [7:0] matrix [1:0][2:1];
  logic [129:0] wide;
  tri pad;
  assign pad = 1'bz;
  snap_if link(clk);
  snap_if links[1:0](clk);
  assign link.pad = 1'bz;
  assign links[0].pad = 1'b0;
  assign links[1].pad = 1'b1;
  snap_slave dut(.*,.bus(link),.result());
  snap_master master(.bus(link),.observe());
  snap_generic connected(.bus(link.mst),.observe());
  snap_generic bare(.bus(link),.observe());
  snap_alias aliases(.bus(link),.observe());
  snap_array array_dut(.buses(links),.observe());
  snap_wrapper wrapper(.bus(link));
  initial begin
    matrix[1][2]=8'h12; matrix[1][1]=8'h11;
    matrix[0][2]=8'h02; matrix[0][1]=8'h01;
    wide={2'bxz,128'h0123456789abcdef_fedcba9876543210};
    link.req=1; link.wdata=8'ha5;
    links[0].req=0; links[0].wdata=8'h36;
    links[1].req=1; links[1].wdata=8'hc9;
    #5 clk=1; rst_n=1;
    #5 clk=0; scalar=8'b10xz0101; link.wdata=8'h5a;
    #5 clk=1;
    #5 clk=0;
    #5 $finish;
  end
  initial begin
    $fsdbDumpfile("waves.fsdb");
    $fsdbDumpvars(0,snapshot_top,"+all");
  end
endmodule
