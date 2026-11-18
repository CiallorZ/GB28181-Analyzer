# 测试样本（fixtures）

本目录的抓包由 `make_*.py` 生成，**内容完全确定**，可直接用于断言。

生成方式（需要 Python 3.10+，无需 tshark）：

```bash
python make_sip_udp_basic.py sip-udp-basic.pcap
python make_tcp_rfc4571.py tcp-rfc4571-media.pcap
```

`sip-tcp-register.pcap` 由 `make_sip_udp_basic.py` 里的 TCP 部分逻辑产生，
见 `tests/test_fixtures.py` 的说明；它是手工构造的 TCP 三次握手 + 1 条 REGISTER 及其 200 OK。

## 样本清单

| 文件 | 内容 | 用途 |
|---|---|---|
| `sip-udp-basic.pcap` | 126 报文。1 个完整 INVITE 事务（100/200/ACK）+ 120 个 UDP RTP/PS 包（SSRC `0x00001234`，H.264 1280×720 占位码流）+ BYE 事务 | 端到端：会话重建、媒体关联、首媒体耗时、诊断 |
| `sip-tcp-register.pcap` | 4 报文。TCP 三次握手（SYN / SYN-ACK）+ 1 条 REGISTER 及其 200 OK | 回归：TCP 承载 SIP 的端口抽取、握手空包不应入为 SIP 消息 |
| `tcp-rfc4571-media.pcap` | 43 报文。TCP 承载 RTP，`[2字节长度][RTP]` 封装，**首个段带 1200 字节非对齐前缀** | 回归：RFC4571 对齐扫描、大包（>2048 字节）不应截断 |

## 已知的预期结果（用于回归）

`sip-udp-basic.pcap`：

```
会话 1 个，signal=success，media=received，first_media_latency≈0.24s
subject_ssrc = '00001234'
sdp_y_ssrc   = '00005678'    ← 取自 200 OK 的 answer（见下方说明）
媒体流 1 条，120 包，关联到会话 #1
诊断：MED-008（重建失败，因为样本码流是占位数据，非真实 H.264）
```

## `y=` 三种写法

| SDP 写法 | 是否标准 | 解析结果 |
|---|---|---|
| `y=0100000001`（顶层独立行） | **是**（GB/T 28181 附录 F） | ✅ `y_ssrc = '0100000001'` |
| `a=y=00001234` | 否（常见误写） | ✅ `y_ssrc = '00001234'` |
| `a=y:00001234` | 否（仅冒号写法） | ✅ `y_ssrc = '00001234'` |

历史上只处理 `a=` 分支，导致**标准写法解析不出来、只有非标准的冒号写法能解析**。
现已三种都支持，回归见 `tests/test_sdp_fields.py`。

本样本刻意两种写法混用：offer 用标准 `y=` 行（另带 `f=`），
answer 用非标准 `a=y=`。端到端跑完应能同时拿到 `y_ssrc` 与 `f_field`。

`tcp-rfc4571-media.pcap`：

```
媒体流 1 条，transport=TCP，150 个 RTP 包全部解析（含 1200 字节非对齐前缀）
```

> 若把其中任一 RTP 包改为 >2048 字节，当前实现会在该处截断 —— 见 `test_rtp_rfc4571.py`。

## 为什么不把真实抓包放进来

真实抓包含客户内网 IP、设备 ID、SN 等敏感信息，且体积大。
本目录的样本是**结构真实、内容合成**的：字段名、编码、封装格式都按国标构造，
但 IP / 设备 ID / 码流内容都是占位值。
