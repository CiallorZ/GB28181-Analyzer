# 实施状态

基线为远端 `main` 的 v1.3.0（`3a4ea35`），并包含后续准确性修复。定位为 Windows x64 单机离线分析。

| 模块 | 当前能力 | 边界 |
|---|---|---|
| 抓包导入与任务 | PCAP/PCAPNG、样例导入、续传、受限的本机网卡采集、任务取消和重跑 | 支持 Web Crypto 时，大于 32 MiB 的文件走 8 MiB 分片。普通上传与分片清单共用 `MAX_UPLOAD_MB` 限制（默认 2 GiB），未完成分片也计入磁盘用量 |
| SIP / SDP / 会话 | SIP 事务、点播会话、SDP 媒体地址与传输协商、信令状态与媒体状态分开记录 | 跨抓包点改写标识或者采样不足时，可能无法关联 |
| RTP / RTCP | UDP 与 TCP 载荷、码率、抖动、序号缺口；自研 RTCP SR/RR 解析，按 LSR/DLSR 计算 RTT 与对端丢包/抖动，并接入 MED-002/003/009；RTCP 已从 RTP 统计中剔除，TCP 多 SSRC 分别建流 | SR 的 NTP 与 RTP 时间轴锚定只用于 RTT 与两端时钟差，尚未把整条时间线换算成墙钟 |
| PS / ES / 视频 | PS 解封装、H.264/H.265 参数、关键帧时间与 GOP 间隔（MED-010）、离线 MP4 重建、预览和下载 | 依赖码流完整性与 FFmpeg。首关键帧耗时按关键帧偏移估算，不等于播放器实际显示时间；取样窗口外的 GOP 不在统计内 |
| 工作台与证据 | 深浅主题、SIP 回放、趋势、规则证据、原始报文与 HEX、端点关系清单 | UDP 可按捕获时间缩放联动。TCP 流内时间与视频帧精确映射、可交互拓扑画布仍待实现 |
| 依赖与升级 | 工具路径手动覆盖、版本探测、设置分区、滚动日志、升级前备份、SQLite 增量补列 | 没有账号体系；数据库迁移仍以单机增量补列为主，PostgreSQL/多人部署未验证 |
| 诊断、AI 和对比 | 23 条诊断规则、证据等级、双任务快照、Markdown/JSON/HTML/CSV 任务报告 | 双点实采在隔离环境验证。AI 使用可选的外部服务，发送摘要前确认 |
| 单机与部署 | Windows 便携包、本机 SQLite、Docker Compose 构建配置及 CI（含桌面壳 cargo check） | PostgreSQL 迁移、多人账户、Windows 代码签名未交付；Compose 实际运行需 Docker daemon |

[发布流程与实测记录](docs/RELEASE.md) · [双包对比](docs/COMPARE.md) · [历史审计](docs/ROADMAP.md) · [2026-11-28 全面评估](docs/QUALITY-REVIEW-2026-11-28.md)
