# 架构说明（ARCHITECTURE）

## 一、整体分层

```
┌─────────────────────────────────────────────────────────┐
│  可视化层  Vue3 + ECharts + 原生 SVG                     │
│  Dashboard / 任务 / 会话 / 诊断 / 报文 / 设置             │
└───────────────────────┬─────────────────────────────────┘
                        │  /api/v1 (JSON, OpenAPI)
┌───────────────────────▼─────────────────────────────────┐
│  服务层  FastAPI                                          │
│  api/tasks  api/sessions  api/diagnostics                │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│  业务层  services/                                        │
│  analyzer.py   编排流水线、写进度、入库                    │
│  diagnosis.py  规则引擎、证据分级                          │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│  解析层  parsers/                                         │
│  capture.py          文件信息、报文索引、TCP 段导出         │
│  sip_parser.py       SIP 头/正文、SDP、国标 XML            │
│  session_builder.py  Dialog / 业务会话 / 媒体关联          │
│  rtp_analyzer.py     RTP 统计、RFC3550 抖动、RFC4571      │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│  数据层  SQLAlchemy 2.0 + SQLite（schema 兼容 PG）        │
└─────────────────────────────────────────────────────────┘
```

## 二、数据模型关系

```
AnalysisTask
  ├─ CaptureFile          抓包文件（1:1，预留多文件）
  ├─ PacketIndex          报文索引（1:N，支撑筛选与定位）
  ├─ SipMessage           每条 SIP 消息（1:N）
  │    └─ dialog_id ──┐
  ├─ SipDialog           SIP 对话（1:N）  ◄──┘
  │    └─ session_id ──┐
  ├─ BusinessSession     业务会话（1:N，一次点播）  ◄──┘
  │    ├─ SipDialog      可能多个
  │    └─ MediaStream    可能多条（1:N）
  │         └─ MediaMetric   时间序列指标（1:N）
  ├─ DiagnosticEvent     诊断事件（1:N，可挂 session/stream）
  ├─ Device              设备目录（来自 Catalog）
  └─ Endpoint            网络端点（拓扑用）
```

### 为什么这样设计

**不把 Call-ID 当会话主键。** 一个 Call-ID 下可能有多个事务（INVITE + BYE），
而一次业务会话可能涉及多个 Call-ID（例如先 SUBSCRIBE 再 INVITE）。
所以拆成三层：`SipMessage` → `SipDialog`（Call-ID + Tags）→ `BusinessSession`。

**信令与媒体状态分离。** `BusinessSession` 有两个独立枚举字段
`signal_status` 和 `media_status`，不合并。这是 PRD 1.3.4 的硬要求。

**指标字段全部可空。** 所有耗时/码率/抖动字段类型是 `Float | None`，
算不出来就是 `NULL`，前端渲染成「无法计算」。不允许填 0。

## 三、分析流水线

```
上传 → 建任务
  ↓
[5%]  读取文件信息     capinfos + 魔数识别
  ↓
[15%] 建立报文索引     tshark 流式输出，每 2000 条批量入库
  ↓
[30%] 解析 SIP         tshark 只给原始字节，本项目自己解头域
  ↓
[45%] 重建会话         Dialog 归并 → 业务会话 → 耗时计算
  ↓
[60%] 分析 RTP         UDP 直接读；TCP 走 RFC4571 自研重组
  ↓
      关联媒体         全局算分 + 贪心分配（一条流只归一个会话）
  ↓
[75%] 整理设备目录     从 Catalog / DeviceInfo 提取
  ↓
[85%] 执行诊断         21 条规则，带证据等级
  ↓
[95%] 生成汇总         KPI 与统计口径
  ↓
[100%] 完成
```

每个阶段都写 `progress` 与 `stage`，前端 1.2 秒轮询一次。

**长任务不阻塞 HTTP**：`POST /tasks/{id}/analyze` 立即返回，
分析在独立线程执行。不用 FastAPI 的 `BackgroundTasks`——
那个要等响应完全发出后才执行，大文件会拖住连接。

## 四、协议解析的关键决策

### 4.1 为什么不用 tshark 解析 SIP/RTP

tshark 的 SIP 解析会丢字段（`sip.msg_hdr` 不含起始行），
`rtp` 过滤器对 TCP 承载的 RTP 直接返回 0 包。

本项目的做法：**tshark 只做「取字节」，所有协议语义自己实现。**

```python
# capture.py 只负责这些
extract_fields(path, [...], filter)   # 按字段取原始值
dump_tcp_segments(path)               # 按 stream 导出 TCP 段
extract_udp_rtp(path)                 # UDP payload 原样返回

# 语义在 parsers 里
sip_parser.build_message(hdr, body, meta)
rtp_analyzer.parse_rfc4571(buf)
```

### 4.2 SIP 解析要点

| 问题 | 处理 |
|---|---|
| `msg_hdr` 不含起始行 | 单独取 `sip.Request-Line` / `sip.Status-Line` 拼回 |
| 正文多为 GB18030 | 依次尝试 gb18030 → utf-8 → latin-1 |
| 头域可折行 | 以空格/Tab 开头的续行并入上一行 |
| 头域有单字母别名 | `f`/`t`/`i`/`v`/`l` 映射到全名 |
| Dialog 需要 Tags | 请求侧 To-Tag 为空，用 Call-ID 分组后从响应补齐 |

### 4.3 SDP 解析要点

必须解析的国标扩展：

