`timescale 1ns/1ps
module glitch_dut(input wire [3:0] data, output wire [3:0] y);
  assign y=data;
endmodule
module glitch_top;
  reg [3:0] data=0;
  glitch_dut dut(.data(data),.y());
  initial begin
    $fsdbDumpfile("waves.fsdb"); $fsdbDumpvars(0,glitch_top,"+all");
    #1 data=4'h1;
    #0 data=4'h2;
    #0 data=4'h3;
    #1 $finish;
  end
endmodule
