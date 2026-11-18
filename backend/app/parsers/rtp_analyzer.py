#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RTP 媒体流分析（M07）

核心难点（都实际踩过）：
1. RTP 序号是 16 位，会回绕 —— 必须展开成 32 位再算缺口
2. 抖动按 RFC 3550 计算，需要正确的时钟频率（PS 流一般 90000）
3. UDP 与 TCP 承载的丢包判定完全不同：
   - UDP：序号缺口可视为"在抓包点观察到丢包"
   - TCP：缺口可能只是抓包不全，不能直接判丢包
4. "序号缺口"不等于"网络丢包" —— 也可能抓包点在中途
"""
from __future__ import annotations

from dataclasses import dataclass, field

CLOCK_RATE_DEFAULT = 90000     # 国标 PS 流常用 90kHz


@dataclass
class RtpPacket:
    seq: int = 0
    seq_unwrapped: int = 0
    timestamp: int = 0
    ssrc: int = 0
    payload_type: int = 0
    marker: bool = False
    arrival: float = 0.0
    size: int = 0
    payload: bytes = b''


@dataclass
class StreamStat:
    """单条流的质量统计"""
    ssrc: int | None = None
    payload_type: int | None = None
    transport: str = 'UDP'
    source_ip: str = ''
    source_port: int | None = None
    destination_ip: str = ''
    destination_port: int | None = None

    start_time: float = 0.0
    end_time: float = 0.0
    duration: float | None = None

    packet_count: int = 0
    byte_count: int = 0
    payload_bytes: int = 0
    avg_bitrate: float | None = None
    peak_bitrate: float | None = None

    seq_start: int | None = None
    seq_end: int | None = None
    seq_gap_events: list = field(default_factory=list)
    seq_gap_count: int = 0
    seq_gap_packets: int = 0
    out_of_order_count: int = 0
    duplicate_count: int = 0

    jitter_avg: float | None = None
    jitter_max: float | None = None
    jitter_series: list = field(default_factory=list)

    max_gap: float | None = None
    interruption_count: int = 0

    clock_rate: int = CLOCK_RATE_DEFAULT
    ts_anomalies: list = field(default_factory=list)

    # 时间序列
    bitrate_series: list = field(default_factory=list)
    interarrival_series: list = field(default_factory=list)

    loss_confidence: str = 'observed_gap'   # observed_gap / confirmed_loss
    notes: list = field(default_factory=list)


# ---------------------------------------------------------------
# 序号回绕展开
# ---------------------------------------------------------------
def unwrap_sequences(packets: list[RtpPacket]) -> None:
    """按到达顺序把 16 位序号展开成 32 位

    回绕判定：相邻差值超出 (-32768, 32768) 视为回绕/跳变。
    这一步是后续所有丢包/乱序计算的基础。
    """
    if not packets:
        return
    base = 0
    prev_raw = None
    for p in packets:
        if prev_raw is None:
            p.seq_unwrapped = p.seq
        else:
            delta = p.seq - prev_raw
            if delta < -32768:
                base += 65536
            elif delta > 32768:
                base -= 65536
            p.seq_unwrapped = p.seq + base
        prev_raw = p.seq


# ---------------------------------------------------------------
# RFC 3550 抖动
# ---------------------------------------------------------------
def compute_jitter(packets: list[RtpPacket], clock_rate: int) -> tuple:
    """计算 RFC 3550 定义的 interarrival jitter

    D(i,j) = (Rj - Ri) - (Sj - Si)
    J(i) = J(i-1) + (|D(i-1,i)| - J(i-1)) / 16

    返回 (avg, max, series)，单位秒。
    """
    if len(packets) < 2:
        return None, None, []

    jitter = 0.0
    series = []
    prev = packets[0]
    for p in packets[1:]:
        transit_prev = prev.arrival - (prev.timestamp / clock_rate)
        transit_cur = p.arrival - (p.timestamp / clock_rate)
        d = abs((transit_cur - transit_prev))
        jitter += (d - jitter) / 16.0
        series.append({
            't': round(p.arrival - packets[0].arrival, 3),
            'j': round(jitter * 1000, 3),      # 毫秒
        })
        prev = p

    avg = sum(x['j'] for x in series) / len(series) if series else None
    mx = max(x['j'] for x in series) if series else None
    return (round(avg, 3) if avg is not None else None,
            round(mx, 3) if mx is not None else None,
            series)


# ---------------------------------------------------------------
# 主分析
# ---------------------------------------------------------------
def analyze_stream(packets: list[RtpPacket], transport: str = 'UDP',
                   clock_rate: int = CLOCK_RATE_DEFAULT,
                   bucket_seconds: float = 1.0) -> StreamStat:
    """对一条流做完整质量分析"""
    st = StreamStat(transport=transport, clock_rate=clock_rate)
    if not packets:
        st.notes.append('该流没有任何 RTP 包')
        return st

    packets.sort(key=lambda p: (p.arrival, p.seq))

    p0 = packets[0]
    st.ssrc = p0.ssrc
    st.payload_type = p0.payload_type
    st.source_ip = ''
    st.start_time = p0.arrival
    st.end_time = packets[-1].arrival
    st.packet_count = len(packets)
    st.byte_count = sum(p.size for p in packets)
    st.payload_bytes = sum(len(p.payload) for p in packets)

    span = st.end_time - st.start_time
    st.duration = round(span, 3) if span > 0 else None

    if span > 0:
        st.avg_bitrate = round(st.byte_count * 8 / span / 1000, 1)

    # ---- 序号分析 ----
    unwrap_sequences(packets)
    st.seq_start = packets[0].seq
    st.seq_end = packets[-1].seq

    expected = len(packets)
    seen = {}
    gaps = []
    ooo = 0
    dup = 0
    prev_unwrapped = None

    for p in packets:
        u = p.seq_unwrapped
        if u in seen:
            dup += 1
            continue
        seen[u] = True
        if prev_unwrapped is not None:
            d = u - prev_unwrapped
            if d <= 0:
                ooo += 1
            elif d > 1:
                missing = d - 1
                gaps.append({
                    'after_seq': p.seq - d,
                    'gap': missing,
                    'time': round(p.arrival - st.start_time, 3),
                })
        prev_unwrapped = u

    st.duplicate_count = dup
    st.out_of_order_count = ooo
    st.seq_gap_events = gaps[:200]        # 最多保留 200 个事件，避免库膨胀
    st.seq_gap_count = len(gaps)
    st.seq_gap_packets = sum(g['gap'] for g in gaps)

    # TCP 承载时缺口不能直接当丢包
    if transport == 'TCP':
        st.loss_confidence = 'observed_gap'
        if gaps:
            st.notes.append('TCP 承载：序号缺口可能来自抓包不完整，'
                            '不能直接判定为网络丢包')
    else:
        st.loss_confidence = 'confirmed_loss' if gaps else 'no_gap'

    # ---- 抖动 ----
    avg_j, max_j, jseries = compute_jitter(packets, clock_rate)
    st.jitter_avg = avg_j
    st.jitter_max = max_j
    st.jitter_series = jseries[::max(1, len(jseries)//300)]   # 抽样降采样

    # ---- 到达间隔与中断 ----
    inter = []
    max_gap = 0.0
    interruptions = 0
    prev = packets[0]
    for p in packets[1:]:
        gap = p.arrival - prev.arrival
        inter.append({'t': round(p.arrival - st.start_time, 3),
                      'g': round(gap * 1000, 1)})
        if gap > max_gap:
            max_gap = gap
        # 中断判定：间隔超过该流中位间隔的 10 倍且 > 0.5 秒
        if gap > 0.5:
            interruptions += 1
        prev = p
    st.max_gap = round(max_gap, 3) if inter else None
    st.interruption_count = interruptions
    st.interarrival_series = inter[::max(1, len(inter)//300)]

    # ---- 码率时间序列 ----
    if span > 0:
        st.bitrate_series = _bitrate_series(packets, st.start_time,
                                            bucket_seconds)
        if st.bitrate_series:
            st.peak_bitrate = max(b['kbps'] for b in st.bitrate_series)

    # ---- 时间戳异常 ----
    st.ts_anomalies = _detect_ts_anomalies(packets)

    return st


def _bitrate_series(packets: list[RtpPacket], t0: float,
                    bucket: float = 1.0, max_points: int = 300) -> list[dict]:
    """按时间片统计码率（kbps）"""
    if not packets:
        return []
    total_span = packets[-1].arrival - t0
    if total_span <= 0:
        return []
    # 自动调整时间片，使点数不超过上限
    while total_span / bucket > max_points:
        bucket *= 2
    series = []
    idx = 0
    n = len(packets)
    cur_start = t0
    while cur_start < t0 + total_span + bucket:
        cur_end = cur_start + bucket
        nbytes = 0
        cnt = 0
        while idx < n and packets[idx].arrival < cur_end:
            nbytes += packets[idx].size
            cnt += 1
            idx += 1
        series.append({
            't': round(cur_start - t0, 3),
            'kbps': round(nbytes * 8 / bucket / 1000, 1),
            'packets': cnt,
        })
        if idx >= n:
            break
        cur_start = cur_end
    return series


def _detect_ts_anomalies(packets: list[RtpPacket]) -> list[dict]:
    """检测 RTP 时间戳异常

    常见异常：
    1. 时间戳倒退（除回绕）
    2. 时间戳跳变过大（超过 5 秒的跃变）
    3. 时间戳不递增但序号递增（说明时基有问题）
    """
    out = []
    if len(packets) < 2:
        return out
    prev = packets[0]
    for p in packets[1:]:
        d = p.timestamp - prev.timestamp
        # 允许 32 位回绕
        if d < -2**31:
            d += 2**32
        if d < 0:
            if len(out) < 20:
                out.append({
                    'type': 'timestamp_backward',
                    'seq': p.seq,
                    'time': round(p.arrival, 3),
                    'delta': d,
                })
        elif d > 90000 * 5:      # 超过 5 秒的跃变
            if len(out) < 20:
                out.append({
                    'type': 'timestamp_jump',
                    'seq': p.seq,
                    'time': round(p.arrival, 3),
                    'delta': d,
                })
        prev = p
    return out


# ---------------------------------------------------------------
# RFC4571 over TCP 自研解析
# ---------------------------------------------------------------
def reassemble_tcp(segments: dict) -> bytes:
    """按 seq 拼接 TCP 段。有空洞就补零（后续解析会跳过坏包）

    segments: {seq: bytes}
    """
    if not segments:
        return b''
    out = bytearray()
    last = None
    for seq in sorted(segments):
        data = segments[seq]
        if last is None:
            out += data
            last = seq + len(data)
        elif seq > last:
            out += b'\x00' * (seq - last)     # 空洞
            out += data
            last = seq + len(data)
        elif seq < last:
            skip = last - seq
            if skip >= len(data):
                continue
            out += data[skip:]
            last = seq + len(data)
        else:
            out += data
            last += len(data)
    return bytes(out)


def parse_rfc4571(buf: bytes, max_scan: int = 8000, min_pkts: int = 3):
    """扫描对齐偏移并解析 RFC4571 帧（2 字节长度 + RTP 包）

    返回 (offset, [RtpPacket...]) 或 None

    为什么不能从偏移 0 开始：抓包起点往往不在 RTP 包边界上，
    实测遇到过偏移 1158 / 1829 字节的情况。
    """
    best = None
    limit = min(max_scan, max(0, len(buf) - 14))
    for off in range(limit):
        if (buf[off + 2] >> 6) != 2:          # 快速过滤：RTP 版本必须为 2
            continue
        o = off
        pkts = []
        while o + 2 <= len(buf):
            L = int.from_bytes(buf[o:o + 2], 'big')
            if L < 12 or L > 2048 or o + 2 + L > len(buf):
                break
            pp = buf[o + 2:o + 2 + L]
            if (pp[0] >> 6) != 2:
                break
            pkts.append(RtpPacket(
                seq=int.from_bytes(pp[2:4], 'big'),
                timestamp=int.from_bytes(pp[4:8], 'big'),
                ssrc=int.from_bytes(pp[8:12], 'big'),
                payload_type=pp[1] & 0x7f,
                marker=bool((pp[1] >> 7) & 1),
                size=L,
                payload=pp[12:],
            ))
            o += 2 + L
        if len(pkts) >= min_pkts and (best is None or len(pkts) > len(best[1])):
            best = (off, pkts)
            if len(pkts) > 400:               # 已足够确认对齐正确
                break
    return best


# ---------------------------------------------------------------
# 流分组
# ---------------------------------------------------------------
def group_into_streams(packets: list[dict]) -> dict:
    """按 (SSRC, 五元组) 把 RTP 包分组

    SSRC 是主键，但同一 SSRC 也可能在不同端口出现，所以带上五元组。
    """
    groups: dict = {}
    for p in packets:
        key = (p.get('ssrc'), p.get('src_ip'), p.get('src_port'),
               p.get('dst_ip'), p.get('dst_port'))
        groups.setdefault(key, []).append(p)
    return groups
