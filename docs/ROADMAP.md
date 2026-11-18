# 优化分析与迭代方案

> 基线：`main` @ ef50c52（v1.0.0-P0）
> 分析日期：2026-11-18
> 方法：通读全部 7.4k 行后端 + 7.6k 行前端；用自建抓包（SIP/UDP、SIP/TCP、TCP+RFC4571 媒体、真实 H.265 PS）端到端跑通分析流水线；对照 tshark 4.6.9 / ffmpeg 7.0.2 验证解析结果。

---

## 一、总体判断

**做得好的地方（应保留）**

- 协议语义与展示层解耦干净：`tshark 只取字节 → 自研解析 → 规则引擎 → 入库`，这条主线是对的，也是这个项目最值钱的部分。
- 「信令状态 / 媒体状态分离」「算不出来就留 NULL」「区分 observed_gap 与 confirmed_loss」这三条设计纪律贯穿代码，是同类工具里少见的严谨。
- 前端「单入口瀑布式 + 空板块自动收起 + 无法计算用灰色斜体」的交互决策有依据，不是拍脑袋。
- 已有 42 个单元测试，解析器（sip 84% / rtp 90% / session 83% / diagnosis 89%）覆盖尚可。

**核心问题：文档宣称的能力与代码实际行为存在系统性偏差，且偏差都落在「国标专有语义」上。**

这类偏差最危险：它不会报错，只会给出看起来合理但错误的结论。下面第 2 节的每一条都已实测复现。

---

## 二、已复现的缺陷（按影响排序）

> **修复状态（第一轮迭代，2026-11-18）**：P0-1、P0-5、P0-16、P0-17、P0-18 已修复并补回归测试，
> 详见 §2.1「第一轮修复说明」。其余条目仍为待办。

### P0-1 国标 SDP 的 `y=` / `f=` 独立行未解析 —— 影响 SSRC 校验与流关联

`GB/T 28181` 附录 F 中 `y=` / `f=` 是 **会话级独立行**，不是 `a=` 属性：

```
v=0
o=34020000001320000001 0 0 IN IP4 192.168.1.10
m=video 3400 RTP/AVP 96
a=recvonly
y=0100000001
f=
```

`backend/app/parsers/sip_parser.py:244-263` 只在 `k == 'a'` 分支里处理 `y` / `f`，且要求 `name:value` 形式。实测三种写法的结果：

| SDP 写法 | 是否标准 | 解析结果 |
|---|---|---|
| `y=0100000001`（顶层独立行） | **是**（附录 F） | `''` ❌ |
| `a=y=00001234` | 否（常见误写） | `''` ❌ |
| `a=y:00001234` | 否（仅冒号形式） | `'00001234'` ✅ |

即：**标准写法解析不出来，只有非标准的冒号写法能解析**。

**后果**
- `SDP-003 SSRC 不一致` 规则条件为 `if subj and sdp_ssrc:`，`sdp_ssrc` 恒空 → **该规则永不触发**。
- `session_builder._match_score` 中 SSRC 完全匹配的 +100 分权重永久失效，只剩端口 60 分 + 时间窗 30 分 → 多流场景误关联概率上升。
- 端到端实测（自建 UDP pcap）：`subject_ssrc='00001234'`，`sdp_y=''`，规则未命中。

**修复**：`parse_sdp` 增加顶层 `k in ('y','f')` 分支；`SDP-003` 补 `insufficient` 证据等级（只有一侧有值时不判"不一致"）。

---

### P0-2 `dialog_key()` 排序与 `build_dialogs` 不一致 —— 请求消息永远回填不到 dialog_id

```python
# sip_parser.py:134
tags = tuple(sorted([self.from_tag or '', self.to_tag or '']))
return '%s|%s|%s' % (self.call_id, tags[0], tags[1])      # 排序

# session_builder.py:128
d = DialogInfo(key='%s|%s|%s' % (call_id, from_tag, to_tag))  # 未排序
```

INVITE 请求方向 `To-Tag` 为空，因此请求的 key 是 `cid||abc`，而 Dialog 的 key 是 `cid|abc|xyz`，**永远不相等**。

实测：

```
dialog map key  = cid-1|abc|xyz
req.dialog_key  = cid-1||abc      → MATCH False
resp.dialog_key = cid-1|abc|xyz   → MATCH True
```

端到端确认：`INVITE` 请求 `dialog_id=None`，`ACK`/`BYE` 有值。

**后果**：任何「按 dialog 取消息」的查询都会漏掉 INVITE —— 而 INVITE 恰恰是信令时序图最重要的一条。目前前端没用到 `dialog_id`，所以没暴露，属于**埋着的雷**。

**修复**：`build_dialogs` 也排序；并补一条回归测试（已可复现）。

---

### P0-3 RTP 乱序被重复计为丢包 —— 丢包率虚高

`rtp_analyzer.py:184-207`：按到达顺序展开后，遇到 `d <= 0` 记一次乱序，但**仍然更新 `prev_unwrapped`**，导致后续包相对乱序包再算一次缺口。

实测 `seq = 1,2,4,3,5,6`（真实只缺 1 包）：

```
gaps = 2, gap_packets = 2, out_of_order = 1
gap events: [after_seq 2 → gap 1]  [after_seq 3 → gap 1]   ← 第二个是假的
```

**后果**：`MED-002` 用 `ratio = gap_packets / (total + gap_packets)` 定级，乱序越多丢包率越高，可能把 warning 误升为 critical。网络抖动场景下这是常态。

