# GB28181 Analyzer · Windows

适用于 Windows x64。ZIP 内含分析服务与前端，运行时无需安装 Python 或 Node.js。

1. 安装 [Wireshark x64](https://www.wireshark.org/download.html)，在安装选项里勾选 **TShark**。读取已有抓包可以跳过 Npcap。
2. 如需重建和播放画面，请安装 [FFmpeg 的 Windows 构建](https://ffmpeg.org/download.html#build-windows)，将包含 `ffmpeg.exe` 和 `ffprobe.exe` 的目录加入 `PATH`。
3. 完整解压 ZIP，双击 `GB28181-Analyzer.exe`。程序通过 Microsoft Edge WebView2 Runtime 显示独立工作台。请先安装该运行时，离线设备可使用微软的 Evergreen Standalone Installer。关闭主窗口即可退出。
4. 在工作台选择抓包或点击「试用示例抓包」。打开「设置」可检查外部工具是否已被识别。安装依赖后请重新启动应用。

应用默认只监听本机。数据保存在 `%LOCALAPPDATA%\GB28181 Analyzer`，可用 `--data-dir` 改位置。应用自动分配本机端口。关闭主窗口会终止仍在进行的分析，请等待导出完成。

工具安装在自定义位置时，可在同一个 PowerShell 窗口设置环境变量，再启动应用。

```powershell
$env:TSHARK_PATH = 'D:\Wireshark\tshark.exe'
$env:FFMPEG_PATH = 'D:\ffmpeg\bin\ffmpeg.exe'
$env:FFPROBE_PATH = 'D:\ffmpeg\bin\ffprobe.exe'
.\GB28181-Analyzer.exe
```

DeepSeek 是可选的联网功能。主动配置并运行后会向配置的模型服务发送分析摘要。Windows 可执行文件未做代码签名。可对照 Release 的 `SHA256SUMS.txt` 校验下载。
