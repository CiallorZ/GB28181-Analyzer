# v1.1.x 产品封版验收报告

- 验收日：2026-11-24
- 审计基线：远端 main `08c497a`，公开版本 v1.1.0。封版候选为本轮补丁。Windows 为 x64，使用独立数据目录。
- 范围：PCAP/PCAPNG 导入、单机分析、历史任务、诊断与证据、视频预览、双包对比和报告导出。
- 建议：**修复版 Go（Windows 单机）**。公开 v1.1.0 应由包含清理修复的下一补丁替代。正式交付时以补丁标签重新构建和复验 ZIP。

## 问题清单

| 等级与状态 | 源码与复现条件 | 影响 | 修复或后续验证 |
|---|---|---|---|
| P0 已修复 · 清理活动任务 | [retention.py](../backend/app/services/retention.py)、[tasks.py](../backend/app/api/tasks.py)。预留任务分析槽，触发数量、天数、磁盘预算或手动全量清理 | 清理可删除活动任务的源文件和媒体产物 | 文件清理与任务预留使用同一把锁，清理前重读状态，启动时在锁内确认源文件。四种策略的回归测试从失败转为通过，并确认普通旧任务仍可清理 |
| P1 已修复 · 普通上传取消残留 | [tasks.py](../backend/app/api/tasks.py)。写入首段后注入 `asyncio.CancelledError` | 未注册文件占用磁盘，重试会另建文件 | 取消时回收半成品后传播原异常。测试确认目录和数据库均无新增内容；普通 ENOSPC 保留现有错误码 |
| P1 已修复 · 分片写满与续传 | [intake.py](../backend/app/api/intake.py)。先保存分片 0，再在分片 1 的临时文件写入时注入 ENOSPC | 用户收到通用失败，临时文件残留 | 返回 507 并清掉失败片段，保留已确认块。回归验证释放空间后能续传、校验和合并 |
| P1 待验证 · 更大、更多路的现场抓包 | [analyzer.py](../backend/app/services/analyzer.py)、[rebuild.py](../backend/app/services/rebuild.py)。持续重放超过 228 MiB 或包含更长、多路高码率视频的样本 | 本轮已记录峰值 2,614.25 MiB；更大负载下的进程稳定性和吞吐缺少数据 | 在目标 Windows 低内存机型复测并定位峰值阶段。历史曾有一次原因不明的断连，本轮长任务完成 |
| P1 待验证 · 现场异构双点对比 | [comparison.py](../backend/app/services/comparison.py)。同一次现场会话在两个独立接口捕获，且中间改写 Call-ID 或 SSRC | 可能产生更多未对齐项；本轮现场包只能验证一个采集接口 | 采集带中间改写的独立双包，核对精确、推断和未对齐项目；既有双点实采来自隔离环境 |
| P2 未实现 · TCP 到视频帧的精确时间映射 | [MetricScope.vue](../frontend/src/components/MetricScope.vue)、[rtp_analyzer.py](../backend/app/parsers/rtp_analyzer.py)、[rebuild.py](../backend/app/services/rebuild.py)。将 TCP 业务选区定位到可解码画面 | 目前可查 RTP 首包、流内趋势与编码结构，视频需独立定位 | 保存可追溯包号、媒体时间及输出 PTS，验证乱序、B 帧及多段时间戳。终端实际显示时间需客户端侧观测 |

## 协议与 21 条诊断规则

- SIP/SDP：复核 [sip_parser.py](../backend/app/parsers/sip_parser.py) 和 [session_builder.py](../backend/app/parsers/session_builder.py)，测试覆盖会话归并、应答、结束、SDP 字段、协商异常、关联歧义和 SSRC 零值/未知值。
- RTP：复核 [rtp_analyzer.py](../backend/app/parsers/rtp_analyzer.py) 和 TCP 分段路径。回归覆盖 UDP、RFC4571、序号回绕与异常，现场 TCP 观察结果继续使用「序号缺口」口径。
- RTCP：复核 [evidence.py](../backend/app/api/evidence.py)，自动化验证多接收报告块、区间丢包字段及缺失 RTT。真实 SR/RR 成对数据、RTT 与外部参考值交叉核对列为待验证。
- PS/ES 与重建：回归通过 PS/PES 解封装、H.264/H.265 参数和 FFmpeg 重建。现场包 73,049 帧、8 个会话、28 条 TCP 流，Windows 工作台实播分辨率 1280 × 724。此前相同现场包的 28 份视频整段解码全部通过。
- [diagnosis.py](../backend/app/services/diagnosis.py) 的 21 项规则在测试集中均有规则级检查。SIP-001–008 涵盖超时、响应、重传、孤立响应、结构和会话结束。SDP-001–004 涵盖地址、协商、SSRC 和结构。MED-001–008 涵盖缺流、序号缺口、抖动、静默、时间戳、码率、BYE 后传输和实际重建失败。CAP-001 验证抓包边界。新测试补上抖动和静默阈值、合法时间戳回绕抑制。规则级测试对应本仓库口径，21 条规则各自的真实故障现场样本覆盖仍待扩充。