**修复**：缺口应在**去重、按 `seq_unwrapped` 排序后**统一计算（或维护 max_seen 只统计真正缺失区间）。乱序/重复作为独立指标保留。

---

### P0-4 RFC4571 单包长度上限 2048 —— 大包直接截断解析

```python
# rtp_analyzer.py:377
if L < 12 or L > 2048 or o + 2 + L > len(buf):
    break
```

RFC4571 的长度字段是 16 位，合法上限 65535。GB28181 设备在 TCP 承载下常把整个 I 帧塞进一个 RTP 包（2-8KB 常见）。

实测：19 个包，其中第 6 个 4000 字节 → **只解析出 5 个包**，其余全部丢弃，且不报错。

**修复**：上限改为 65535（或可配置），并在 `parse_rfc4571` 返回 `truncated` 标记，让上层写进 `notes` 而不是静默丢包。

---

### P0-5 「取消」无效 —— 状态被无条件覆盖

`analyzer.run_analysis` 在 `_run` 正常返回后无条件：

```python
task.status = TaskStatus.COMPLETED
```

`api/tasks.py:cancel_task` 只把状态写成 `CANCELLED`，worker 完成后照常覆盖。

实测（模拟 worker 运行期间取消）：

```
after run, status = TaskStatus.COMPLETED   （期望 CANCELLED）
```

**后果**：前端点「取消」后，任务最终仍显示「完成」，用户以为取消没生效；且分析线程实际继续跑满全程，取消只是视觉上的。

**修复**：worker 收尾前重读状态，若已是 `CANCELLED` 则不覆盖；`_run` 内部每个阶段边界检查取消标志并提前退出。

---

### P0-6 TCP 承载的 SIP 拿不到端口 —— 五元组残缺

```python
# analyzer.py:341-347
rows_raw = capture.extract_fields(path, [
    'frame.number', 'frame.time_relative',
    'ip.src', 'udp.srcport', 'ip.dst', 'udp.dstport',   # ← 只有 UDP 端口
    ...
], 'sip || tcp.port==5060')
```

filter 明确包含 TCP，但字段只取 `udp.*`。实测 TCP REGISTER：

```
method=REGISTER status=200  src_port=None dst_port=None
```

**后果**：TCP SIP 的端点统计、会话方向判定（`initiator_ip` 有、端口无）、`Endpoint` 表端口为空。国标 2022 大量设备走 TCP 5060。

**修复**：补 `tcp.srcport` / `tcp.dstport`，按 `src_port or tcp_src` 合并。

---

### P0-7 TCP 5060 上的非 SIP 载荷被当成 SIP 消息入库

实测一个只含 TCP 三次握手 + 1 条 REGISTER 的抓包，入库 **4 条** SIP 消息，其中 2 条是握手空包：

```
packet#1 method=None status=None call_id=None headers=0
packet#2 method=None status=None call_id=None headers=0
packet#3 REGISTER ...   ← 真实
packet#4 REGISTER 200 ... ← 真实
```

`build_message` 对空 header 也返回对象（只记 `parse_errors`），`_load_sip` 不做有效性过滤。

**后果**：`SIP 消息总数`、方法分布、`sip_count`（决定前端走「有信令」还是「纯媒体」分支）全部被污染。前端的「信令节是否显示」判断也会受影响。

**修复**：`build_message` 在 `not call_id and not method and not status_code` 时返回 `None`；或 `_load_sip` 跳过 `headers == {}` 的行。

---

### P0-8 PS 分析把 NAL 数当帧数 —— 帧数/帧类型统计全错

`ps_parser.analyze_es`：

```python
info.frame_count = nal_count          # 把 NAL 总数当帧数
```

实测 10 帧（每帧 SPS+PPS+1 个 IDR）→ `frame_count=30, i_frame_count=10`。
端到端 120 帧 → `frame_count=360`。

**后果**：前端「编码分析」里的帧数、I/P 比例、`keyframe_intervals` 全部失真；`MED-008` 的判据也依赖帧数。

**修复**：按 access unit 边界计数（`first_mb_in_slice == 0` 或 NAL 类型切换 + 时间戳变化）；无 PES 边界信息时明确标注 `frame_count_estimated`。

---

### P0-9 视频重建分辨率失真

`rebuild.py:191` 硬编码 `-vf scale=1280:-2`。源 2688×1520 输出 1280×**724**（1520/2688×1280=723.8，`-2` 取偶）。

实测真实 PS 文件：

```
ffprobe 源     : 2688x1520  H.265
重建产物       : 1280x724  h264
```

同时 H.265 源被转成 H.264 —— 这是有意的（浏览器兼容），但 `codec` 字段存的是 `rb.codec`（h264），会把「源编码」信息覆盖掉，用户看到 H.264 会以为设备就是 H.264。

**修复**：`scale` 改为不缩放或按需降档（`-vf scale='min(1280,iw)':-2`），并新增 `source_codec` 字段与 `codec`（产物编码）区分。

---

### P0-10 规则表 21 条 / 实际实现 12 条 —— `/rules` 接口误导前端

`diagnosis.RULES` 声明 21 条，`diagnose()` 实际只产出 12 种 `rule_id`：

```
已实现: SIP-001/003/008, SDP-003, MED-001/002/003/004/005/007/008, CAP-001
未实现: SIP-002/004/005/006/007, SDP-001/002/004, MED-006
```

`main.list_rules()` 把 `RULES` 全量返回，`SettingsView` / `DiagnosticsView` 会展示 21 条规则清单。

另外 `_check_sdp` 里注释写 `# SDP-002 协商端口与实际媒体不匹配`，实际产出的是 `MED-001`。

