# 开发说明

## 环境

- Python 3.10+
- Node.js 18+
- tshark（Wireshark 自带）
- ffmpeg（可选，用于视频重建）

## 本地启动

```bash
# 后端
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8788 --reload

# 前端
cd frontend
npm install
npm run dev
```

或直接双击 `start-dev.bat`（Windows）/ `./start-dev.sh`（Linux/macOS）。

## 测试

```bash
cd backend
.venv\Scripts\python -m pytest tests/ -q
```

测试全部基于合成数据，不依赖真实抓包。

## 代码约定

**解析器**
- 外部程序调用一律列表传参，不用 `shell=True`
- 每个外部进程都有超时，异常带上下文
- 解析不出就返回 `None`，不要猜

**指标**
- 算不出来的字段留 `NULL`，不填 0
- 区分「观察到的现象」与「确认的事实」

**诊断规则**
- 必须能追溯到报文或计算数据
- 必须标注证据等级

**前端**
- 按钮只用全局 `.btn` 体系，不在页面里自定义
- 图表通过 `alma-theme-changed` 事件跟随主题重绘
- SVG 内的 `v-for` 要用字符串拼装（见 `SipLadder.vue` 注释）

## 提交前检查

```bash
# 后端语法与测试
python -m pytest tests/ -q

# 前端构建
cd frontend && npm run build
```

## 不要提交

- `data/ai_config.json`（含 API Key）
- `data/uploads/`、`data/rebuilt/`（抓包与视频）
- `data/*.db`（数据库）
- `.venv/`、`node_modules/`

`.gitignore` 已覆盖，但提交前用 `git status` 再确认一次。
