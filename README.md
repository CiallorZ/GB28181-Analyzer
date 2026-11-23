# GB28181 Analyzer

适用于 Windows x64 的 GB/T 28181 离线抓包分析工作站。遇到「点播有响应，画面却没有出来」，可以沿同一会话核对信令、媒体和视频重建结果，并导出带证据的报告。

**[下载 v1.1.5 Windows x64 离线单文件 EXE](https://github.com/CiallorZ/gb28181-analyzer/releases/download/v1.1.5/GB28181-Analyzer-v1.1.5-offline-x64.exe)** · [校验和与版本记录](https://github.com/CiallorZ/gb28181-analyzer/releases/tag/v1.1.5)

## 首次打开

1. 双击离线 EXE。首次启动会将内置工具解压到当前用户的本机缓存，后续打开复用缓存。整个过程无需管理员权限。
2. 程序自带 TShark、Capinfos、FFmpeg、FFprobe 和固定版本 WebView2。分析已有抓包和重建视频无需联网或配置 PATH。实时网卡采集另需 Npcap 驱动。
3. 拖入 PCAP、PCAPNG 或 CAP 文件，或先点击「试用示例抓包」。分析完成后从工作台的关键诊断进入证据。

## 从结论查到报文

| 想回答的问题 | 核对位置 |
| --- | --- |
| 点播协商进行到哪一步？ | 在 SIP 时序中选择消息，核对 Call-ID、响应、SDP 地址及端口，再打开关联报文。 |
| 抓包点观察到了哪些媒体？ | 查看 RTP 流、SSRC、码率、抖动及序号缺口。信令成功、捕获媒体、视频可解码是三个独立观察结果。 |
| 能否还原视频？ | 在媒体详情选择流，查看编码参数、重建状态、预览或下载。结果取决于抓包完整性和解码工具。 |
| 两个抓包点看到的结果有何不同？ | 在「双包对比」选择两个已完成任务。先核对对齐置信度，再查差异和未对齐项。[对比方法](docs/COMPARE.md) |
| 如何交接排查结果？ | 从完成任务导出诊断报告，保留会话、流和报文依据。历史任务可在下次启动后继续查看。 |

## 数据和 AI

桌面版默认监听本机，抓包、数据库及分析产物默认位于 Windows 用户目录下的 `%LOCALAPPDATA%\GB28181 Analyzer`。删除任务或清理数据前，请先归档所需报告和视频。

DeepSeek 是可选外部服务。用户自行提供 API Key，环境变量 `DEEPSEEK_API_KEY` 优先于本机设置。通过设置保存的密钥位于本机应用数据目录，勿分享该目录。发送前可查看结构化摘要并确认。规则诊断可离线独立使用，AI 建议需回到原始证据核实。

## 适用边界

未捕获 RTP 只说明当前抓包点和时间窗未观察到对应媒体。TCP 承载流的序号缺口不能直接换算成网络丢包。首 RTP 时间与终端实际出画时间也需分别衡量。完整 RTCP 对时、多跳拓扑和团队数据库见[实施状态](IMPLEMENTATION_STATUS.md)。Windows 便携包未做代码签名，下载后可核对发布页 SHA-256。

## 使用与维护

[Windows 安装与排障](docs/WINDOWS.md) · [架构](ARCHITECTURE.md) · [源码开发和测试](CONTRIBUTING.md) · [验收记录与性能基线](docs/FREEZE_V1_1.md) · [更新记录](CHANGELOG.md) · [MIT 许可证](LICENSE)
