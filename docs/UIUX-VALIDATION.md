# 中国铁塔风格 UI/UX 改造与验收

## 实施记录

| 阶段 | 改动与验证 |
| --- | --- |
| 0 | 审计当前分支的工作台、任务、证据路由、分析服务和 Tauri 打包流程。变更前前端 lint、58 项测试、构建和体积预算通过。后端初始环境 325 项通过，7 项因平台或工具缺少跳过。 |
| 1 | `frontend/src/styles/tokens.css` 定义品牌、双主题、间距和图表主系列。共享表格及焦点样式位于 `desktop-workspace.css`。普通业务样式通过 CSS 变量跟随根节点的 `data-theme`。铁塔线稿为本地 SVG。 |
| 2 | `App.vue` 提供 48 px 标题栏、216/56 px 导航和 28 px 真实状态栏。主题支持跟随系统、浅色和深色，和折叠偏好分别在本地持久化。详细页面共用当前任务上下文。 |
| 3 | 全部既有页面使用工作站框架。工作台、历史任务、分析结论、SIP、会话详情、媒体、报文、对比及详情、会诊和设置均有实际运行截图。 |
| 4 | 媒体页按真实流选择预览。SIP 会话栏宽度和报文列表高度可拖拽或用方向键调整，协议树和 HEX 分侧滚动。对照双主题实图检查留白、焦点、视频、表头和消息详情。 |
| 5 | 前端 lint、Vitest、Vite 构建和体积预算通过。后端与实际 TShark、FFmpeg、FFprobe 联合运行。Windows 原生发行包验证情况见下文。 |

## 运行截图与功能迁移