**修复**：`RULES` 增加 `implemented: bool`，`/rules` 只返回已实现的，或明确分组；注释与 ID 对齐。

---

### P0-11 文档「已知限制」已严重过期

`README.md:339-352` 仍写着：

> 1. 未实现 PS/ES 解封装（P1）
> 2. 未实现视频重建与预览（P1）—— `rebuild_path` 恒为空

但 `ps_parser.py`（582 行）、`rebuild.py`（332 行）已完整实现，`IMPLEMENTATION_STATUS.md` 也标 ✅。两份文档互相矛盾。

**修复**：README 已知限制按实际重写（真正的限制是：RTCP 未实现、报告导出未实现、分片上传未实现、Docker 未验证、TCP 到达时间是插值）。

---

### P0-12 `sip_dialog.session_id` 从不写入 —— Dialog 与业务会话的关联断开

模型里 `SipDialog.session_id` 有外键、有索引，`BusinessSession.dialogs` 关系也基于它，但 `analyzer._run` 只回填了 `SipMessage.session_id`，**从未回填 `SipDialog.session_id`**。

**后果**：`BusinessSession.dialogs` 恒为空；任何「按会话列出其 Dialog」的查询都是空集。目前前端走 `call_ids` 绕过了这个问题，但模型层的关系是断的。

**修复**：建 `call_id → session_id` 映射后，对 `SipDialog` 批量 UPDATE 一次即可。

---

### P0-13 `packet_index.ssrc` / `session_id` 从不写入

模型和 API 都支持（`diagnostics.py:94-95` 按 `session_id` 过滤报文），但 `analyzer` 里只有回填 `call_id`，`ssrc` / `session_id` 永远是 NULL。

**后果**：前端任何「按会话看报文」的入口都会得到空列表；`PacketIndex` 的这两个索引是纯开销。

**修复**：在流关联完成后批量回填（按 `(src_port, dst_port, ssrc)` 匹配），或删掉字段与过滤参数。

---

### P0-14 `related_packet_ids` 永远为空 —— 证据可追溯性未落地

`Diagnostic.related_packet_ids` 在所有规则里都没赋值，但前端 `DiagnosticsView.vue:153` / `SessionDetailView.vue:427` 都有渲染分支。

这是 PRD 的硬要求（「每条诊断能追溯到报文」），目前是**空承诺**。

**修复**：规则里带上触发该结论的 packet number（SIP 规则带消息包号，MED-002 带首个缺口前后的包号），入库后前端链接即可点开报文查看器。

---

### P0-15 诊断列表「先分页、后排序」—— 第一页可能看不到 critical

`api/diagnostics.py:36-43`：

```python
rows = db.scalars(stmt.offset(...).limit(page_size)).all()   # 先分页（DB 无 ORDER BY）
rows = sorted(rows, key=lambda r: (order.get(r.severity, 9), r.timestamp or 0))
```

排序发生在**分页之后**，只能排当前页的 50 条。实测 4 条诊断（info/warning/critical/warning）、`page_size=2`：

```
PAGE1 = ['warning', 'info']      ← critical 不在第一页
PAGE2 = ['critical', 'warning']
```

**后果**：`DiagnosticsView` 与 Workbench 的诊断列表默认只取前 N 条并按严重度展示，最严重的问题可能被排到后面几页，而用户只会看第一页。

**修复**：把严重度映射成 DB 可排序的值（`CASE WHEN` 或加 `severity_rank` 列），在 SQL 里 `ORDER BY` 后再分页。

---

### P0-16 分析异常处理自身抛 `UnboundLocalError`，真实错误被掩盖

`analyzer.py:84-88` 在 `try` 内写了局部 `import traceback`：

```python
try:
    from . import retention
    retention.auto_purge(db)
except Exception:
    import traceback          # ← 这一行让 traceback 在整个函数内变成局部变量
    traceback.print_exc()
...
except Exception as e:
    ...
    traceback.print_exc()     # ← 这里访问未绑定的局部变量
```

Python 的作用域规则：函数内任何位置出现 `import traceback`，`traceback` 就是整个函数的**局部名**。
若执行路径没经过那行 import（即 `retention` 没抛错），末尾的 `traceback.print_exc()` 就会抛 `UnboundLocalError`。

实测（抓包文件不存在）：

```
最终抛出的异常类型: UnboundLocalError
消息: cannot access local variable 'traceback' where it is not associated with a value
```

**后果**：任务状态与 `error_message` 已写入（`FAILED` + 原因），但**真实异常栈被完全吞掉**，
`_worker` 又 `except Exception: pass`，日志里什么都看不到。任何分析失败都无法定位原因。

**修复**：删掉函数内的局部 `import traceback`（模块级已有），统一改用 `logging.getLogger(...).exception(...)`。

---

### P0-17 重新分析先删光旧结果、再校验输入 —— 失败即不可逆丢数据

`analyzer.py:62-73` 在 `_run` 之前就删掉了 PacketIndex / SipMessage / SipDialog / MediaStream /
BusinessSession / DiagnosticEvent / Device / Endpoint，而抓包文件是否存在要到 `_run` 里
`capture.inspect_file` 才检查。

实测（预置 1 条会话，抓包路径不存在）：

```
分析前会话数: 1
分析失败后会话数: 0      ← 旧结果已被删除，不可恢复
```

触发条件很现实：默认 `KEEP_TASKS=5`，第 6 个任务分析完会把第 1 个任务的 pcap 删掉
（`retention.py:104-111`），但任务记录与统计还在。用户点「重新分析」→ 旧结果清零 + 分析失败。