## 单机、前端与发布验证

| 检查 | 结果 |
|---|---|
| 公共 Windows v1.1.0 ZIP | 本次从已校验发布包解压，在实际 WebView2 页面导入现场包并自动完成分析、播放、诊断焦点、SIP → 报文 HEX、工作台/历史/对比/设置导航、切换深浅主题、下载 MD/JSON/HTML/CSV，最后关窗和引擎退出 |
| 性能及 SQLite | 同一引擎连续跑完六次。数据库 `integrity_check` 为 `ok`，`foreign_key_check` 无记录 |
| 本地候选 Windows ZIP | 使用公开包的同版 WebView2 壳和本轮源代码重新构建的分析引擎，重复通过真实抓包导入、自动分析、播放、导航、主题、四种报告和关窗退出。该本地包沿用 1.1.0 内部版本号用于验收。发布流程仍需独立构建补丁版本 |
| 候选异常恢复 | 强制终止分析引擎后，用相同独立目录启动。活动任务标为「已中断」，既有任务 JSON 报告内容一致，SQLite 完整性与外键检查通过 |
| 任务与清理 | 重复提交、并发槽、取消、启动中断、丢失源文件的重跑、清理活动任务、上传取消、分片失败重试通过自动化回归 |
| 前端交互 | 本轮真实桌面通过上述核心导航及联动，前端 lint、42 项 Vitest、build 和 budget 通过，首屏 97.8 KB／110 KB。深浅色桌面、主题选区、报文筛选与对比创建另有同一前端版本的 UAT。所有页面的每个按钮逐一复点仍待验证 |
| 依赖缺失 | 屏蔽 TShark/Capinfos/FFmpeg/FFprobe 后，245 通过、7 个环境用例跳过。已有报告保留，缺 TShark 和 FFmpeg 时的降级由回归覆盖。干净终端上的所有依赖组合和 Npcap 网卡实采待验证 |
| 后端全量 | Ruff 通过，pytest 251 通过、1 个 POSIX 权限用例跳过。覆盖率 81.58%，超过 70% 门槛 |
| Docker | `docker compose config -q` 通过，既有主线构建 CI 通过。本机 Docker Linux daemon 未运行，Compose 实际运行未测 |

## 性能基线

在公开 v1.1.0 Windows 引擎、同一新建数据目录、串行提交。耗时为开始上传到完成结果可读，包含 FFmpeg；每 200 ms 采样引擎及子进程工作集之和。磁盘增量为各任务前后数据目录大小差，包含 SQLite/WAL、上传和预览。工作集会重复计入共享页。大包为实测现场包做时间平移扩展，属于容量测试。

| 场景 | 报文 / 流 | 耗时 | 峰值工作集 | 磁盘增量 |
|---|---:|---:|---:|---:|
| 纯 RTP，60.23 KiB | 120 / 1 | 2.52 s | 199.47 MiB | 0.31 MiB |
| 多路 RTP，963.27 KiB | 1,920 / 16 | 4.53 s | 211.59 MiB | 3.54 MiB |
| 混合 SIP/RTP，62.89 KiB | 126 / 1 | 2.69 s | 204.50 MiB | 0.69 MiB |
| 连续任务第 2、3 次 | 每次 126 / 1 | 2.47 / 2.47 s | 209.06 / 204.38 MiB | 1.64 / 0.11 MiB |
| 大包，227.72 MiB | 219,147 / 70 | 159.93 s | 2,614.25 MiB | 399.75 MiB |

## 未关闭 Issue 核对

