# 验证记录

日期：2026-10-02。验证环境：`192.168.31.116`，CentOS 7、Python 3.6.8、Verdi/VCS O-2018.09-SP2。交付源码位于 `D:\wave_init`，VM 副本位于 `/root/wave_init`。

当前版本 **1.3.0** 提供内置 Python 3.8 / Tk 的 Linux x86_64 便携包。[便携包验证记录](linux_portable_results.json) 保存归档 SHA-256、跨 Linux 启动结果和打包后的 GUI 实测；[构建信息](linux_bundle_info.json) 保存运行时版本、原生库审计和交付源码校验值。

版本 **1.2.0** 添加 Python 3.8 / Tkinter GUI。[GUI 验证记录](gui_results.json) 单独记录该版的本机/SSH 真实提取、SFTP 浏览、远端取消和界面响应；[界面截图](gui_preview.png) 来自实际生成的结果。

下方核心功能记录对应 **1.1.0**：独立 `tb_snapshot.sv` 改用常量 `assign`，普通连接保留 RTL 端口名；现有 TB 的 `snapshot.svh` 提供可选的 force/release 任务。版本 1.2.0 的 CLI 取消机制另经过进程组清理测试，并复测普通端口及现有 TB 的 force/release 接入。

[results.json](results.json) 汇总 1.1.0 每个测试组的最后结果和当时核心源码 SHA-256。[runs](runs/) 保留原始各轮结果，包括修正前的测试失败记录；最终各组均通过。测试检查和样例生成都实际调用了 VM 上的 NPI/VCS。

## Linux 便携包验证（1.3.0）

- Python 3.8.13 / Tk 8.5.13 下 20 项单元与 GUI 测试全部通过、无跳过。新增检查覆盖打包后的 CLI 调用方式、外部 EDA 库环境还原、用户输出/缓存目录和相对路径/符号链接启动。
- CentOS 7 / glibc 2.17：从其他工作目录启动内置运行时，构建完整 GUI，加载 7 行 assign 示例，中文字体及 SSH 依赖检查通过。
- Ubuntu Base 22.04.5 / glibc 2.35：在独立 mount/PID namespace 内以 UID 65534 运行，环境未安装 Python、Tk、Verdi；安装目录只读且路径包含空格。完整 GUI、中文字体、示例和 CLI 版本检查通过。此项验证使用 CentOS 7 的宿主内核，不代表独立 Ubuntu 虚拟机验证。
- 打包后的 GUI 原生可执行文件：通过实际“提取快照并生成 SV”按钮调用内置 CLI 子进程和真实 Verdi，16 项四态值全部匹配已验证样例，表格及 assign 预览正确；查询期间窗口持续响应。证据见 [GUI 运行结果](runs/frozen_gui_local.json)。
- 移动后的只读便携目录：实际 NPI 提取 16 项值，生成的 assign testbench 经 VCS 编译、运行通过。证据见 [跨 Linux 结果](runs/linux_portable_acceptance.json)、[VCS 日志](runs/linux_portable_vcs.log)。
- 76 个 ELF 文件审计，最高要求为 GLIBC 2.17；归档内保留依赖锁文件和组件许可证。下载回本机后的归档 SHA-256、内置源码与工作区源码校验均一致。

交付包：[wave_init-1.3.0-linux-x86_64.tar.gz](../dist/wave_init-1.3.0-linux-x86_64.tar.gz)。启动方式与目标设备要求见 [LINUX.md](../LINUX.md)。

## GUI 追加验证（1.2.0）

- Python 3.8.13 / Tk 8.5.13：15 项测试通过、无跳过，包含原有 7 项单元测试，以及配置不含密码、字面参数传递、缺失报告、部分结果展示、四态值详情和取消时清理进程组。
- 通过 Tk 的“提取”按钮调用真实 Verdi：VM 本机与 Windows SSH 两种模式均取得 16 项预期信号及 assign SV；查询期间 Tk 定时回调持续执行。
- Windows SSH 场景同时验证 SFTP 文件选择器和自动取回报告。
- 通过 GUI“取消”按钮停止刻意构造的远端慢进程：返回码 130，父/子两个进程均停止，约 0.34 秒确认取消。
- CLI 的普通端口/综合类型和现有 TB force/release 两组回归再次通过 VCS 验证。

