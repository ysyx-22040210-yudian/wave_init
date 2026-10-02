# wave_init

基于 **Verdi NPI**，输入 FSDB、对应的 KDB++、模块实例层次和时间，提取模块边界的 input/inout 快照。支持 SystemVerilog interface/modport，并同时输出 JSON、CSV 和两种 SystemVerilog 回放文件。

运行环境：Linux、Python 3.6+、可用 Verdi 及许可证。Python 运行部分仅使用标准库；运行生成的 testbench 另需 VCS、原始 RTL/package/filelist。开发验证环境为 Verdi/VCS O-2018.09-SP2。

**GUI：Python 3.8+ / Tkinter**，支持 Linux 本机执行和 Windows/Linux 通过 SSH 调用 Verdi 服务器。源码 GUI 本机模式仅使用标准库；源码 SSH 模式另外需要 Paramiko。当前版本为 1.3.0。

## 其他 Linux 设备直接启动

使用 `dist/wave_init-1.3.0-linux-x86_64.tar.gz`：内置 Python 3.8、Tk、SSH 依赖及中文字体，不需要安装 Python/Tk，也不需要开发 VM 或 root 权限。

```bash
tar -xzf wave_init-1.3.0-linux-x86_64.tar.gz
cd wave_init-linux-x86_64
./start_gui.sh
```

适用于 Linux x86_64、glibc 2.17+ 和可用图形桌面。完整部署要求、环境自检和源码启动方式见 [LINUX.md](LINUX.md)。界面启动及报告查看不需要 Verdi；实际提取需要该设备自己的 Verdi/NPI 与许可证。

## GUI 使用

在工程目录运行：

```bash
python wave_init_gui.py
```

本次 Windows 环境可直接启动；在虚拟机的**桌面终端**运行：

```bash
cd /root/wave_init
source tests/env.sh
python3.8 wave_init_gui.py
```

虚拟机已在 Python 3.8.13 / Tk 8.5.13 下通过界面与真实 Verdi 提取验证。无桌面的 SSH 终端可使用本机 GUI 的 `ssh` 模式；Tk 窗口需要可用的桌面 / DISPLAY。

1. 在“提取设置”选择 `ssh`（远端执行）或 `local`（Linux 本机执行）。
2. Linux 默认使用 `local`，无需 SSH。在 `ssh` 模式下通过“SSH / 高级”填写自己的主机、用户、远端工具目录和可选环境脚本。程序不预设开发 VM 的地址/目录。密码只保留在当前 GUI 内存中；也支持 SSH agent / 已有密钥。
3. 浏览并选择 FSDB、KDB / simv.daidir，填写完整模块实例路径、采样数值和单位。`ssh` 模式的“浏览”打开 SFTP 文件选择器，所有输入路径均为**虚拟机路径**；不上传 FSDB/KDB。
4. 选择新的输出目录，或点击“生成新的输出目录名”；点击“提取快照并生成 SV”。后台执行不阻塞界面，取消会通知提取进程清理 Verdi 子进程。
5. 在结果页筛选信号；选择一行可查看完整 `0/1/x/z`、实际波形路径、方向依据、类型及状态。“SV 预览”展示 `tb_snapshot.sv` 的 `assign` 驱动，也可切换至 `snapshot.svh`。“诊断”保留未知方向、缺失值和 SV 不完整信息。

SSH 完成后自动将 JSON、CSV、SV 和日志取回当前用户的缓存目录：Linux 为 `${XDG_CACHE_HOME:-~/.cache}/wave_init/downloads/`，Windows 为 `%LOCALAPPDATA%/wave_init/downloads/`；原始报告也留在远端输出目录。GUI 的默认本机输出父目录为 `~/wave_init_output/`，可用 `WAVE_INIT_OUTPUT_DIR` 覆盖，安装目录可保持只读。“打开结果目录”打开当前本机报告的位置。读取状态不完整的任务仍能查看报告，GUI 会显示“部分完成”，不会把它标为成功。

通过“文件 → 保存配置”保存路径、层次、时间、SSH 主机及高级参数，**不保存密码**。可以打开 [examples/gui_vm.json](examples/gui_vm.json) 使用本次 VM 综合测试波形；首次填写密码，重复提取前生成新的输出目录名。高级项包括 Verdi 路径、超时、SVH 层次/Interface 重映射和未知方向成员的显式驱动。

无需连接 Verdi 也可查看已有快照：

```bash
python wave_init_gui.py --report examples/assign/snapshot.json
```

若 SSH 模式提示缺少依赖，在运行 GUI 的 Python 环境执行 `python -m pip install paramiko`。首次连接服务器先通过系统 `ssh` 校验并保存主机密钥；GUI 沿用 `known_hosts`，不会自动接受陌生主机。

宽信号的表格列会缩略显示，选中行的详情与导出文件保留完整值。一次筛选超过 5000 项时表格显示前 5000 项并明确提示，可缩小筛选范围；SV 预览超过 1 MiB 时提示截断，完整文件仍在输出目录。

[GUI 截图](validation/gui_preview.png) · [GUI 验证记录](validation/gui_results.json)

