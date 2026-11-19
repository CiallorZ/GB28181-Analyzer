# 发布流程

面向维护者。目标版本：`0.0.1` 起。发布前必须全部打勾。

## 1. 版本号

版本只有一处来源：`backend/app/__init__.py` 的 `__version__`。
健康检查、OpenAPI 文档都读它；`tests/test_version.py` 会校验前端 `frontend/package.json` 与它一致。

```bash
# 同时改三处（package-lock 有两行版本字段）
backend/app/__init__.py            __version__ = 'X.Y.Z'
frontend/package.json              "version": "X.Y.Z"
frontend/package-lock.json         "version": "X.Y.Z"（两处）
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
- 用 `git archive` 打源码包 `gb28181-analyzer-vX.Y.Z.tar.gz`；
- 生成 `SHA256SUMS.txt`；
- 以 tag 创建 GitHub Release（自动汇总 PR 列表）。

## 5. 发布后

- 下载 Release 里的源码包，按 README 快速开始跑一遍（至少验证源码包不缺文件）。
- 需要镜像时：`docker compose up --build`，确认前端 8080、后端 8788 与报告导出都正常。
- 失败时：先撤 Release，再 `git tag -d vX.Y.Z && git push origin :refs/tags/vX.Y.Z`；
  修复后用新补丁版本重发，不改已发布的 tag。

## 当前发布等级

`0.0.1` 定位为**内网可用**：核心链路（上传 → 解析 → 诊断 → 报告）已闭环并有测试护栏；
未验证项在 README「已知限制」中逐条列出，发布说明里必须保留这些限制，不要写成「生产就绪」。
