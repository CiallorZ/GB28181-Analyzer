# 发布流程

面向维护者。目标版本：`0.0.1` 起。发布前必须全部打勾。

## 1. 版本号

版本只有一处来源：`backend/app/__init__.py` 的 `__version__`。
健康检查、OpenAPI 文档都读它；`tests/test_version.py` 会校验前端 `frontend/package.json` 与它一致。

```bash
# 同步以下位置，依赖项版本保持原值
backend/app/__init__.py            __version__ = 'X.Y.Z'
frontend/package.json              "version": "X.Y.Z"
frontend/package-lock.json         "version": "X.Y.Z"（两处）
desktop/tauri.conf.json            "version": "X.Y.Z"
desktop/Cargo.toml                 gb28181-desktop 的 version
desktop/Cargo.lock                 gb28181-desktop 的 version
```

## 2. 变更记录

`CHANGELOG.md` 顶部新增 `## [X.Y.Z] - YYYY-MM-DD`，写清「新增 / 变化 / 已知限制」。
README 的「当前版本」同步更新。

## 3. 验收

```bash
cd backend
python -m pytest tests/ -q --cov=app --cov-fail-under=70
ruff check app tests

cd ../frontend
npm run lint
npm run test
npm run build

cd .. && docker compose config -q     # 有 Docker 时再跑一次 compose
```

界面至少覆盖：暗色、亮色、390px 移动端各截一次关键页面，控制台无 error。
报告导出需要实际下载一次 `.md` 与 `.json`，确认内容与页面数字一致。

可选 AI 服务纳入发布目标时，从仓库根目录执行 `backend/.venv/Scripts/python scripts/verify-deepseek.py`。进程从 `DEEPSEEK_API_KEY` 读取凭据，用临时数据库中的合成会话调用官方服务，验证流式报告和追问均收到正文及结束事件。运行会使用该账户的 API 额度，输出仅记录模型名及两次回复长度。

面向 main 的 PR 还会在干净的 Windows x64 runner 构建候选 ZIP。测试解压后启动引擎和桌面窗口、访问对比入口、关闭窗口并确认引擎退出。可在该次 CI 的 Artifacts 下载按 PR 提交 SHA 命名的候选制品。

## 4. 提交与打标签

```bash
git checkout main
git merge --ff-only <release-branch>
git commit -m "release: vX.Y.Z"
git tag -a vX.Y.Z -m "vX.Y.Z"
git push origin main
git push origin vX.Y.Z
```

标签推送后 `.github/workflows/release.yml` 会自动：

- 构建前端 `dist` 并打成 `gb28181-analyzer-frontend-vX.Y.Z.zip`；
- 在 Windows x64 构建便携 ZIP，解包验证 EXE 启动后加入发布；
- 用 `git archive` 打源码包 `gb28181-analyzer-vX.Y.Z.tar.gz`；
- 生成 `SHA256SUMS.txt`；
- 以 tag 创建 GitHub Release（自动汇总 PR 列表）。

## 5. 发布后

- 下载 Release 里的源码包，按 README 快速开始跑一遍（至少验证源码包不缺文件）。
- 需要镜像时：`docker compose up --build`，确认前端 8080、后端 8788 与报告导出都正常。
- 失败时：先撤 Release，再 `git tag -d vX.Y.Z && git push origin :refs/tags/vX.Y.Z`；
  修复后用新补丁版本重发，不改已发布的 tag。

本地复现 Windows 构建时，在 Windows x64 使用 Python 3.12、Node.js 20 和 PowerShell 7。
桌面壳还需要 Rust 工具链与 WebView2 构建依赖。安装 rustup 后重新打开终端，确保 cargo 位于 PATH；脚本也会检查用户目录下的 .cargo/bin/cargo.exe。

```powershell
python -m pip install -r backend/requirements.txt pyinstaller==6.19.0
./scripts/build-windows.ps1
python scripts/smoke-windows.py build/windows/gb28181-analyzer-windows-x64-vX.Y.Z.zip
```

## 1.0.0 验收记录

| 检查 | 方法和观察结果 |
| --- | --- |
| 现场点播 | 双向现场抓包共 73,049 帧，得到 8 个会话、28 条 TCP 媒体流。8 条关联会话，20 条独立列出。28 份预览均通过下载校验，FFprobe 识别为 H.264，FFmpeg 均成功解码首帧。 |
| 诊断证据 | 对照原包复核 47 条记录，涉及 6 个规则。检查 SIP 事务标识、BYE 应答、SDP 主体中的 SSRC、RFC4571 尾帧边界及 RTP 序号。观察到一处 29 包的序号缺口。该证据不足以确定丢失位置或原因。 |
| 双点对比 | 在两个隔离网络命名空间内建立点播，各自在接口独立抓包。使用仓库示例的 SIP/SDP 和生成的 H.264 测试画面，两侧分别观测到 126 帧、120 个 RTP 包。1 个会话和 1 条流精确对齐，结构性差异、超容差和未对齐计数均为 0，首个关键帧时延保留为未知。两份 160×96 MP4 均通过整段解码，JSON 与详情相同，Markdown 可下载。现场包另行用于双向证据核对，文件只记录一个抓包接口。 |
| 诊断界面 | Edge 桌面与 390 px 窄屏检查规则折叠、键盘打开、等级和规则筛选、空结果、跳转报文及返回。在隔离数据库扩充至 257 条事件，成功从首批 200 条继续加载全部。 |
| 外部工具缺失 | 模拟工具探测结果为空。缺少 TShark 时新任务明确失败，既有完成任务的报告保留。缺少 FFmpeg 时仍可查看信令、关联媒体与导出报告，重建项显示工具缺失。 |
| 对比耗时 | 每侧 500 会话、2,000 条流，从发起 POST 到响应返回耗时 0.194 秒，响应 561,054 字节。复验命令见双抓包对比文档。 |
| Windows 长任务 | 将现场包按时间平移重复三次，得到 238,782,531 字节、219,147 帧。两次独立重跑分别用时 90.93 秒和 90.76 秒，重启后均可导出相同汇总。最终引擎再次运行，同时复验现场样本，耗时 199.14 秒，桌面进程树的 160 次采样中工作集最高 3.06 GiB，该次数据目录占 421.26 MiB。以上为本机观测值。 |
| 取消和中断 | 在读取文件阶段取消后 0.24 秒内可重新分析。另一次在 4 个 FFmpeg 进程运行时取消，0.98 秒内确认重试已受理且原进程已退出。关窗中断分析后，用同一数据目录启动，界面标记任务已中断，可重新运行。 |
| 回归 | Windows 后端 235 项通过、1 项 POSIX 权限用例跳过；模拟无外部工具时 229 项通过、7 项按环境跳过。前端 42 项通过，lint、build 和 budget 均通过，首屏同步 JS 97.7 KB（预算 110 KB）。 |

首轮长任务曾在媒体阶段失去本地服务连接。随后的两次独立复跑和最终引擎复测均完成；现有日志不足以确定首轮中断原因。现场抓包、视频、设备标识与原始报告仅保存在本地。
