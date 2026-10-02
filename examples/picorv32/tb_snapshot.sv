`timescale 1ns/1ps
// Compile with the original RTL/package filelist.
// Continuous assignments hold the sampled values throughout simulation.
// Source: picorv32_snapshot_tb.dut @ 26ns (26000 ticks of 1ps).
// Internal sequential state and individual inout drivers are not reconstructed.
module wave_init_tb;
  wire  clk;
  wire  resetn;
  wire  trap;
  wire  mem_valid;
  wire  mem_instr;
  wire  mem_ready;
  wire [31:0] mem_addr;
  wire [31:0] mem_wdata;
  wire [3:0] mem_wstrb;
  wire [31:0] mem_rdata;
  wire  mem_la_read;
  wire  mem_la_write;
  wire [31:0] mem_la_addr;
  wire [31:0] mem_la_wdata;
  wire [3:0] mem_la_wstrb;
  wire  pcpi_valid;
  wire [31:0] pcpi_insn;
  wire [31:0] pcpi_rs1;
  wire [31:0] pcpi_rs2;
  wire  pcpi_wr;
  wire [31:0] pcpi_rd;
  wire  pcpi_wait;
  wire  pcpi_ready;
  wire [31:0] irq;
  wire [31:0] eoi;
  wire  trace_valid;
  wire [35:0] trace_data;
  picorv32 #(.ENABLE_COUNTERS(1'b1), .ENABLE_COUNTERS64(1'b1), .ENABLE_REGS_16_31(1'b1), .ENABLE_REGS_DUALPORT(1'b1), .LATCHED_MEM_RDATA(1'b0), .TWO_STAGE_SHIFT(1'b1), .BARREL_SHIFTER(1'b0), .TWO_CYCLE_COMPARE(1'b0), .TWO_CYCLE_ALU(1'b0), .COMPRESSED_ISA(1'b0), .CATCH_MISALIGN(1'b1), .CATCH_ILLINSN(1'b1), .ENABLE_PCPI(1'b0), .ENABLE_MUL(1'b0), .ENABLE_FAST_MUL(1'b0), .ENABLE_DIV(1'b0), .ENABLE_IRQ(1'b0), .ENABLE_IRQ_QREGS(1'b1), .ENABLE_IRQ_TIMER(1'b1), .ENABLE_TRACE(1'b1), .REGS_INIT_ZERO(1'b1), .MASKED_IRQ(32'b00000000000000000000000000000000), .LATCHED_IRQ(32'b11111111111111111111111111111111), .PROGADDR_RESET(32'b00000000000000000000000000000000), .PROGADDR_IRQ(32'b00000000000000000000000000010000), .STACKADDR(32'b11111111111111111111111111111111)) dut (
    .clk(clk),
    .resetn(resetn),
    .trap(trap),
    .mem_valid(mem_valid),
    .mem_instr(mem_instr),
    .mem_ready(mem_ready),
    .mem_addr(mem_addr),
    .mem_wdata(mem_wdata),
    .mem_wstrb(mem_wstrb),
    .mem_rdata(mem_rdata),
    .mem_la_read(mem_la_read),
    .mem_la_write(mem_la_write),
    .mem_la_addr(mem_la_addr),
    .mem_la_wdata(mem_la_wdata),
    .mem_la_wstrb(mem_la_wstrb),
    .pcpi_valid(pcpi_valid),
    .pcpi_insn(pcpi_insn),
    .pcpi_rs1(pcpi_rs1),
    .pcpi_rs2(pcpi_rs2),
    .pcpi_wr(pcpi_wr),
    .pcpi_rd(pcpi_rd),
    .pcpi_wait(pcpi_wait),
    .pcpi_ready(pcpi_ready),
    .irq(irq),
    .eoi(eoi),
    .trace_valid(trace_valid),
    .trace_data(trace_data)
  );

  // Constant FSDB snapshot drivers (input/inout; output ports are not driven).
  // picorv32_snapshot_tb.dut.clk (input)
  assign clk = 1'b1;
  // picorv32_snapshot_tb.dut.irq (input)
  assign irq = 32'b00000000000000000000000000000000;
  // picorv32_snapshot_tb.dut.mem_rdata (input)
  assign mem_rdata = 32'b00000000000000000000000000010011;
  // picorv32_snapshot_tb.dut.mem_ready (input)
  assign mem_ready = 1'b1;
  // picorv32_snapshot_tb.dut.pcpi_rd (input)
  assign pcpi_rd = 32'b00010010001101000101011001111000;
  // picorv32_snapshot_tb.dut.pcpi_ready (input)
  assign pcpi_ready = 1'b0;
  // picorv32_snapshot_tb.dut.pcpi_wait (input)
  assign pcpi_wait = 1'b0;
  // picorv32_snapshot_tb.dut.pcpi_wr (input)
  assign pcpi_wr = 1'b0;
  // picorv32_snapshot_tb.dut.resetn (input)
  assign resetn = 1'b1;

task automatic check_snapshot();
  if (dut.clk !== 1'b1) $fatal(1, "snapshot mismatch at generated item 0");
  if (dut.irq !== 32'b00000000000000000000000000000000) $fatal(1, "snapshot mismatch at generated item 1");
  if (dut.mem_rdata !== 32'b00000000000000000000000000010011) $fatal(1, "snapshot mismatch at generated item 2");
  if (dut.mem_ready !== 1'b1) $fatal(1, "snapshot mismatch at generated item 3");
  if (dut.pcpi_rd !== 32'b00010010001101000101011001111000) $fatal(1, "snapshot mismatch at generated item 4");
  if (dut.pcpi_ready !== 1'b0) $fatal(1, "snapshot mismatch at generated item 5");
  if (dut.pcpi_wait !== 1'b0) $fatal(1, "snapshot mismatch at generated item 6");
  if (dut.pcpi_wr !== 1'b0) $fatal(1, "snapshot mismatch at generated item 7");
  if (dut.resetn !== 1'b1) $fatal(1, "snapshot mismatch at generated item 8");
endtask

initial begin
  #0.001;
  check_snapshot();
  $display("WAVE_INIT_SNAPSHOT_PASS");
  #0.001;
  $finish;
end
endmodule