## 命令行使用

```bash
export VERDI_HOME=/path/to/verdi
export PATH="$VERDI_HOME/bin:$PATH"
export SNPSLMD_LICENSE_FILE=port@license-server

python3 wave_init.py \
  --fsdb /path/to/waves.fsdb \
  --kdb /path/to/simv.daidir/kdb.elab++ \
  --scope testbench.u_dut \
  --time 125.5ns \
  --out out/snapshot_125ns
```

`--kdb` 也接受包含 `kdb.elab++` 的 `simv.daidir`。KDB++ 是数据库目录，应保留整个目录结构。工具只查询数据库；启动 Verdi 产生的日志及配置位于输出目录的独立运行子目录。

`--scope` 是完整的**实例路径**，不是 module 定义名。带方括号、空格或转义标识符的路径须在 shell 中引用，例如 `--scope 'tb.gen[2].u_dut'`。每次运行使用新的输出目录，防止误读上一次结果。

时间必须带单位：`fs`、`ps`、`ns`、`us`、`ms`、`s`，或整数 `ticks`。按 FSDB 文件自身精度精确换算；不做浮点舍入。指定时刻取最后一次已经发生的值变化，包括该时刻的最后一次记录。全局越界和不足一个 tick 的时间直接报错。

## 结果

| 文件 | 内容 |
|---|---|
| `snapshot.json` | 所有选中信号、方向依据、真实波形路径、类型/维度、四态值、时间和生成诊断 |
| `snapshot.csv` | 与 JSON 相同的信号行；`value_bin` 按文本列导入，保留前导零 |
| `snapshot.svh` | 现有 testbench 可 include 的 apply/release/check 任务 |
| `tb_snapshot.sv` | 独立 DUT testbench，全部已采样 input/inout 用 `assign` 驱动，含参数和 interface 连接 |
| `run_vcs.sh` | 使用原始 RTL filelist 编译、运行独立 testbench |
| `README.txt` | 本次结果的接入说明 |
| `verdi.log`、`npi_*/records.jsonl` | Vendor 日志及原始 NPI 查询记录 |

JSON 的 `signals` 是目标模块边界快照；`dependencies` 是生成独立 interface 实例所需的构造端口采样，不混入选中的 input/inout 集合。`ports` 还保留输出端口的连接元数据，用于构建完整 testbench。

`value_bin` 是保留 `0/1/x/z` 的无损二进制字符串。未找到或不可信的数据为 `null`，不能等同于真实的 `x`。`status` 区分 `ok`、`not_dumped`、`no_initial_value`、`dump_off`、`width_mismatch`、`unsupported_type`、`read_error`。

返回码：`0` 表示所需值和 SV 均成功生成；`2` 表示有不完整项，但报告已保存；`1` 表示参数、时间范围、数据库或 Verdi 运行失败；`130` 表示响应 GUI 的取消请求。`values_complete` 与 `directions_complete` 分别表示值和方向是否完整。按用户选择保留的无 modport 成员可在方向未知时返回 `0`。

## Interface 方向

- 按 `npiPort → npiLowConn → npiActual` 找到实际 interface/modport，再读取成员 `npiDirection`。`mst`、`slv` 等名称没有内置方向假设。
- 支持 module 声明处选择 modport、实例连接处选择 modport、跨层传递、interface 数组及多个端口共享一个 interface。
- modport 的 output 不进入快照；input/inout 按其绑定的真实对象采样。别名、固定切片和拼接通过 `npiExpr` 处理。
- 没有 modport 时提取静态数据成员并标记 `unknown`。`ref` 单独记录，不伪装成 input/inout。
- 默认 SV 只驱动已成功采样的 input/inout：独立 `tb_snapshot.sv` 使用 `assign`，现有 TB 的 `snapshot.svh` 使用 `force/release`。`--force-unknown` 才会额外驱动无 modport 的未知方向成员；ref 保持仅报告。

## 两种 SV 用法

现有 testbench：在 module 内 include `snapshot.svh`，在用户选择的仿真时间调用：

```systemverilog
initial begin
  #100ns;
  apply_snapshot();
  #1ps;
  check_snapshot();
  // ...需要保持快照的操作...
  release_snapshot();
end
```

任务使用常量 `force/release`；include 本身不触发驱动。生成文件使用原设计的实际层次路径。迁移到另一个实例时显式提供：

```bash
--sv-target new_tb.dut --sv-interface-map bus=new_tb.link
```

`--sv-interface-map` 可重复，键是目标模块的 interface 端口名。Interface 数组映射到实际数组基路径。共享同一个实际 interface 的映射必须一致。

独立 testbench：

`tb_snapshot.sv` 为每个已成功采样的 input/inout 生成模块级常量连续赋值。普通信号保留 RTL 端口名，interface 按 modport 输入方向驱动实际成员；output 仅连接，不添加快照驱动。例如：

```systemverilog
wire [7:0] a;
// ...interface 实例、其他端口声明...
my_dut dut (.a(a), .bus(bus));

assign a = 8'b10100101;
assign bus.req = 1'b1;
assign bus.data = 8'b10xz0101;
```