**修复**：破坏性清理之前先 `os.path.isfile(stored_path)`，不存在则 409 并提示「原文件已被清理，请重新上传」；
更稳妥的是「先分析到临时 task，成功后再替换」。

---

### P0-18 同一任务可被并发触发多次分析

`api/tasks.py:180-191`：

```python
has_worker = bool(_running.get(task_id))
stale = (task.status == TaskStatus.ANALYZING and not has_worker)
if task.status == TaskStatus.ANALYZING and has_worker:
    raise HTTPException(409, '任务正在分析中')
```

冲突判断要求「DB 状态是 ANALYZING **且** 有 worker」。但请求刚进来时 DB 里还是 `PENDING`
（worker 还没把它改成 ANALYZING），于是 `has_worker=True` 被忽略，重复启动。

实测 3 个并发请求：

```
HTTP 状态码: [200, 200, 200]
实际启动的 worker 次数: 3      （期望 1）
```

**后果**：多个 worker 都会执行开头的 DELETE，互相删除对方正在写入的数据；SQLite 写锁竞争；
最终结果取决于最后完成的线程，数据可能重复或缺失且不可预期。

**修复**：只要 `task_id in _running` 就 409，不看 DB 状态；「占坑 + 置 PENDING」放进锁内做成原子操作，
并用 `try/finally` 保证 `_running` 不会泄漏。

---

### 2.1 第一轮修复说明（2026-11-18）

本轮只做「不改变输出语义、但消除不可逆损失」的五项，其余待办不动。

| 条目 | 改动 | 回归测试 |
|---|---|---|
| P0-1 | `sip_parser.parse_sdp` 增加顶层 `k in ('y','f')` 分支；`a=` 分支兼容 `a=y=` 与 `a=y:` | `tests/test_sdp_fields.py`（13 例） |
| P0-5 | `run_analysis` 在 `_run` 之后 `expire_all()` 重读状态，`CANCELLED` 不被覆盖 | `test_cancelled_status_not_overwritten_by_completion` |
| P0-16 | 删除函数内局部 `import traceback`，统一模块级 `log` | `test_unexpected_error_sets_failed_and_propagates_original` |
| P0-17 | 破坏性 DELETE 之前校验 `os.path.isfile(stored_path)`；API 层同样前置校验并返回 409 | `test_reanalyze_with_missing_file_keeps_old_results` 等 2 例 |
| P0-18 | `if task_id in _running: 409`，槽位检查与占用同锁；启动失败时归还槽位 | `test_concurrent_analyze_starts_only_one_worker` 等 3 例 |

顺带修掉的一个**新发现**：`SessionLocal` 设了 `expire_on_commit=False`，
`db.rollback()` **不会**让已加载对象失效。因此 `_mark_failed` 若只 `rollback()` 再 `get()`，
会从 identity map 拿到旧状态，把另一个会话刚写的 `CANCELLED` 覆盖成 `FAILED`。
修复为 `rollback()` + `expire_all()`，并由 `test_failed_status_not_overwritten_when_cancelled` 锁定。

### 与 main 上 `d3ed829` 的合并说明

开工期间 `main` 上多了一个提交 `d3ed829`（17:02），它也修了 `y=` 独立行，并且：

1. `sip_parser.parse_sdp` 加了 `elif k == 'y' / 'f'` 分支 —— 与本分支的
   `elif k in ('y','f')` **功能重复**，合并后成为死代码（前面的分支已命中），已删除。
2. `_match_score` 的 SSRC 权重 `100 → 10000`，并放宽为「互为后缀」匹配。
   这个改动方向是对的（多会话共享 8808 端口时，端口分会让所有候选同分），
   但**引入了一个新的边界缺陷**：

   ```python
   w = want.lower().lstrip('0')
   h = ssrc_hex.lower().lstrip('0')
   if h == w or h.endswith(w) or w.endswith(h):   # ← w 或 h 为空时恒真
   ```

   SSRC 缺失时 `raw_ssrc` 为 `0`/`None` → `ssrc_hex = '00000000'` → `h = ''`，
   而任何字符串都 `endswith('')`，于是**没有 SSRC 的流拿到满分 10000**，
   比真实匹配还高，会把流静默归到错误的会话。

   已修复为「任一侧为空则不参与匹配」，并由 `tests/test_media_matching.py`（10 例）锁定。
   端到端复跑确认归属结果不变。

同时新增 `backend/tests/conftest.py`：在 import 任何 `app.*` 之前把 `DATA_DIR` /
`DATABASE_URL` 指向临时目录，避免测试写真实数据库；`tests/test_e2e_fixtures.py`
用 `tests/fixtures/` 的样本跑完整流水线（无 tshark 时自动跳过）。

**覆盖率**：22% → 67%（`analyzer.py` 82%、`api/tasks.py` 36%、`sip_parser.py` 86%）。

---

## 三、性能与架构

### 3.1 每次分析 tshark 全量扫描 6 次以上

```
inspect_file  → capinfos + io,phs + 3 次 count 查询   （内部 3 次全量）
iter_packets  → 1 次全量
extract_fields(SIP)        → 1 次全量
extract_udp_rtp            → 1 次全量
dump_tcp_segments          → 1 次全量
_tcp_time_spread × 流数     → N 次全量      ← 最严重
```

`_tcp_time_spread`（`analyzer.py:587`）对**每条 TCP 流**再跑一次全量 `tshark -Y tcp.stream==N`。28 条流的纯媒体包 = 28 次全量扫描。

