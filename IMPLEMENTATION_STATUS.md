# 实施状态

基线为远端 `main` 的 v1.1.0（`08c497a`），并包含本轮封版候选的回归结论。定位为 Windows x64 单机离线分析。

| 模块 | 当前能力 | 边界 |
|---|---|---|
| 抓包导入与任务 | PCAP/PCAPNG、样例导入、续传、受限的本机网卡采集、任务取消和重跑 | 支持 Web Crypto 时，大于 32 MiB 的文件走 8 MiB 分片。分片清单上限 16 GiB，普通上传默认上限 2 GiB。这些是接口限制 |
| SIP / SDP / 会话 | SIP 事务、点播会话、SDP 媒体地址与传输协商、信令状态与媒体状态分开记录 | 跨抓包点改写标识或者采样不足时，可能无法关联 |
| RTP / RTCP | UDP 与 TCP 载荷、码率、抖动、序号缺口、接收报告块和抓包中可提取的 RTT | RTCP 按需读取原包；完整 SR 时间线与 SR/RR 时钟关联仍待实现 |
| PS / ES / 视频 | PS 解封装、H.264/H.265 参数、离线 MP4 重建、预览和下载 | 依赖码流完整性与 FFmpeg。RTP 首包耗时、关键帧统计和终端首帧时间各有独立口径 |
| 工作台与证据 | 深浅主题、SIP 回放、趋势、规则证据、原始报文与 HEX、端点关系清单 | UDP 可按捕获时间缩放联动。TCP 流内时间与视频帧精确映射、可交互拓扑画布仍待实现 |
| 诊断、AI 和对比 | 21 条诊断规则、证据等级、双任务快照、Markdown/JSON/HTML/CSV 任务报告 | 双点实采在隔离环境验证。AI 使用可选的外部服务，发送摘要前确认 |
| 单机与部署 | Windows 便携包、本机 SQLite、Docker Compose 构建配置及 CI | PostgreSQL 迁移、多人账户、Windows 代码签名未交付；Compose 实际运行需 Docker daemon |

[发布流程与实测记录](docs/RELEASE.md) · [双包对比](docs/COMPARE.md) · [历史审计](docs/ROADMAP.md)
