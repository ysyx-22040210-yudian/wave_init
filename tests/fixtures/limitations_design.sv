`timescale 1ns/1ps
interface empty_if;
endinterface
module limited_dut #(parameter string LABEL="fixture")(input logic [3:0] data, empty_if empty_bus);
endmodule
module limitations_top;
  reg [3:0] data=4'ha;
  empty_if empty_bus();
  limited_dut dut(.*);
  initial begin
    $fsdbDumpfile("waves.fsdb"); $fsdbDumpvars(0,limitations_top,"+all");
    #2 $finish;
  end
endmodule