**优化**：`dump_tcp_segments` 已经拿到了每段的时间，直接从中取 `min/max` 即可，删掉 `_tcp_time_spread`（**零成本，立即生效**）。进一步可合并 `iter_packets` 与 SIP 抽取为一次 `-T fields` 全量输出。

### 3.2 大抓包内存占用与「2GB 上限」自相矛盾

`capture.extract_fields` 是**非流式**的：`_run` 把 tshark 全部输出读进内存，再拆成 `list[list[str]]` 返回。

`dump_tcp_segments` 用它取 `tcp.payload`，每段是一个十六进制字符串：

```
单个 1400 字节 TCP 段 → hex 字符串对象 2841 字节（实测 sys.getsizeof）
膨胀 ≈ 2.0x，且 list / row 的容器开销另计
```

2GB 抓包若 80% 是 TCP 媒体载荷 ≈ 1.6GB 原始字节 → **仅 hex 字符串就 ≈ 3.2GB**，
随后 `reassemble_tcp` 再拼一份 `bytearray`，`parse_rfc4571` 又切出 150+ 个 `RtpPacket`（每个带 payload 副本）。

同理 `analyzer._run` 里 `packets = []` 累积了全部报文的 dict（2M 报文 ≈ 1GB+），
而它只被 `detect_capture_limits`（要首末时间）和 `_build_summary`（要数量）使用。

**结论**：README 宣称支持 2GB，实际在 200-300MB 的 TCP 媒体抓包上就会 OOM 或严重换页。

**修复**
1. `extract_fields` 改为生成器版本（复用 `iter_packets` 的 `Popen` 流式模式），`dump_tcp_segments` 直接消费流。
2. `packets` 不保存全量，只累加 `count` / `min_ts` / `max_ts` / `protocols` 计数。
3. 大文件走「先转 Parquet / 按流切片」的两阶段处理。

### 3.3 TCP 重组不区分方向 —— 双向有负载时补出巨量空洞

`capture.dump_tcp_segments` 只按 `tcp.stream` 分组（`capture.py:370`），不区分 A→B / B→A：

```python
entry = streams.setdefault(sid, {'segs': {}, 'meta': {}})
entry['segs'][seq] = data
```

`reassemble_tcp` 遇到 `seq > last` 就补零。实测两个方向各 200 字节：

```
合并后长度 = 4200 字节（正确应分成两条独立的 200 字节流）
```

**后果**
- 内存与解析时间被空洞放大（取决于两端 ISN 差值，可达数 GB 量级）。
- 补零后的 `parse_rfc4571` 可能把对向流量里的字节误判为对齐偏移，导致抓到错误的流。
- 反向如果有 RTCP/信令复用同一连接，会被当成 RTP 垃圾。

**修复**：分组键改为 `(tcp.stream, src_ip, src_port, dst_ip, dst_port)`；`meta` 一并按方向存。

### 3.4 AI 接口把 DB Session 传给后台线程

`api/ai.py:84` / `133`：`ai.analyze(db, ...)` 在 `threading.Thread` 内使用 FastAPI 依赖注入的 `Session`。SQLAlchemy `Session` 非线程安全，且该 Session 在 `get_db` 的 `finally` 里随请求结束被关闭。

**风险**：并发 AI 请求下偶发 `This session is provisioning a new connection` / 脏读。目前单用户本地使用不易复现，但是明确的错误用法。

**修复**：worker 内自建 `SessionLocal()`，请求线程只做校验。

### 3.5 配置体系未生效：`.env.example` 是摆设

`requirements.txt` 声明了 `pydantic-settings`，`backend/.env.example` 也写了完整的配置项，
但 `core/config.py` 全部用裸 `os.environ.get()`，**从未加载 `.env`**：

```bash
$ grep -rn "pydantic_settings|BaseSettings|dotenv" backend/app
（无结果）
```

**后果**
- 用户按 README 复制 `.env.example` 为 `.env` 后，配置**完全不生效**，且没有任何提示。
- `.env.example` 里写的是 `DATABASE_URL=sqlite:///../data/analyzer.db`（相对路径），
  而 `config.py` 的默认值是 `PROJECT_DIR/data/analyzer.db`（绝对路径）。
  一旦真的加载了 `.env`，相对路径会按**进程工作目录**解析 —— 从 `backend/` 启动会指向
  `Documents/data/analyzer.db`，与默认位置不同，形成两个数据库。
- `pydantic-settings` 是纯冗余依赖。

**修复**：改用 `pydantic_settings.BaseSettings` + `model_config = SettingsConfigDict(env_file='.env')`；
`.env.example` 的相对路径改成绝对语义（或明确注释「相对 backend/」并在加载时 `resolve()`）；
两者择一，不要留半套。

### 3.6 前端

| 问题 | 证据 | 影响 |
|---|---|---|
| `/tasks/:id` 路由不存在 | `TasksView.vue:76` push，`router/index.js` 无此路由、无 catch-all | 点历史任务 → 白屏 |
| `cancelled` 状态无渲染分支 | `WorkbenchView.vue:623/652/661` 只处理 analyzing/failed/completed | 取消后整页空白 |
| 52 处 CSS 变量未定义 | `--panel/-2/-3`、`--accent`、`--border` 等，`theme.css` 0 处定义 | 6 个页面面板透明、无边框、错误框无色 |
| `--line-2: #26324300` | `theme.css:72`，alpha=00 | 暗色下所有按钮/输入框/表格边框透明 |
| ECharts 全量引入 | 构建产物 `index-8VjjxCB0.js` = **1036 KB**（gzip 343 KB） | 首屏体积可降 60%+ |
| 切任务无竞态保护 | `WorkbenchView.vue:551` watch 直接 `loadAll()` | 旧任务数据覆盖新任务 |
| N+1 请求 | 30 会话 × 2 请求 = 61 次；`MediaView` 最多 101 次 | 慢、且 `Promise.all` 一处失败全页空 |
| AI 逻辑重复约 350 行 | `AiPanel.vue` 887 行 vs `AiSummarySection.vue` 800 行 | 维护成本翻倍 |
| 前端 0 测试、无 lint | `package.json` 只有 dev/build/preview | 上述问题无一道防线 |

