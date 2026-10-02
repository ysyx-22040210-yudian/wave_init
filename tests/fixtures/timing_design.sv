`timescale 10ps/1ps
module timing_dut(input wire [7:0] data, input wire [3:0] absent, inout wire pad, output wire [7:0] y);
  assign y = data;
endmodule
module timing_top;
  reg anchor=0;
  reg [7:0] data=8'h12;
  reg [3:0] absent=4'h9;
  tri pad;
  assign pad=1'bz;
  timing_dut dut(.*,.y());
  initial begin
    #1 data=8'h23;
    #1 data=8'h34;
    #1 data=8'h45;
    #1 data=8'h56;
    #1 data=8'h67;
    #1 data=8'h78;
    #1 $finish;
  end
  initial begin
    if ($test$plusargs("LATE")) #1.5;
    $fsdbDumpfile("waves.fsdb");
    if ($test$plusargs("LATE_SIGNAL")) begin
      $fsdbDumpvars(0,timing_top.anchor);
      #1.5 $fsdbDumpvars(0,timing_top.dut,"+all");
    end else if ($test$plusargs("MISSING")) begin
      $fsdbDumpvars(0,timing_top.dut.data);
      $fsdbDumpvars(0,timing_top.dut.pad);
    end else $fsdbDumpvars(0,timing_top,"+all");
    if ($test$plusargs("GAP")) begin
      #2.5 $fsdbDumpoff;
      #2 $fsdbDumpon;
    end
  end
endmodule
