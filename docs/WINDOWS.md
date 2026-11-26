# GB28181 Analyzer · Windows

推荐下载发布页的 `gb28181-analyzer-windows-x64-vX.Y.Z.zip`，完整解压后双击 `GB28181-Analyzer.exe`。压缩包内含分析服务与前端，运行时不需要 Python 或 Node.js。

程序使用 Microsoft Edge WebView2 Runtime 显示独立窗口。Windows 10/11 一般已自带；离线设备可安装微软的 Evergreen Standalone Installer。可执行文件未做代码签名，可对照 Release 的 `SHA256SUMS.txt` 校验下载。

## 浏览器便携模式

解压文件名以 `-browser.zip` 结尾的包，双击 `Start-Analyzer.cmd`。本地服务会打开系统默认浏览器。启动窗口需保持打开，按 Ctrl+C 停止服务。该模式使用浏览器文件选择器导入抓包，运行依赖可在设置页手工输入路径。默认固定在回环端口 8791，端口冲突时可用 `Start-Analyzer.cmd --port 8792`。

从源码构建浏览器包时使用 `scripts/build-windows.ps1 -BrowserOnly`。构建脚本为 ZIP 生成 `.sha256` 校验文件。可用 `python scripts/smoke-windows.py <ZIP> --browser-only --analyze-sample` 验证解包启动和真实抓包分析。执行分析冒烟前需准备 TShark。

## 外部依赖

| 用途 | 需要 | 缺少时的表现 |
| --- | --- | --- |
| 抓包解析与统计 | [Wireshark x64](https://www.wireshark.org/download.html)，勾选 TShark | 无法分析，顶栏提示缺少 TShark |
| 视频重建与预览 | [FFmpeg](https://www.gyan.dev/ffmpeg/builds/)（含 ffmpeg.exe、ffprobe.exe） | 信令与媒体指标仍可用，视频区显示重建失败原因 |
| 本机网卡实时采集 | Npcap（随 Wireshark 安装）与相应权限 | 采集入口不可用，抓包文件分析不受影响 |

安装后在「设置 → 运行依赖」确认五项工具状态；缺少的项目可直接指定路径并点“测试”验证版本，无需重启。

应用默认只监听本机。数据保存在 `%LOCALAPPDATA%\GB28181 Analyzer`，可用 `--data-dir` 改位置。应用自动分配本机端口。关闭主窗口会终止仍在进行的分析，请等待导出完成。

运行日志位于 `%LOCALAPPDATA%\GB28181 Analyzer\logs\analyzer.log`，单文件最多 5 MiB，保留 3 份历史。应用版本变化时会在 `backups` 目录自动备份现有 SQLite 数据库，保留最近 5 份。反馈启动或分析异常时，可一并提供日志和对应任务编号。

工具安装在自定义位置时，可在同一个 PowerShell 窗口设置环境变量，再启动应用。

```powershell
$env:TSHARK_PATH = 'D:\Wireshark\tshark.exe'
$env:FFMPEG_PATH = 'D:\ffmpeg\bin\ffmpeg.exe'
$env:FFPROBE_PATH = 'D:\ffmpeg\bin\ffprobe.exe'
.\GB28181-Analyzer.exe
```

DeepSeek 是可选的联网功能。主动配置并运行后会向配置的模型服务发送分析摘要。Windows 可执行文件未做代码签名。可对照 Release 的 `SHA256SUMS.txt` 校验下载。

设置页的“外部工具路径”可为 TShark、Capinfos、Dumpcap、FFmpeg、FFprobe 指定本机文件。优先级为手动配置 > 环境变量 > PATH。配置保存在数据目录的 tools.json，清空输入或点击“恢复自动探测”即可回到自动探测。

每个工具都可以先点“测试”执行版本探测。桌面版支持“浏览”直接选择 .exe；浏览器模式请粘贴完整路径。工具路径修改默认只允许本机请求，通过反向代理开放设置页时应先配置认证并显式设置 ALLOW_REMOTE_SETTINGS=1。

SQLite 数据库升级时会先备份，再补充新增的可空或带默认值字段。该机制不删除、不改写已有数据，但不等同于完整的 PostgreSQL 迁移方案。


## Native Shell 开发入口

Windows 桌面开发使用 Native Shell 0.7.1。安装该版本的 nsh CLI、项目 Python 依赖并在 frontend 目录运行 npm run build 后，在仓库根目录运行以下命令。

```powershell
.venv/Scripts/python.exe scripts/run-nsh.py
```

启动器通过随机回环端口连接独立分析服务。可用 --data-dir 指定测试数据目录，--nsh 指定 CLI 的完整路径。加 --test 可运行 Windows 原生宿主测试，测试等待 Vue 工作台通过 WebView 桥发出就绪事件。Windows 便携包使用同一 Native Shell 宿主，Rust 启动器负责监督窗口与分析进程。