- `a=y:` — SSRC（十进制字符串，需与 Subject 比对）
- `a=f:` — 媒体源
- `a=setup:` — `passive` / `active` / `actpass`
- `a=connection:new` — 新建连接
- `a=streamprofile` — 码流类型（主/辅）

**容错**：`o=`/`c=` 字段不足时记录到 `errors`，不抛异常。
实测遇到过 `c=IN IP4` 后面地址缺失的畸形 SDP。

### 4.4 SDP 端口语义（最容易踩的坑）

```
INVITE offer:  m=video 8808 TCP/RTP/AVP 96
               a=setup:passive          ← 我监听 8808，你连我

200 OK answer: m=video 9    TCP/RTP/AVP 96
               a=setup:active           ← 端口 9 是占位，我主动连你
```

**answer 里的 9 不是真实端口。** 关联媒体时若只看 answer，
永远匹配不到实际连接的 8808。必须优先用 offer 端口，把 0/9 视为占位。

### 4.5 RFC4571 over TCP

格式：`[2字节大端长度][RTP 包][2字节长度][RTP 包]...`

难点：**抓包起点通常不在包边界上**。

算法：

```python
for offset in range(0, 8000):
    if (buf[offset+2] >> 6) != 2:      # RTP 版本必须为 2
        continue
    pkts = try_parse_from(buf, offset)
    if len(pkts) >= 3:
        return (offset, pkts)          # 第一个能连续解出 3 包以上的偏移
```

实测偏移 1158 / 1829 字节都能正确找到。

### 4.6 RTP 序号回绕

16 位序号，回绕后直接比较会误判大量丢包。

```python
if delta < -32768:  base += 65536
elif delta > 32768: base -= 65536
seq_unwrapped = seq + base
```

修复前 tcp0 只解出 4.4s/101 帧，修复后 8.88s/201 帧。

### 4.7 抖动计算

严格按 RFC 3550：

```
D(i,j) = (Rj - Ri) - (Sj - Si)      传输时间差
J(i)   = J(i-1) + (|D(i-1,i)| - J(i-1)) / 16
```

`R` 是到达时刻，`S` 是 RTP 时间戳除以时钟频率。
国标 PS 流时钟频率是 90000。

### 4.8 UDP 与 TCP 的丢包判定差异

| 承载 | 序号缺口的含义 |
|---|---|
| UDP | 大概率是真实丢包（`confirmed`） |
| TCP | 可能只是抓包不全，TCP 本身可靠（`insufficient`） |

诊断规则 `MED-002` 按 `transport` 字段切换等级与证据等级。

## 五、前端设计

### 5.1 信息密度优先

专业分析工具不是营销页面。原则：

- 深色优先，浅色可切换
- 表格行高 9px padding，能一屏看更多
- 指标用等宽数字（`font-variant-numeric: tabular-nums`）便于纵向对比
- 装饰性动画只保留状态指示（加载转圈、进度条）

### 5.2 状态色统一

| 语义 | 颜色 | 用途 |
|---|---|---|
| critical | `#f0453a` | 严重异常 |
| warning | `#f0a020` | 警告 |
| info | `#4a9eea` | 提示 |
| ok | `#2ecc71` | 正常 |
| unknown | `#7d8b9a` | 证据不足 |

所有页面统一，不因模块不同而变化。

### 5.3 SIP 时序图

用原生 SVG 而非图表库——时序图需要精确控制每条线的位置和点击区域。

- 参与方从消息里动态提取（不硬编码 IP）
- 每条消息一行，高度 26px
- 请求蓝色、2xx 绿色、4xx/5xx 红色
- 点击某行显示详情，可跳转到报文

### 5.4 「无法计算」的呈现

```vue
<div class="kpi-value" :class="summary.avg_first_media_latency == null ? 'na' : ''">
  {{ summary.avg_first_media_latency != null
      ? fmtNum(summary.avg_first_media_latency, 3)
      : '无法计算' }}
</div>
```

`na` 样式是灰色斜体，视觉上与数字明显区分。

## 六、错误处理

| 场景 | 行为 |
|---|---|
| 文件不是 pcap | 魔数检查 → 400 + 明确提示 |
| tshark 缺失 | 启动时告警，分析时 500 + 提示安装 Wireshark |
| 分析超时 | 每个外部进程都有 timeout，超时抛 `CaptureError` |
| 分析崩溃 | 写入 `error_message`，状态置 `failed`，不吞异常 |
| 服务重启 | 启动时清理遗留的 `analyzing` 僵尸任务 |
| 上传过大 | 边写边计数，超限立即中止并删除临时文件 |

## 七、安全边界

- 上传文件只读解析，**不执行**
- 外部程序一律列表传参，不用 `shell=True`，避免命令注入
- 文件名白名单过滤（`.pcap/.pcapng/.cap`），路径用 UUID 前缀防穿越
- 抓包原始内容不出本机（无外部 AI 调用）
- SQL 全部走 ORM，无字符串拼接

## 八、扩展点

| 扩展 | 位置 |
|---|---|
| 新诊断规则 | `services/diagnosis.py` 加函数 + `RULES` 注册 |
| 新协议解析 | `parsers/` 加模块，`analyzer._run` 加阶段 |
| 换数据库 | 改 `DATABASE_URL`，模型已 PG 兼容 |
| 加 RTCP | 模型已留字段，`rtp_analyzer` 加解析函数 |
| 视频重建 | `MediaStream.rebuilt_path` 已留字段 |
| 分片上传 | `api/tasks.upload_file` 改造 |
