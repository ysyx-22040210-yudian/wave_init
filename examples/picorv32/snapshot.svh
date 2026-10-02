// Generated boundary snapshot. Call apply_snapshot() explicitly.
// Values are resolved FSDB values, including X/Z. Inout driver ownership is not reconstructed.
task automatic apply_snapshot();
  force picorv32_snapshot_tb.dut.clk = 1'b1;
  force picorv32_snapshot_tb.dut.irq = 32'b00000000000000000000000000000000;
  force picorv32_snapshot_tb.dut.mem_rdata = 32'b00000000000000000000000000010011;
  force picorv32_snapshot_tb.dut.mem_ready = 1'b1;
  force picorv32_snapshot_tb.dut.pcpi_rd = 32'b00010010001101000101011001111000;
  force picorv32_snapshot_tb.dut.pcpi_ready = 1'b0;
  force picorv32_snapshot_tb.dut.pcpi_wait = 1'b0;
  force picorv32_snapshot_tb.dut.pcpi_wr = 1'b0;
  force picorv32_snapshot_tb.dut.resetn = 1'b1;
endtask

task automatic release_snapshot();
  release picorv32_snapshot_tb.dut.clk;
  release picorv32_snapshot_tb.dut.irq;
  release picorv32_snapshot_tb.dut.mem_rdata;
  release picorv32_snapshot_tb.dut.mem_ready;
  release picorv32_snapshot_tb.dut.pcpi_rd;
  release picorv32_snapshot_tb.dut.pcpi_ready;
  release picorv32_snapshot_tb.dut.pcpi_wait;
  release picorv32_snapshot_tb.dut.pcpi_wr;
  release picorv32_snapshot_tb.dut.resetn;
endtask

task automatic check_snapshot();
  if (picorv32_snapshot_tb.dut.clk !== 1'b1) $fatal(1, "snapshot mismatch at generated item 0");
  if (picorv32_snapshot_tb.dut.irq !== 32'b00000000000000000000000000000000) $fatal(1, "snapshot mismatch at generated item 1");
  if (picorv32_snapshot_tb.dut.mem_rdata !== 32'b00000000000000000000000000010011) $fatal(1, "snapshot mismatch at generated item 2");
  if (picorv32_snapshot_tb.dut.mem_ready !== 1'b1) $fatal(1, "snapshot mismatch at generated item 3");
  if (picorv32_snapshot_tb.dut.pcpi_rd !== 32'b00010010001101000101011001111000) $fatal(1, "snapshot mismatch at generated item 4");
  if (picorv32_snapshot_tb.dut.pcpi_ready !== 1'b0) $fatal(1, "snapshot mismatch at generated item 5");
  if (picorv32_snapshot_tb.dut.pcpi_wait !== 1'b0) $fatal(1, "snapshot mismatch at generated item 6");
  if (picorv32_snapshot_tb.dut.pcpi_wr !== 1'b0) $fatal(1, "snapshot mismatch at generated item 7");
  if (picorv32_snapshot_tb.dut.resetn !== 1'b1) $fatal(1, "snapshot mismatch at generated item 8");
endtask