该版核心文件 SHA-256、运行时版本及每项原始证据路径见 [gui_results.json](gui_results.json)。Windows GUI 联调使用 Python 3.11.5 / Tk 8.6.12；要求的 Python 3.8 兼容性由 VM 的实际 GUI 运行覆盖。

## 核心功能验收（1.1.0）

- 7 个单元测试，Windows 与 VM 的 Python 均通过。
- 10 个功能测试组，覆盖表如下。
- 3 个工程场景：现有 `interface_port_root` 的 `u_src`（5 项）、`u_sink`（3 项）；原有 PicoRV32 RTL 重新生成波形后的 DUT（9 项输入、26 个参数）。三者生成的独立 testbench 均经 VCS 编译、运行并通过四态比较。

| 测试组 | 检查内容 |
|---|---|
| `test_plain_and_shapes` | 精确端口集合、input/inout、升序范围、signed、二维数组、packed 结构体、130 位含 X/Z 总线；独立 TB |
| `test_modports_and_generics` | mst/slv 方向、连接处选择 modport、跨层传递、无 modport 默认不驱动与显式启用；独立 TB |
| `test_interface_array_and_aliases` | interface 数组元素区分、别名切片、拼接、实际波形路径；独立 TB |
| `test_time_and_xz` | 零点、变化前/当时/之后、ticks、X/Z、低于精度的时间、越界、无效层次 |
| `test_dump_gaps_and_missing` | dump-off 起止边界、缺失信号、延迟开始 dump 的全局时间范围 |
| `test_existing_include_and_release` | 原 testbench 接入、层次重映射、interface 映射、force 生效、release 恢复与后续驱动 |
| `test_parameters_struct_union_shared_interface` | 非默认参数、共享 interface、接口成员数组、unpacked 结构体、packed union、转义标识符；独立 TB |
| `test_sparse_fsdb_and_glitches` | 用 NPI Writer 构造单信号无初值与位宽不一致；真实 FSDB 在同一时间戳保留 3 次变化，提取最后一次 |
| `test_partial_sv_parameter_diagnostic` | 普通取值仍完整时，不支持的 string 参数使独立 TB 明确标为不完整；现有 TB 快照仍有效 |
| `test_constant_assign_connections` | 明确的 `input var`、同名普通连接、辅助名字与端口冲突、interface 构造端口、inout；生成内容使用 assign，独立观察器验证 DUT 输入与组合输出持续 20 ns 正确，output 未被误驱动 |

当前版本回归日志留在 VM 的 `/root/wave_init/build/acceptance_zdq54owv` 和 `/root/wave_init/build/acceptance_u1lawfik`，各组的具体证据路径见汇总 JSON。工程测试日志在 `/root/wave_init/build/datasets_atcdiji6`。

## 示例

- [assign 示例](../examples/assign/tb_snapshot.sv)：包含 `assign a = 8'b10xz0101;`、interface 输入成员及对应的 DUT 连接；[20 ns 持续驱动验证日志](../examples/assign/hold_validation.log)。
- [综合类型快照 JSON](../examples/snapshot/snapshot.json)、[CSV](../examples/snapshot/snapshot.csv)、[现有 TB 任务](../examples/snapshot/snapshot.svh)、[独立 TB](../examples/snapshot/tb_snapshot.sv)、[VCS 日志](../examples/snapshot/validation.log)。
- [PicoRV32 快照](../examples/picorv32/snapshot.json)、[独立 TB](../examples/picorv32/tb_snapshot.sv)、[VCS 日志](../examples/picorv32/validation.log)。

测试期间发现原有香山 FSDB 未完成且缺失对应锁文件，Verdi 拒绝读取，因此没有把它算作通过的工程样例；改用现有 PicoRV32 RTL 生成新的配套 FSDB/KDB 验证。

SV 生成结果不代表任意未来设计自动通过编译；新设计应使用其原始 RTL、package、filelist 做接入验证。具体支持范围和不完整结果处理见主 [README](../README.md)。
