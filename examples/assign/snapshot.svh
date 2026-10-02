// Generated boundary snapshot. Call apply_snapshot() explicitly.
// Values are resolved FSDB values, including X/Z. Inout driver ownership is not reconstructed.
task automatic apply_snapshot();
  force assign_top.link.clk = 1'b1;
  force assign_top.link.req = 4'b1010;
  force assign_top.u.a = 8'b10xz0101;
  force assign_top.u.check_snapshot = 1'b1;
  force assign_top.u.dut = 1'b0;
  force assign_top.u.pad = 1'b1;
  force assign_top.u.wi_bus_clk = 1'b0;
endtask

task automatic release_snapshot();
  release assign_top.link.clk;
  release assign_top.link.req;
  release assign_top.u.a;
  release assign_top.u.check_snapshot;
  release assign_top.u.dut;
  release assign_top.u.pad;
  release assign_top.u.wi_bus_clk;
endtask

task automatic check_snapshot();
  if (assign_top.link.clk !== 1'b1) $fatal(1, "snapshot mismatch at generated item 0");
  if (assign_top.link.req !== 4'b1010) $fatal(1, "snapshot mismatch at generated item 1");
  if (assign_top.u.a !== 8'b10xz0101) $fatal(1, "snapshot mismatch at generated item 2");
  if (assign_top.u.check_snapshot !== 1'b1) $fatal(1, "snapshot mismatch at generated item 3");
  if (assign_top.u.dut !== 1'b0) $fatal(1, "snapshot mismatch at generated item 4");
  if (assign_top.u.pad !== 1'b1) $fatal(1, "snapshot mismatch at generated item 5");
  if (assign_top.u.wi_bus_clk !== 1'b0) $fatal(1, "snapshot mismatch at generated item 6");
endtask