Markdown 渲染器（`utils/markdown.js`）经逐行审查**无 XSS 路径**：`inline()` 首行即 `esc()`，所有出口都经转义。这点做得对，但需加回归测试锁住。

### 3.7 CI 拦不住任何真实回归

| 事实 | 后果 |
|---|---|
| 后端 CI 只跑 `pytest tests/`（42 个纯解析器单测）+ `compileall` | `capture` / `ps_parser` / `rebuild` / `analyzer` / `retention` / 全部 `api/*` 覆盖率 **0%**，这些层的任何回归都拦不住 |
| ubuntu-24.04 runner **没有** tshark / ffmpeg | 核心分析链路在 CI 里从未执行过；能过 CI 只说明解析器函数没坏 |
| hygiene 大文件步骤有 bug | `git ls-files` 默认 `core.quotePath=true`，中文路径被输出为 `"docs/samples/8\346..."`，`wc -c < "$f"` 找不到文件 → `[: : integer expected`，但发生在 `sz=$(...)` 的管道末端，GHA 默认 `bash -e` 下**退出码仍为 0**，文件被静默跳过 |
| 敏感文件检查遗漏 | 只查 `ai_config.json` / `*.db` / `data/uploads` / `node_modules`，漏掉 `.env`、`*.pcap`、`frontend/dist/`、`.coverage` |
| 无 `permissions` / `concurrency` / `timeout-minutes` | 默认 GITHUB_TOKEN 权限过宽；连续推送会并行跑多份；卡住的 job 会跑满 6 小时 |

**修复**：hygiene 改用 `git -c core.quotePath=false ls-files -z` + `read -r -d ''`；
补敏感文件规则；加 `permissions: contents: read`、`concurrency`、`timeout-minutes`；
新增一个 `integration` job，`apt-get install -y tshark ffmpeg` 后用 `tests/fixtures/` 跑端到端。

### 3.8 索引设计与查询模式不匹配

`packet_index` 上有 9 个索引（含 `task_id`、`packet_number`、`timestamp` 单列索引与一个复合索引），
但实际查询（`api/diagnostics.py:83-99`）全部是 `task_id + X` 形式。

实测 `EXPLAIN QUERY PLAN`（15 万行 / 3 任务）：

```
ip / port / protocol / session_id / call_id 过滤
→ 全部 SEARCH ... USING INDEX ix_packet_task_number (task_id=?)
→ 命中 5 万行后逐行过滤
```

`source_port` / `destination_port` / `protocol` 甚至**完全没有索引**。

**修复**：改成 `(task_id, packet_number)`、`(task_id, source_ip)`、`(task_id, destination_ip)`、
`(task_id, session_id)`、`(task_id, call_id)` 复合索引，删掉低选择性的单列索引（同时降低批量插入写放大）。

### 3.9 时间戳无时区，前端显示差 8 小时

DB 存 naive UTC，Pydantic 序列化出来是 `"2026-11-18T08:26:37"`（无 `Z`），
前端 `new Date(...).toLocaleString()` 按**本地时区**解析 → UTC+8 下显示 08:26（实际应为 16:26）。

**修复**：统一 `datetime.now(timezone.utc)`（注意项目声明支持 3.10，不能用 3.11+ 的 `datetime.UTC`），
序列化带 `Z`；前端显式按 UTC 解析。

### 3.10 安全边界（本地单用户可接受，但需写清）

| 项 | 现状 | 风险 |
|---|---|---|
| 鉴权 | 无 | 一旦 `HOST=0.0.0.0`，上传/分析/删除/改 Key 全部对外开放 |
| Host 校验 | 无 `TrustedHostMiddleware` | DNS rebinding 可绕过 CORS；无 body 的 POST 是「简单请求」，可被 CSRF |
| AI Key | `data/ai_config.json` 明文，Windows 实测 mode **0666** | 同机其他用户可读 |
| AI `base_url` | 可设为任意地址（实测接受 `http://169.254.169.254/latest`） | SSRF + Key 外泄 |
| 上传 | 只校验扩展名，不校验魔数；先落临时盘再计数 | `MAX_UPLOAD_MB` 挡不住请求体先写满磁盘 |

**已确认安全的部分**：上传路径（`basename` + 正则 + UUID 前缀，实测 `..\..\evil.pcap` 未逃逸）；
`_safe_media_path`（`realpath` + `commonpath`，实测同前缀兄弟目录被正确拦截）；
SQLite 外键与 WAL（实测 `foreign_keys=1`、`journal_mode=wal`）。

**修复**：非 loopback 绑定时打 warning 或要求 token；加 Host 白名单；Key 文件 `chmod 0600`；
`base_url` 限 https + 域名白名单；上传前置 `Content-Length` 检查 + 魔数校验。

---

## 四、迭代方案

### 阶段 0：可信度修复（1-2 天，无新功能）

> 目标：让工具给出的每个数字都是对的。这是专业分析工具的生命线，优先于任何新功能。

