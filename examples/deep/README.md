# 深层 interface 例子

`tb.sv` 使用递归深度 8，最底层 DUT 位于 13 层模块实例、23 段完整层次路径中：

```text
deep_top.soc.g_tile[1].tile.u_chain.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_next.u_child.g_leaf.dut
```

Interface、DUT、包装层分别位于 `tests/fixtures/split_interface/bus.sv`、`dut.sv` 和 `tests/fixtures/deep_interface/hierarchy.sv`。`g_tile[0]` / `[1]` 的输入值不同，用于检查层次隔离。

`tb_snapshot.sv` 是 5 ns 的独立 assign 快照。`snapshot.svh` 是 1 ns 快照，目标已重映射到 `existing_replay.original`；`existing_force_release.sv` 在 6 ns 调用它，再检查 release 后 8 ns 的原始驱动。

从仓库根目录、在已有 VCS/Verdi PLI 环境中运行：

```bash
vcs -full64 -sverilog -debug_access+all -f examples/deep/design.f \
  examples/deep/tb_snapshot.sv -top wave_init_tb -o /tmp/deep_assign_simv
/tmp/deep_assign_simv

vcs -full64 -sverilog -debug_access+all -f examples/deep/design.f \
  +incdir+examples/deep examples/deep/existing_force_release.sv \
  -top existing_replay -P "$VERDI_HOME/share/PLI/VCS/LINUX64/novas.tab" \
  "$VERDI_HOME/share/PLI/VCS/LINUX64/pli.a" -o /tmp/deep_release_simv
/tmp/deep_release_simv
```

完整自动回归入口为 `tests/run_deep_interfaces.py`；本例的原始测试日志与结果见 `validation/deep_interface_results.json`。
