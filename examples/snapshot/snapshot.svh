// Generated boundary snapshot. Call apply_snapshot() explicitly.
// Values are resolved FSDB values, including X/Z. Inout driver ownership is not reconstructed.
task automatic apply_snapshot();
  force snapshot_top.dut.ascending = 8'b10100110;
  force snapshot_top.dut.clk = 1'b1;
  force snapshot_top.dut.matrix[0][1] = 8'b00000001;
  force snapshot_top.dut.matrix[0][2] = 8'b00000010;
  force snapshot_top.dut.matrix[1][1] = 8'b00010001;
  force snapshot_top.dut.matrix[1][2] = 8'b00010010;
  force snapshot_top.dut.packed_data = 8'b10111001;
  force snapshot_top.dut.packet = 16'b1100000100100011;
  force snapshot_top.dut.pad = 1'bz;
  force snapshot_top.dut.rst_n = 1'b1;
  force snapshot_top.dut.scalar = 8'b10010110;
  force snapshot_top.dut.wide = 130'bxz00000001001000110100010101100111100010011010101111001101111011111111111011011100101110101001100001110110010101000011001000010000;
  force snapshot_top.link.clk = 1'b1;
  force snapshot_top.link.pad = 1'bz;
  force snapshot_top.link.req = 1'b1;
  force snapshot_top.link.wdata = 8'b10100101;
endtask

task automatic release_snapshot();
  release snapshot_top.dut.ascending;
  release snapshot_top.dut.clk;
  release snapshot_top.dut.matrix[0][1];
  release snapshot_top.dut.matrix[0][2];
  release snapshot_top.dut.matrix[1][1];
  release snapshot_top.dut.matrix[1][2];
  release snapshot_top.dut.packed_data;
  release snapshot_top.dut.packet;
  release snapshot_top.dut.pad;
  release snapshot_top.dut.rst_n;
  release snapshot_top.dut.scalar;
  release snapshot_top.dut.wide;
  release snapshot_top.link.clk;
  release snapshot_top.link.pad;
  release snapshot_top.link.req;
  release snapshot_top.link.wdata;
endtask

task automatic check_snapshot();
  if (snapshot_top.dut.ascending !== 8'b10100110) $fatal(1, "snapshot mismatch at generated item 0");
  if (snapshot_top.dut.clk !== 1'b1) $fatal(1, "snapshot mismatch at generated item 1");
  if (snapshot_top.dut.matrix[0][1] !== 8'b00000001) $fatal(1, "snapshot mismatch at generated item 2");
  if (snapshot_top.dut.matrix[0][2] !== 8'b00000010) $fatal(1, "snapshot mismatch at generated item 3");
  if (snapshot_top.dut.matrix[1][1] !== 8'b00010001) $fatal(1, "snapshot mismatch at generated item 4");
  if (snapshot_top.dut.matrix[1][2] !== 8'b00010010) $fatal(1, "snapshot mismatch at generated item 5");
  if (snapshot_top.dut.packed_data !== 8'b10111001) $fatal(1, "snapshot mismatch at generated item 6");
  if (snapshot_top.dut.packet !== 16'b1100000100100011) $fatal(1, "snapshot mismatch at generated item 7");
  if (snapshot_top.dut.pad !== 1'bz) $fatal(1, "snapshot mismatch at generated item 8");
  if (snapshot_top.dut.rst_n !== 1'b1) $fatal(1, "snapshot mismatch at generated item 9");
  if (snapshot_top.dut.scalar !== 8'b10010110) $fatal(1, "snapshot mismatch at generated item 10");
  if (snapshot_top.dut.wide !== 130'bxz00000001001000110100010101100111100010011010101111001101111011111111111011011100101110101001100001110110010101000011001000010000) $fatal(1, "snapshot mismatch at generated item 11");
  if (snapshot_top.link.clk !== 1'b1) $fatal(1, "snapshot mismatch at generated item 12");
  if (snapshot_top.link.pad !== 1'bz) $fatal(1, "snapshot mismatch at generated item 13");
  if (snapshot_top.link.req !== 1'b1) $fatal(1, "snapshot mismatch at generated item 14");
  if (snapshot_top.link.wdata !== 8'b10100101) $fatal(1, "snapshot mismatch at generated item 15");
endtask