| # | 内容 | 验证方式 | 状态 |
|---|---|---|---|
| 1 | SDP 顶层 `y=` / `f=` 解析 | 新增单测：国标独立行写法 | ✅ 已完成 |
| 2 | `dialog_key` 排序一致 | 新增单测：INVITE 请求可回填 | 待办 |
| 3 | 乱序/缺口分离计算 | 新增单测：`1,2,4,3,5,6` → gap=1 | 待办 |
| 4 | RFC4571 长度上限 65535 + truncated 标记 | 新增单测：4000 字节包 | 待办 |
| 5 | 取消真正生效 | 新增单测：cancelled 不被覆盖 | ✅ 已完成 |
| 6 | SIP 抽取补 TCP 端口 | 用 `tests/fixtures/sip-tcp-register.pcap` | 待办 |
| 7 | 空 SIP 消息过滤（握手空包不入库） | 同上，断言只入库 2 条 | 待办 |
| 8 | PS 帧计数按 AU 边界 | 用真实 H.265 PS 样本 | 待办 |
| 9 | 重建不缩放 + `source_codec` 分离 | ffprobe 断言 | 待办 |
| 10 | `RULES` 标注实现状态、注释对齐 | `/rules` 断言 12 条 | 待办 |
| 11 | README 已知限制重写 | 人工核对 | 待办 |
| 12 | `sip_dialog.session_id` 回填 | `BusinessSession.dialogs` 非空 | 待办 |
| 13 | `packet_index` 回填 `ssrc`/`session_id`，或删除字段 | API 过滤断言 | 待办 |
| 14 | `related_packet_ids` 落地（至少 SIP 与 MED-002） | 诊断结果非空断言 | 待办 |
| 15 | 诊断列表在 SQL 里排序后再分页 | 断言第 1 页含 critical | 待办 |
| 16 | 修 `traceback` 局部变量导致的 `UnboundLocalError`，改用 logger | 断言失败时能拿到真实异常 | ✅ 已完成 |
| 17 | 重分析前校验原文件存在，不存在则 409（不删旧结果） | 断言失败后旧数据仍在 | ✅ 已完成 |
| 18 | 同任务并发触发去重（`_running` 直接 409，锁内原子占坑） | 3 并发 → 只启 1 个 worker | ✅ 已完成 |

**同时**：把自建抓包固化为 `backend/tests/fixtures/`（SIP/UDP、SIP/TCP、TCP+RFC4571 已放入，见该目录 README），
让 CI 能跑端到端。注意：**端到端仍依赖 tshark**（`capture.py` 全部走 tshark），
所以 CI 需 `apt-get install tshark` 或把解析器纯函数化后直接喂字节 —— 后者更彻底，建议随阶段 0 一起做。
当前实现是前者：`tests/test_e2e_fixtures.py` 在无 tshark 时 `skip`，CI 尚未安装 tshark。

### 阶段 1：工程化护栏（1 天）

- `pytest-cov` 接入，解析器/诊断/analyzer 覆盖率门槛 80%；当前总体 **67%**（本轮从 22% 提升），
  `rebuild`/`ai`/`retention`/`api` 仍是短板。
- 新增 `conftest.py`：临时 `DATA_DIR` / `DATABASE_URL` 的 fixture，让 API 与 analyzer 测试不碰真实数据。✅ 已完成
- ruff + 配置入仓（当前 220 条告警，先 `--fix` 44 条安全的，其余逐条决策）；`F401/F841` 现有 13 处，先清零。
- 前端 ESLint + Prettier + Vitest；CI 增加 `lint` / `test`。
- requirements 锁定上限 + lock 文件（`pip-compile` 或 `uv lock`），拆分 `requirements-dev.txt`（`pytest`/`httpx` 目前混在运行依赖里）；删掉未使用的 `pydantic-settings`（或按 3.5 真正启用）。
- `datetime.utcnow()` → `datetime.now(timezone.utc)`（实测 Python 3.14 已抛 `DeprecationWarning`，共 9 处）。
- 补 `Dockerfile` + `docker-compose.yml`（CI 里 `docker build` 验证，不依赖本机 Docker）；加 `.gitattributes`（`*.sh text eol=lf`、`*.pcap binary` —— `start-dev.sh` 实测是 CRLF，Linux 下会 `bad interpreter`）。
- CI hygiene job 按 3.7 重写（`quotePath=false` + `-z` 读取、补敏感文件规则、加 `permissions`/`concurrency`/`timeout-minutes`）。
- 新增 `integration` job：`apt-get install -y tshark ffmpeg`，用 `tests/fixtures/` 跑端到端。

### 阶段 2：性能（1 天）

- 删除 `_tcp_time_spread`（改用 `dump_tcp_segments` 已取的时间），省掉 N 次全量扫描。
- `dump_tcp_segments` 按方向分组（`stream + 五元组`），修掉双向合并补零的问题。
- `extract_fields` 流式化；`analyzer` 不再保留全量 `packets` 列表（只留计数与首末时间），解决大包 OOM。
- 合并 `iter_packets` 与 SIP 字段抽取为单次 tshark 调用。
- `rebuild` 按 CPU 核数并发（当前硬编码 3）。
- 前端 ECharts 按需引入 + `manualChunks`，目标首屏 gzip < 120 KB。
- 前端任务级数据缓存（按 `taskId`），消除路由切换全量重取。

### 阶段 3：功能补齐（按价值排序）

