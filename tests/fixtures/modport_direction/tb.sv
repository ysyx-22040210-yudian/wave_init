`timescale 1us/1ns
module direction_top;
  logic clk=1;
  a link(clk);
  assign link.pad = 1'bz;
  direction_wrap u_wrap(.bus(link));
  initial begin
    link.req=1;
    link.data=8'b10xz0101;
    #60;
    link.req=0;
    link.data=8'bz01x1010;
    #5 $finish;
  end
  initial begin
    if ($test$plusargs("LATE")) #60;
    $fsdbDumpfile("waves.fsdb");
    $fsdbDumpvars(0, direction_top, "+all");
  end
endmodule
