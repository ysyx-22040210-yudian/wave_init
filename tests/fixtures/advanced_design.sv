`timescale 1ns/1ps
package adv_pkg;
  typedef struct {logic [3:0] tag; int payload;} record_t;
  typedef union packed {logic [15:0] word; logic [1:0][7:0] bytes;} union_t;
endpackage
interface adv_if #(parameter W=16)(input wire clk);
  logic [W-1:0] data;
  logic [7:0] words[1:0];
  logic ready;
  modport slv(input clk, data, words, output ready);
  modport mst(input clk, ready, output data, words);
endinterface
module advanced_dut #(parameter W=13)(
  input logic [W-1:0] param_data,
  input adv_pkg::record_t record_data,
  input adv_pkg::union_t union_data,
  input wire \escaped.port ,
  adv_if.slv bus_a,
  adv_if.slv bus_b,
  output wire seen
);
  assign seen = param_data[0] ^ bus_a.data[0] ^ bus_b.words[1][0];
endmodule
module advanced_top;
  reg clk=1;
  logic [12:0] param_data=13'h1593;
  adv_pkg::record_t record_data;
  adv_pkg::union_t union_data;
  adv_if #(.W(24)) link(clk);
  advanced_dut #(.W(13)) dut(.param_data(param_data), .record_data(record_data),
    .union_data(union_data), .\escaped.port (1'b1), .bus_a(link), .bus_b(link), .seen());
  initial begin
    record_data.tag=4'hb; record_data.payload=32'h12345678;
    union_data.word=16'h5678;
    link.data=24'h123456; link.words[0]=8'ha6; link.words[1]=8'h59;
    $fsdbDumpfile("waves.fsdb"); $fsdbDumpvars(0,advanced_top,"+all");
    #4 $finish;
  end
endmodule