1. **RTCP 分析**（M07 缺口）：丢包率/往返时延/接收端报告，字段已在模型里。
2. **报告导出**（M13）：HTML 单文件 + JSON + CSV，复用现有 KPI/诊断结构。
3. **设备拓扑图**（M11）：`Device` / `Endpoint` 数据已入库，只差前端。
4. **分片上传**：2GB 上限对大型抓包不够；`tus` 或简单分片 + 断点续传。
5. **实时采集**：接 `dumpcap` 管道，替代「先存盘再上传」。
6. **RTP 原始包导出**：把单条流导出为 `.pcap`，便于交给 Wireshark 复核（这是分析工具可信度的关键一环）。

### 阶段 4：架构演进（可选，视使用规模）

- **Alembic 基线**（当前 `create_all` 不会给已有库加列/索引，升级用户会撞 `no such column`）；
  同时把 `Enum` 改为 `values_callable` 存 value（现在 DB 存 `COMPLETED`，API 返回 `completed`）。
- 分析任务队列化（`arq` / `RQ`），替代裸 `threading.Thread`，天然支持并发上限、取消、重试、进度上报。
- 大文件场景评估 DuckDB / Parquet 存 `packet_index`（SQLite 单表 2000 万行后查询会退化）。
- 结构化日志（文件 + 滚动 + `task_id` 关联），替换散落的 `traceback.print_exc()`；
  默认 `DEBUG=0`（现在是 1，且 `reload=settings.DEBUG`，`python -m app.main` 也会开 reload）。
- `lifespan` shutdown：标记运行中任务失败，避免 daemon 线程被直接杀死后留下孤儿 tshark/ffmpeg。

---

## 五、验证策略

本次分析已经验证到的、以及后续每轮迭代应保持的验证方式：

| 层 | 手段 | 是否需要 tshark/ffmpeg |
|---|---|---|
| 解析器纯函数（SDP / SIP / RTP / PS / SPS） | 单元测试，直接喂字节 | 否 |
| 抓包读取（`capture.py`） | 用 `tests/fixtures/*.pcap` 端到端 | **是** |
| 分析编排（`analyzer.py`） | mock `capture.*`，只验流程与状态机 | 否 |
| API / 路由 / 分页 / 枚举 | `TestClient` + 临时 DB | 否 |
| 并发 / 取消 / 僵尸任务 | 多线程 + mock analyzer | 否 |
| 视频重建 | 真实 PS 样本 + `ffprobe` 断言 | **是** |
| 前端逻辑 | Vitest（markdown / api / store） | 否 |

**关键原则**：CI 里能跑的部分要跑满；必须依赖外部程序的部分单独一个 job，
用 `pytest.mark.skipif(not capture.TSHARK)` 标记，本地开发时自动跳过、CI 的 integration job 里全跑。

---

## 六、优先级建议

```
阶段 0（可信度） → 阶段 1（护栏） → 阶段 2（性能） → 阶段 3（功能）
```

理由：阶段 0 的 18 项里，有 13 项是「静默给出错误结论」。功能越多，错误结论被采信的概率越高。而阶段 1 的护栏能防止阶段 0 的修复被后续迭代重新破坏 —— 这两步合起来才形成正循环。

阶段 2 的收益立竿见影（删一个函数就能省掉 N 次全量扫描），但**必须排在阶段 0 之后**，否则性能优化会把还没修的语义 bug 一起「优化」进更深的抽象层。

### 建议的第一个迭代（1 天，只做三件事）✅ 已完成

如果只能先做一天，按这个顺序：

1. **修 `traceback` 作用域 bug**（P0-16）—— 10 分钟，但在此之前**所有分析失败都没有可读的栈**，等于后续排查全靠猜。
2. **重分析前校验原文件**（P0-17）+ **同任务并发去重**（P0-18）—— 各约 10 行，消除两类「数据不可逆损坏」。
3. **补 `conftest.py` + 3 个 API 测试**（并发触发 / 取消 / 重分析失败）—— 把上面两条锁住。

这三件事做完，项目从「跑起来能用」变成「失败时能查、数据不会静默丢失」。
之后再进 P0-1 ~ P0-15 的解析正确性修复。

实际执行（2026-11-18，PR #9）在上面三项之外顺带做了 P0-1（`y=`/`f=` 解析）
与 P0-5（取消生效），因为它们在同一个文件里、改动同样小。
测试数 42 → 79，覆盖率 22% → 67%。

### 建议的第二个迭代（2-3 天，输出数值的正确性）

这一批**会改变工具给出的数字**，每一项都必须先有对照样本再改：

1. P0-2 `dialog_key` 排序（INVITE 回填）+ P0-12 `sip_dialog.session_id` 回填 —— 会话时序图的前提。
2. P0-3 乱序与缺口分离 —— 直接决定丢包率与 `MED-002` 定级，**优先级最高的一项数值修复**。
3. P0-4 RFC4571 长度上限 65535 + `truncated` 标记 —— 当前大包被静默丢弃，TCP 场景统计数据偏小。
4. P0-8 PS 帧计数按 AU 边界 —— 帧数/帧率/码率全链路依赖它。
5. P0-15 诊断列表在 SQL 里排序后再分页 —— 否则第一页可能看不到 critical。

### 建议的第三个迭代（1 天，对外诚实）

P0-10（`RULES` 实现状态）、P0-11（README 已知限制）、P0-6/P0-7（TCP 承载 SIP）、
P0-13/P0-14（字段回填或删除）。这一批不改变分析能力，但决定用户会不会被误导。

---

## 七、明确不做

- 不为了让数字好看而放宽判定阈值。
- 不在没有真实抓包验证的情况下宣称支持某协议特性（这正是 P0-1 的教训：文档写了 `y=` 支持，代码其实没解析）。
- 不用模拟数据填充缺失字段。