位宽、前导零以及 `x/z` 均保留；数组逐元素赋值，非 packed 结构体逐字段赋值，别名/切片映射到真实成员。共享 interface 的多个端口保持同一实例，相同目标去重，每条赋值上方注释列出对应的原始端口路径。Interface 构造端口（例如 `input clk`）通过连接线的 `assign` 驱动。DUT 实例名及辅助名字会避开与 RTL 端口的冲突。

```bash
bash out/snapshot_125ns/run_vcs.sh /absolute/path/design.f
```

filelist 及其 include 路径须可从独立构建目录访问，建议使用绝对路径。脚本接受后续 VCS 参数，每次创建独立构建目录。生成顶层 `wave_init_tb` 的 `assign` 从仿真开始持续生效，1 ps 后检查 DUT 边界上的四态值，打印 `WAVE_INIT_SNAPSHOT_PASS`，2 ps 结束。需要后续变化的时钟、复位或激励时，先替换对应的常量 `assign`，再添加激励。

这里只恢复边界值，内部寄存器和存储器状态不在快照中。inout 保存 FSDB 的解析后总线值，无法由该值重建各个驱动源；连续赋值会参与总线解析，若 DUT 自身驱动了相反值，结果可能变成 `x`，生成的四态检查会报错。Interface 内部若已有同一变量的驱动，需要按原始 RTL 处理驱动冲突。现有 TB 的 `release` 遵循 SystemVerilog 语义：net 重新服从驱动，变量可能保持强制值直到下一次过程赋值。

缺失数据或无法重建的连接会写入诊断，并生成主动 `$fatal` 的任务/顶层，避免静默使用残缺快照。`sv.complete` 表示生成器完成了受支持的重建，不等同于新设计已通过 VCS 编译。

## 支持边界

支持静态 RTL 的标量、任意位宽四态向量、整数、packed 数组/结构体/union、固定 unpacked 数组、具有 package typedef 的 unpacked 结构体，以及可由 KDB 解析的静态 interface/modport。数组按展开后的范围和元素解析。Union 成员重叠，采样时不会把所有视图重复拼接。

遇到动态/关联数组、队列、虚拟 interface、class、real/string、时钟块或任务形式的 modport 成员，以及暂不支持的表达式，会明确报告，不能用猜测值代替。独立 testbench 对无法重建的类型参数、不可访问的非 packed typedef 或不支持的构造连接也报告不完整。KDB 与 FSDB 应来自对应仿真；工具检查可解析的路径和位宽，无法仅靠名称证明两个数据库完全同源。

## 开发与验证

```bash
python3 -m unittest discover -s tests -p test_unit.py -v
source tests/env.sh              # 本次虚拟机的工具路径；其他服务器请使用自己的配置
bash tests/build_fixture.sh
python3 tests/run_integration.py
```

使用 VM 中原有 interface 样例及现有 PicoRV32 RTL 做工程抽查：

```bash
python3 tests/run_vm_datasets.py \
  --picorv32 /path/to/picorv32.v \
  --interface-fixture /path/to/interface_port_root
```

`tests/run_integration.py` 在 `build/acceptance_*` 保存逐项结果、生成报告、VCS 编译和仿真日志。测试直接验证期望端口集合与四态值，并编译运行两种 SV，不以文件存在作为通过依据。

本次验证结果和示例见 [validation/README.md](validation/README.md)。稀疏 FSDB 测试会使用 g++ 编译 NPI Writer 辅助程序；主工具本身不依赖 C++ 编译。

GUI 测试（需要 Tk 显示环境；无桌面 Linux 可使用 Xvfb）：

```bash
python3.8 -m unittest discover -s tests -p test_gui.py -v
python3.8 tests/run_gui_integration.py   # 已 source Verdi 环境的 Linux 桌面
```

虚拟机上的无桌面检查应先启动系统 Xvfb，再为子进程加载 Verdi 环境，避免选中 Verdi 自带的旧版 Xvfb：

```bash
xvfb-run -a bash -c 'source tests/env.sh; python3.8 -m unittest discover -s tests -p test_gui.py -v'
xvfb-run -a bash -c 'source tests/env.sh; python3.8 tests/run_gui_integration.py'
```

Windows 到 VM 的 GUI 联调入口为 `tests/run_gui_integration.py --ssh` 和 `tests/run_gui_cancel_ssh.py`。测试密码通过环境变量 `WAVE_INIT_SSH_PASSWORD` 注入；GUI 程序本身由密码输入框或 SSH 密钥进行认证。

可选开发辅助 `tools/vm.py` 使用 Paramiko 同步到测试 VM；密码只从 `WAVE_INIT_SSH_PASSWORD` 环境变量读取，不写入文件。首次使用前需用正常 SSH 验证并保存服务器 host key。该辅助脚本不是工具运行依赖。

实现入口：`wave_init.py`、`wave_init_gui.py`；NPI 后端：`backend/snapshot.tcl`；结果处理：`waveinit/cli.py`；SV 生成：`waveinit/sv.py`；Tk 界面与后台任务：`waveinit/gui.py`、`waveinit/gui_runner.py`。
