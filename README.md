# GB28181 Analyzer

上传 PCAP/PCAPNG，还原一次视频点播从 SIP 协商到 RTP 收流的全过程，
给出可追溯到报文的质量指标与故障结论，并在条件允许时把媒体还原成可播放的 MP4。

面向 GB/T 28181（2016 / 2022）的点播故障取证：**先回答“哪一步坏了”，再回答“为什么”**。
不做通用抓包分析器。

[![CI](https://github.com/CiallorZ/gb28181-analyzer/actions/workflows/ci.yml/badge.svg)](https://github.com/CiallorZ/gb28181-analyzer/actions/workflows/ci.yml)

当前版本 **0.0.1**（首个公开发布版本），变更见 [CHANGELOG.md](CHANGELOG.md)。

## 能做什么

- **信令**：SIP 请求/响应、重传、Dialog 归并；国标 SDP 扩展 `y=`（SSRC）、`f=`、`setup`、`xstreamtype`
- **会话**：一个 INVITE Dialog = 一次点播，分别判定 `signal_status` 与 `media_status`
- **媒体**：UDP 与 TCP(RFC4571) 承载；序号回绕、丢包、乱序、抖动、码率、静默
- **编码**：MPEG-PS → PES → ES，H.264/H.265 识别，SPS 解析，按访问单元（AU）统计 I/P/B 帧
- **还原**：参数集对齐后用 ffmpeg 重建 MP4，前端直接播放
- **诊断**：规则引擎输出 critical/warning/info，每条带证据等级（confirmed/suspected/insufficient）、
  可能原因、排查建议、关联报文；21 条规则中 12 条已接入，其余在设置页明确标为「规划中」
- **AI 摘要**：可选接入 DeepSeek，只发送结构化摘要，不发送抓包原始字节

## 快速开始

依赖：Python 3.10+、Node.js 18+、[tshark](https://www.wireshark.org/) 4.x；
视频还原另需 ffmpeg 6.x（不装只影响播放，不影响统计）。

```bash
# 后端
cd backend
python -m venv .venv
.venv\Scripts\activate            # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env               # 可选：改端口/数据目录/外部工具路径
python -m uvicorn app.main:app --host 127.0.0.1 --port 8788 --reload
```

配置也可以不用 `.env`，直接设环境变量；两者同时存在时环境变量优先。

- API 文档：http://127.0.0.1:8788/api/v1/docs
- 健康检查：http://127.0.0.1:8788/api/v1/health

```bash
# 前端（另开一个终端）
cd frontend
npm install
npm run dev                       # http://localhost:5173
```

前端 dev server 把 `/api` 代理到 `127.0.0.1:8788`。生产构建用 `npm run build`，
产物在 `frontend/dist/`，交给静态服务器并反代 `/api` 即可。

### Docker

```bash
docker compose up --build
# 前端 http://localhost:8080 ，后端 http://localhost:8788
```

镜像内已安装 tshark 与 ffmpeg；抓包、数据库和重建产物落在 `./data`。
对外部署时请显式设置 `ALLOWED_HOSTS`。

### 测试与检查

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest tests/ -q                      # 端到端需要 tshark，缺失时 skip
python -m pytest tests/ -q --cov=app            # 覆盖率
ruff check app tests                            # 静态检查
```

```bash
cd frontend
npm run lint && npm run test && npm run build
npm run budget                                  # 首屏 JS 预算（110 KB）
```

端到端用例在 CI 的 integration job 中安装 tshark/ffmpeg 后真实执行，
覆盖率门槛 70%。测试样本与说明见 `backend/tests/fixtures/`。

## 架构

```
抓包 → 文件信息 → 报文索引 → SIP/SDP 解析 → 会话重建
     → RTP 分析（UDP / RFC4571）→ PS/ES 与编码分析 → 诊断 → 入库
```

```
backend/app/
  api/          tasks / sessions / diagnostics / ai
  core/         配置、数据库、安全校验
  models/       SQLAlchemy 实体
  parsers/      capture / sip_parser / session_builder / rtp_analyzer / ps_parser / rebuild
  services/     analyzer（编排）/ diagnosis（规则引擎）
  schemas/      Pydantic 契约
frontend/src/
  api/ stores/ views/ styles/
data/           uploads、analyzer.db、rebuilt/（运行时生成）
docs/           ROADMAP 与抓包分析笔记
```

分析在后台线程执行，HTTP 请求不阻塞；同一任务不能并发启动，取消状态不会被后续进度覆盖。

## 几个关键口径

**信令成功 ≠ 媒体成功。** `200 OK` 只说明协商完成。媒体是否真的到达、能否解码，单独判定。
两者在界面上分开显示，不合并成一个“成功/失败”。

**算不出来就留空。** 无法计算的指标存 `NULL`，界面显示“无法计算”或“—”，不写 0。

**TCP 被动模式的端口。** offer 里的 `m=video 8808` 是监听端口，answer 里的 `9` 是占位值。
媒体关联优先用 offer 端口，并把 0/9 视为占位，否则永远匹配不上实际连接。

**帧数按 AU 计。** 一帧通常由 SPS/PPS/SEI + 多个 slice NAL 组成。按 NAL 计数会把帧数放大数倍，
帧率和 I/P/B 比例随之失真；本项目按 `first_mb_in_slice == 0`（H.264）/
`first_slice_segment_in_pic_flag == 1`（H.265）切分访问单元。

**抓包点视角。** 结论只反映抓包位置观察到的流量。“没抓到”和“没发生”是两件事，
抓包截断、起点在会话中间等情况会以 `capture_warnings` 显式标出，不当作故障。

**TCP 承载的到达时间是插值。** RFC4571 没有逐包时间戳，码率/抖动按 TCP 段时间窗估算，
精度低于 UDP；界面与诊断会说明这一点。

## 配置

`.env`（仓库根或 `backend/` 下）或环境变量，常用项：

| 变量 | 默认 | 说明 |
|---|---|---|
| `HOST` / `PORT` | `127.0.0.1` / `8788` | 监听地址 |
| `DATABASE_URL` | `sqlite:///data/analyzer.db` | schema 兼容 PostgreSQL |
| `DATA_DIR` | `./data` | 上传、重建产物、数据库所在目录 |
| `TSHARK_PATH` / `FFMPEG_PATH` | 自动查找 | 外部工具路径（Windows 也可自动找 Wireshark 安装目录） |
| `MAX_CONCURRENT_TASKS` | `2` | 同时分析的任务数 |
| `KEEP_TASKS` / `KEEP_DAYS` / `DISK_BUDGET_MB` | `5` / `7` / `2048` | 历史与磁盘保留策略 |
| `KEEP_UPLOADS` | `1` | 关掉可省空间，但不能重新分析 |
| `ALLOWED_HOSTS` | 仅本机时自动限制 | 对外部署必须显式设置域名 |
| `CORS_ORIGINS` | 本机前端 | 跨源部署时设置 |
| `DEEPSEEK_API_KEY` | 空 | 也可在前端首次使用时配置（落盘权限 0600） |
| `AI_BASE_URL_ALLOWLIST` | `api.deepseek.com` | 允许的 AI 网关；换网关必须显式加白 |

本服务**没有账号体系**，定位是本机或可信内网的单用户工具。对外暴露前请在反向代理层加认证，
并设置 `ALLOWED_HOSTS`、透传 `Host`。上传文件按魔数校验，只读解析，不执行。

## API

统一前缀 `/api/v1`，完整契约以 `/api/v1/docs` 为准。主要分组：

- `POST /tasks/upload`、`GET /tasks`、`POST /tasks/{id}/analyze|cancel`
- `GET /tasks/{id}/overview|sessions|diagnostics|rule-stats|packets`
- `GET /tasks/{id}/report?format=md|json`（分析报告导出）
- `GET /sessions/{id}` 及其 `sip|timeline|media|metrics|diagnostics`
- `GET /packets/{id}`（协议树 + 十六进制）

## 已知限制

- 未做 RTCP 统计分析（数据模型已留位置）
- 设备拓扑只有后端数据，前端没有拓扑图
- 报告导出支持 Markdown / JSON；HTML 单文件报告与 CSV 未实现
- 上传为单请求，未做分片，上限 2GB
- PostgreSQL 未在真实环境验证；Docker 镜像由 CI 构建，Compose 运行需在目标机器验证
- H.265 暂不区分 B 帧，非 IRAP 帧统一计入 P
- 诊断规则尚余 9 条未实现（如 REGISTER 超时、SIP 重传、码率骤降），设置页会标注
- 抓包缺少 SPS/PPS 时无法还原画面，只能给出编码参数缺失的诊断

路线图与优先级见 [docs/ROADMAP.md](docs/ROADMAP.md)。

## 开发约定

- API 统一 `/api/v1/` 前缀；异步任务状态可查询
- 外部程序一律列表传参，不用 `shell=True`
- 上传文件只读解析；抓包原始内容不外发
- 新解析逻辑必须配黄金值测试（固定输入 → 固定输出），避免“看起来对”的统计回归