1440×900，Windows 上的 Edge。使用仓库的 UDP、TCP RFC4571 验收抓包及 SRS 公开点播抓包。视频封面来自公开抓包重建结果。AI 截图显示真实的未配置状态。 [SRS 抓包文档](https://ossrs.io/lts/zh-cn/docs/v6/doc/gb28181)

| 页面 | 浅色 | 深色 | 检查项 |
| --- | --- | --- | --- |
| 工作台 | [截图](screenshots/uiux/workbench-light.png) | [截图](screenshots/uiux/workbench-dark.png) | 导入、流程演示、最近任务 |
| 历史任务 | [截图](screenshots/uiux/tasks-light.png) | [截图](screenshots/uiux/tasks-dark.png) | 读取真实任务列表 |
| 任务总览 | [截图](screenshots/uiux/results-light.png) | [截图](screenshots/uiux/results-dark.png) | 真实会话、趋势、诊断与重建封面 |
| 分析结论 | [截图](screenshots/uiux/diagnostics-light.png) | [截图](screenshots/uiux/diagnostics-dark.png) | 任务指标、规则命中与证据入口 |
| SIP 信令 | [截图](screenshots/uiux/sip-light.png) | [截图](screenshots/uiux/sip-dark.png) | 选择时序消息并显示详情 |
| 会话详情 | [截图](screenshots/uiux/session-light.png) | [截图](screenshots/uiux/session-dark.png) | 信令与媒体状态、SDP、关联流 |
| 媒体分析 | [截图](screenshots/uiux/media-light.png) | [截图](screenshots/uiux/media-dark.png) | 流趋势与实际重建视频播放 |
| 原始报文 | [截图](screenshots/uiux/packets-light.png) | [截图](screenshots/uiux/packets-dark.png) | 指定编号定位、协议树与真实 HEX |
| 双包对比 | [截图](screenshots/uiux/compare-light.png) | [截图](screenshots/uiux/compare-dark.png) | 选择已完成任务与读取历史 |
| 双包对比详情 | [截图](screenshots/uiux/comparison-light.png) | [截图](screenshots/uiux/comparison-dark.png) | 快照读取、Markdown 和 JSON 导出 |
| AI 专家会诊 | [截图](screenshots/uiux/ai-light.png) | [截图](screenshots/uiux/ai-dark.png) | 未配置密钥提示和本地面板 |
| 系统设置 | [截图](screenshots/uiux/settings-light.png) | [截图](screenshots/uiux/settings-dark.png) | 分类导航与外观持久化 |

## 运行验证

- `npm run lint`、`npm test`（58 项）、`npm run build`、`npm run budget` 均通过。首屏同步 JS 的 gzip 体积从 102.8 KB 增至 104.2 KB，预算为 110 KB。
- `.venv/Scripts/python.exe -m pytest backend/tests -q` 在 TShark 4.6.10、FFmpeg 和 FFprobe 可用时为 333 项通过、1 项跳过。跳过项检查 POSIX 权限位。另有 FastAPI/Starlette 弃用警告。
- `scripts/verify-public-playback.py` 使用 SHA-256 校验后的 SRS PCAPNG，以完整和缩短的观察窗口分析并创建快照。精确对齐的同一 RTP 流分别得到 1669 和 811 个包，两份视频都经 FFprobe 确认是 640×480 H.264，Markdown 和 JSON 报告导出通过。
- 浏览器阻断非回环网络请求后，成功访问本地生产构建、创建分析和对比任务、打开报告、读取报文协议树与 HEX、播放重建视频。播放期间切换主题后同一个视频元素继续存在，重载后恢复主题。24 张截图采集过程中未记录浏览器页面异常。
- 工作台、SIP 和报文页在 1280×720、1366×768、1920×1080、2560×1440、960×600 检查了页面横向溢出。工作台、报文和媒体页通过浏览器设备像素比 1.25 与 1.5 的模拟检查。
- 一次本地验收的完整分析耗时约为 UDP 126 帧 1.80 秒、TCP 43 帧 1.75 秒、SRS 3212 帧 2.98 秒，包含 API 轮询粒度。没有同条件的端到端历史耗时或整进程峰值内存。另用重复拼接公开抓包得到的 102,784 帧压力样本测试，分析耗时 22.76 秒，报文表首次出行 386 ms，翻页 90 ms，第 100,000 帧跨页定位 230 ms。常规页保留 200 行 DOM，跨页选择可额外显示一行已定位报文。

## 后端决策

保留 FastAPI、SQLite 和 Tauri 的部署边界，在现有分析服务内优化热路径。Native Shell v0.7.1 提供桌面渲染和打包，Windows WebView2 能承载 Vue，但更换桌面壳无法减少抓包解析和数据库写入成本。完整 Rust 重写需要逐项复核 SIP、SDP、RTP、RTCP、视频和诊断语义。现阶段选择以批量写入降低实际开销。 [Native Shell 架构](https://nsh.dev/zh-CN/docs/architecture) · [Windows 支持](https://nsh.dev/zh-CN/docs/windows)

- `backend/app/services/analyzer.py` 使用 SQLAlchemy 2 批量映射写入。提交批次和取消检查保持原有行为。以仓库示例解析出的字段重复构造 100,000 行、每 2,000 行提交，SQLite 文件库对照实测如下。

  | 路径 | 3 次耗时 | 中位数 | Python 分配峰值 |
  | --- | --- | --- | --- |
  | 构造 ORM 对象再写入 | 4.294 / 4.184 / 4.186 秒 | 4.186 秒 | 5,761,197 字节 |
  | 批量映射写入 | 2.516 / 2.648 / 3.588 秒 | 2.648 秒 | 4,872,664 字节 |

  分配峰值来自独立的 `tracemalloc` 测量。该基准只测索引写入。TShark 4.6.10 导出的重复字段问题也已修复，UDP 验收抓包返回两个 IP 且第一帧源地址可定位。

- `backend/app/api/sessions.py` 为现有媒体质量接口补充重建状态、编码和 RTCP 字段，视频仍由已有下载接口提供。
- `scripts/verify-public-playback.py` 在清理临时目录前关闭日志句柄，修复 Windows 上验收脚本退出时的文件占用。

## 本地 Windows 制品

浏览器便携包通过 `scripts/build-windows.ps1 -Python .venv/Scripts/python.exe -BrowserOnly` 构建。归档和 SHA-256 文件位于 `build/windows`。解压后双击 `Start-Analyzer.cmd`。`scripts/smoke-windows.py` 校验了归档摘要、启动器、隔离数据目录、同目录单实例、离线资源、示例分析、协议字段偏移和报告下载。另在解包后的实际界面验证了导入、主题恢复和 HEX 高亮。

原生桌面便携包以锁定的 Rust 依赖构建。对实际归档执行 `scripts/smoke-windows.py <ZIP> --analyze-sample` 并通过。冒烟覆盖校验、隔离数据目录、示例分析、原生 WebView2 窗口出现、正常关闭与引擎端口回收。程序内部版本号仍为 1.3.0，本地 ZIP 是当前工作区的候选包。

## DeepSeek 产品走查

| 用户需要 | 本轮实现 |
| --- | --- |
| 看完本地结论后，知道 AI 可以帮忙检查什么 | 任务总览加入综合研判、检查信令、检查媒体与现场排障。SIP、媒体和分析结论页直接打开对应视角。 |
| 发送前知道会发什么、发给谁 | 确认页展示任务摘要、脱敏范围、接收服务主机和当前视角。浏览器测试确认预览期间未发送分析请求。 |
| 等待、失败和重新分析时知道如何继续 | 请求发出后立即进入报告阶段。可以停止接收流式报告。失败反馈保留在会诊流程中，重新分析会再打开摘要确认。 |
| 从 AI 报告回到实际证据 | 提示词要求引用摘要已有证据、标明已观察和待核实、给出检查端和预期观测。媒体摘要补充实际可用的 RTCP、编码及重建状态。 |

[深色任务总览](screenshots/uiux/results-ai-dark.png) · [浅色任务总览](screenshots/uiux/results-ai-light.png) · [深色分析结论](screenshots/uiux/diagnostics-ai-dark.png) · [浅色分析结论](screenshots/uiux/diagnostics-ai-light.png)

信令、媒体、诊断和任务总览均做了 1440×900 双主题走查。浏览器以实际任务和本地脱敏摘要运行，模型响应以受控 SSE 测试数据验证。真实 DeepSeek 联网及报告效果仍待现场验证。前端测试 60 项通过，首屏同步 JS 104.5 KB。更新后的原生 ZIP 已通过解包、示例抓包、报告下载和窗口退出冒烟。

## 终版候选检查

- Windows 工作区普通按钮使用 8 px 圆角，面板使用 10 px，品牌区使用 14 px。按钮、导航、路由、任务进度和会诊抽屉共用交互动效时长。Edge 实测浅色、深色、键盘焦点、减少动态效果及 960 px 窗口布局。
- 实际子进程先输出 256 KiB stderr，再分别正常输出和非零退出。读取可完成，失败尾部错误可展示。本轮后端 334 项通过、1 项因 POSIX 权限语义跳过。SRS 公开样本的两路视频重建、快照导出和协议证据复测通过。
- 重新分析包含 102,784 帧的压力 PCAPNG，单次耗时 21.37 秒，并核对第 100,000 帧跨页定位。运行资源与历史测量不同，因此只记录本次耗时。
- 首屏同步 JS 104.5 KB，预算为 110 KB。前端 60 项测试、lint 与构建通过。当前 Windows 原生 ZIP 已验证解包、启动、抓包分析、导出与关闭，作为本地发布候选。真实 DeepSeek 流式响应、目标设备的实时采集和干净 Windows 环境验收仍是发布前检查项。

## 待补验收
- AI 联网提交、流式报告与停止生成需要已配置的服务及明确的发送确认。本次只验证了本地界面和现有自动化测试。
- 未操作真实网卡采集、批量删除本地业务数据，也未执行逐组件对比度审计。
- 参考图的布局仍有差异。诊断事件沿用可展开规则分组，会诊沿用侧边面板，报文列表和 SIP 会话栏使用可键盘操作的分隔条。协议字段须经字节校验才能联动 HEX。通用列宽拖拽尚未覆盖。
