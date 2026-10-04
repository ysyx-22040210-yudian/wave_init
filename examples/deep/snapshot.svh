// Generated boundary snapshot. Call apply_snapshot() explicitly.
// Values are resolved FSDB values, including X/Z. Inout driver ownership is not reconstructed.
task automatic apply_snapshot();
  force existing_replay.original.soc.g_tile[1].tile.link.clk = 1'b1;
  force existing_replay.original.soc.g_tile[1].tile.link.data = 8'b10xz0101;
  force existing_replay.original.soc.g_tile[1].tile.link.pad = 1'bz;
  force existing_replay.original.soc.g_tile[1].tile.link.req = 1'b1;
  force existing_replay.original.soc.g_tile[1].tile.u_chain.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_leaf.dut.rst_n = 1'b1;
endtask

task automatic release_snapshot();
  release existing_replay.original.soc.g_tile[1].tile.link.clk;
  release existing_replay.original.soc.g_tile[1].tile.link.data;
  release existing_replay.original.soc.g_tile[1].tile.link.pad;
  release existing_replay.original.soc.g_tile[1].tile.link.req;
  release existing_replay.original.soc.g_tile[1].tile.u_chain.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_leaf.dut.rst_n;
endtask

task automatic check_snapshot();
  if (existing_replay.original.soc.g_tile[1].tile.link.clk !== 1'b1) $fatal(1, "snapshot mismatch at generated item 0");
  if (existing_replay.original.soc.g_tile[1].tile.link.data !== 8'b10xz0101) $fatal(1, "snapshot mismatch at generated item 1");
  if (existing_replay.original.soc.g_tile[1].tile.link.pad !== 1'bz) $fatal(1, "snapshot mismatch at generated item 2");
  if (existing_replay.original.soc.g_tile[1].tile.link.req !== 1'b1) $fatal(1, "snapshot mismatch at generated item 3");
  if (existing_replay.original.soc.g_tile[1].tile.u_chain.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_leaf.dut.rst_n !== 1'b1) $fatal(1, "snapshot mismatch at generated item 4");
endtask