| Issue | 封版判断、源码和核对方法 |
|---|---|
| #1 · 报告导出 | 已实现。检查 [report.py](../backend/app/services/report.py)，在完成任务下载四种格式；归档流程通过 |
| #2 · RTCP | 部分实现，P2。对含多 RR 块的包可查已有报告；完整 SR/RR 对齐和 RTT 一致性需用含已知发送时基的样本比较，入口为 [evidence.py](../backend/app/api/evidence.py) |
| #3 · 设备拓扑 | 部分实现，P2。完成含信令与流的任务后可见端点关系清单；多跳图布局与节点过滤应在独立真实拓扑样本验收，组件为 [CaptureEvidence.vue](../frontend/src/components/CaptureEvidence.vue) |
| #4 · Docker Compose | 配置与镜像构建已交付，运行实测待验证。开启 daemon 后用 [docker-compose.yml](../docker-compose.yml) 启动并检查上传/导出。目前影响容器部署验收 |
| #5 · PostgreSQL / 迁移 | P2。当前 [db.py](../backend/app/core/db.py) 面向单机 SQLite。团队版才需要用既有历史库验证升级、数据迁移和并发事务 |
| #6 · 可解码首帧 | P2，见问题清单。当前首 RTP 时延为接收观察值。用含已知关键帧和终端显示时刻的样本分别验证 |
| #7 · 分片上传 | 已实现。支持 Web Crypto 的页面上传超过 32 MiB 的文件时，按块校验并续传。用 [test_field_workbench.py](../backend/tests/test_field_workbench.py) 验证重试、重复合并和磁盘不足，79.6 MB 现场包验证实际 UI 路径 |
| #8 · 单元测试数量 | 数量目标早已达到。后端现有 pytest 251 项通过；后续按真实失败路径补用例，记录在 [backend/tests](../backend/tests/) |

## 修改文件与边界

本地候选 ZIP SHA-256 为 `06685a8297711565ed5790b67a2b1bf2dfdd61874f4b8de1de53a0e57e39748e`。

- 稳定性：[tasks.py](../backend/app/api/tasks.py)、[intake.py](../backend/app/api/intake.py)、[analysis_control.py](../backend/app/core/analysis_control.py)、[retention.py](../backend/app/services/retention.py)。
- 回归：[test_retention_coordination.py](../backend/tests/test_retention_coordination.py)、[test_field_workbench.py](../backend/tests/test_field_workbench.py)、[test_diagnostic_observations.py](../backend/tests/test_diagnostic_observations.py)。
- 文档：[README.md](../README.md)、[IMPLEMENTATION_STATUS.md](../IMPLEMENTATION_STATUS.md)、[ROADMAP.md](ROADMAP.md)、[CHANGELOG.md](../CHANGELOG.md)、本报告。
- 已知限制：单机 SQLite、Windows 便携包无代码签名、网络部署需独立验收。DeepSeek 公网、设备端实采权限、现场异构双点、完整 RTCP SR/RR 对时与极限容量待验证。本轮现场文件和诊断报告数据保存在本机。


## 迭代验收：v1.2 可信度与容量补丁

本轮以 940cd57 为基线，修复数值口径并降低大包内存峰值，不改变诊断规则数量。

- **H.265 SPS**：conformance window 按 4:2:0/4:2:2 的 SubWidthC/SubHeightC 裁剪，读取 luma/chroma bit depth。新增带 1088→1080 底部裁剪、Main10 的合成 SPS 黄金值测试。
- **RTP 时间戳**：跳变阈值跟随 clock_rate，新增 8 kHz 流 6 秒跳变与 4 秒不误报的测试。
- **抓包扫描**：去掉 capinfos 之外的 IP/TCP/UDP 三次全量 tshark 计数，改由报文索引汇总。inspect_file 仍负责格式、时长、链路类型与文件校验。
- **PS/ES 与预览**：编码结构分析与 MP4 预览取样流开头 60 秒或 256 MiB，媒体质量指标仍覆盖完整流；界面标注取样范围。新增窗口与字节预算测试。
- **可支持性**：运行日志写入数据目录 logs/analyzer.log，5 MiB × 4 滚动；健康检查返回日志路径。应用版本变化时通过 SQLite 在线备份 API 生成 backups/analyzer-<version>-<time>.db，保留最近 5 份，升级前失败会记录日志。
- **桌面构建**：Windows 脚本缺少 Rust 时给出明确错误，并兼容用户目录下的 .cargo/bin/cargo.exe；新增构建契约测试。

验证结果（Windows 11，本地）：

| 检查 | 结果 |
|---|---|
| 后端 pytest | 262 通过，1 个 POSIX 权限用例跳过 |
| Ruff | 通过 |
| 前端 lint / Vitest | 0 error / 42 通过 |
| 前端构建与首屏预算 | 通过，100.1 KB / 110 KB |
| WebView 冒烟 | 设置页显示日志路径；待分析任务标题显示分析中；浏览器式 beforeunload 被拦截（页面刷新/导航）；已有任务视频与编码区正常渲染 |
| 真实分析 | 示例抓包 126 报文、1 条流完成分析，日志落盘 |
| 候选便携包 | 用 v1.1.5 桌面壳替换新引擎后重新打包，ZIP 解包、WebView2 启动、关窗和引擎退出冒烟通过 |

未在本机验证：Tauri 桌面 EXE 重编译（本机缺少 Rust，winget 安装请求未获确认）；离线单文件 EXE 的重新打包。两者需要在带 Rust 工具链的 Windows 构建机上完成。
