# Linux 解压即用版

便携包内置 Python 3.8、Tk、SSH 依赖和中文字体。解压到任意目录，不需要安装 Python、Tk 或 pip 包，也不需要 root 权限。

```bash
tar -xzf wave_init-1.3.3-linux-x86_64.tar.gz
cd wave_init-linux-x86_64
./start_gui.sh
```

升级到 1.3.3 时请完整解压新包，再运行 `./start_gui.sh --version` 确认版本。1.3.3 增加默认持久化的详细 NPI 日志、环境/版本记录、GUI/SSH 日志与实时调试选项，并保留此前深层 interface、generate、数组和 FSDB 别名修复。便携可执行文件使用内置代码，仅替换外层 Python/Tcl 文件不会更新它。

适用平台：**Linux x86_64、glibc 2.17 或更新版本、可用的图形桌面/X11（含 XWayland）**。请保留整个解压目录，尤其是 `_internal`。ARM、Alpine/musl 不适用本二进制包；源码启动方式仍可使用对应平台的 Python/Tk。

目录可以改名、包含空格，也可以安装为只读目录。GUI 在 Linux 默认选择 `local`，不连接预设服务器。输出目录默认位于当前用户的 `~/wave_init_output/`，SSH 下载缓存位于 `${XDG_CACHE_HOME:-~/.cache}/wave_init/downloads/`。可通过 `WAVE_INIT_OUTPUT_DIR` 修改默认输出父目录。

## Verdi 环境

打开 GUI 或查看已有快照不需要 Verdi。**实际提取波形需要目标设备上已有可用的 Verdi/NPI 和许可证**；本包不包含 Verdi 或许可证，不依赖原开发虚拟机。

使用本设备已有的 EDA 环境设置，例如：

```bash
source /your/site/eda_setup.sh
/where/you/extracted/wave_init-linux-x86_64/start_gui.sh
```

也可以设置本设备自己的 `VERDI_HOME`、`PATH` 和许可证环境，并在 GUI 的“SSH / 高级”中填写 Verdi 可执行路径。不要在其他设备上加载开发 VM 专用的 `tests/env.sh`。

## 检查与命令行

```bash
./start_gui.sh --check          # 检查内置运行时、Tk、显示环境、资源和 SSH 依赖
./start_gui.sh --report examples/assign/snapshot.json
./wave_init --cli --help       # 同一便携运行时提供 CLI，不依赖系统 Python
```

纯 SSH 终端没有图形显示时，请在 Linux 桌面启动或使用可用的 X11 转发。`--check` 会明确报告显示环境缺失；不会静默开启后台不可见窗口。

提取命令添加 `--debug`，或勾选 GUI 高级页的“实时显示详细日志”，可在界面看到逐层 interface 绑定和 FSDB 路径查询。即使未勾选，输出目录也会默认保存完整 `npi_trace.log`、`wave_init.log`、`runtime.json`、`verdi.log` 和原始 NPI 记录。SSH 会自动下载日志，连接失败时本机缓存仍保存 `gui.log`。其他设备出现问题时，可直接提供本次报告及这些日志；详见 [README 日志说明](README.md#其他设备出错时的日志)。

## 源码目录启动

源码目录也提供 `start_gui.sh`：没有便携可执行文件时，会自动寻找支持 Tk 的 Python 3.8+。可以显式指定解释器：

```bash
WAVE_INIT_PYTHON=/your/python3.8 bash /path/to/wave_init/start_gui.sh
```

## 重新打包

使用 Linux x86_64 / glibc 2.17 / Python 3.8 构建机，在独立虚拟环境安装 PyInstaller 6.18.0、Paramiko，然后执行：

```bash
python tools/build_linux_bundle.py
```

构建脚本生成 tar.gz、SHA-256、运行时依赖锁文件、原生库 glibc 版本审计、组件许可证和 `bundle_info.json`。构建要求安装 WenQuanYi Zen Hei 字体；许可证随包保留。便携包遵循 [PyInstaller 的 Linux 兼容性构建说明](https://pyinstaller.org/en/stable/usage.html#making-gnu-linux-apps-forward-compatible)，不打包 glibc 或商业 EDA 软件。
