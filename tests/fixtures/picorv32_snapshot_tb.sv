`timescale 1ns/1ps
module picorv32_snapshot_tb;
  reg clk=0, resetn=0;
  reg mem_ready=1;
  reg [31:0] mem_rdata=32'h00000013; // ADDI x0,x0,0
  reg pcpi_wr=0, pcpi_wait=0, pcpi_ready=0;
  reg [31:0] pcpi_rd=32'h12345678;
  reg [31:0] irq=0;
  picorv32 #(.ENABLE_TRACE(1),.REGS_INIT_ZERO(1)) dut(
    .clk(clk), .resetn(resetn), .mem_ready(mem_ready), .mem_rdata(mem_rdata),
    .pcpi_wr(pcpi_wr), .pcpi_rd(pcpi_rd), .pcpi_wait(pcpi_wait), .pcpi_ready(pcpi_ready), .irq(irq)
  );
  always #5 clk=~clk;
  initial begin
    $fsdbDumpfile("waves.fsdb"); $fsdbDumpvars(0,picorv32_snapshot_tb,"+all");
    #12 resetn=1;
    #200 $finish;
  end
endmodule
