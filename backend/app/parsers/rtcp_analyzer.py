#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RTCP SR/RR 解析与时钟关联

RTCP 提供的是"接收端自己的统计"，证据强度高于发送端按序号缺口推断：

- RR 的 Fraction Lost / Cumulative Lost：对端实际观察到的丢包；
- SR 的 NTP/RTP 对应关系：把 RTP 时间轴锚到墙钟；
- RR 的 LSR/DLSR：和抓到 SR 的时间差一起算 RTT，不依赖本机绝对时钟。

本模块只做纯字节解析，不依赖 tshark。analyzer 负责把采集到的 RTCP
载荷按到达时间喂进来，并把汇总写回 MediaStream.extra['rtcp']。
"""
from __future__ import annotations

from dataclasses import dataclass, field

NTP_EPOCH_OFFSET = 2208988800        # 1900-01-01 到 1970-01-01 的秒数
PT_SR = 200
PT_RR = 201
RTCP_TYPES = frozenset(range(200, 208))
REPORT_BLOCK_SIZE = 24


def _u16(b: bytes) -> int:
    return int.from_bytes(b, 'big')


def _signed24(b: bytes) -> int:
    v = int.from_bytes(b, 'big')
    return v - (1 << 24) if v & 0x800000 else v


def ntp_to_seconds(msw: int, lsw: int) -> float:
    """64 位 NTP 时间戳转 Unix 秒（浮点）"""
    return (msw - NTP_EPOCH_OFFSET) + lsw / (1 << 32)


def ntp_middle32(msw: int, lsw: int) -> int:
    """RTCP LSR 使用的 NTP 中间 32 位：低 16 位秒 + 高 16 位小数"""
    return ((msw & 0xFFFF) << 16) | (lsw >> 16)


@dataclass
class ReportBlock:
    """RR/SR 中的接收报告块"""
    ssrc: int = 0                 # 被报告的发送端 SSRC
    fraction_lost: int = 0        # 8 位定点小数，/256
    cumulative_lost: int = 0      # 24 位有符号
    highest_seq: int = 0
    jitter: int = 0               # RTP 时间戳单位
    lsr: int = 0                  # 最近一次 SR 的 NTP 中间 32 位
    dlsr: int = 0                 # 距最近一次 SR 的延迟，1/65536 秒

    @property
    def loss_percent(self) -> float:
        return round(self.fraction_lost * 100 / 256, 3)

    @property
    def dlsr_seconds(self) -> float:
        return self.dlsr / 65536.0


@dataclass
class RtcpPacket:
    pt: int = 0
    ssrc: int = 0                     # SR: 发送端；RR: 报告端
    arrival: float = 0.0
    # TCP 承载时没有逐帧时间戳，到达时间是从该方向的时间窗插值出来的。
    # 用它算的 RTT 只能当估算值，不能当作实测往返时延。
    arrival_estimated: bool = False
    source_ip: str | None = None      # 发包方，用来判断报告属于哪条流
    epoch: float | None = None        # 抓包机墙钟（Unix 秒），用于比对 SR 的 NTP
    ntp_seconds: float | None = None
    ntp_msw: int = 0
    ntp_lsw: int = 0
    rtp_timestamp: int | None = None
    sender_packet_count: int | None = None
    sender_octet_count: int | None = None
    report_blocks: list[ReportBlock] = field(default_factory=list)

    @property
    def middle32(self) -> int:
        return ntp_middle32(self.ntp_msw, self.ntp_lsw)


def _parse_report_blocks(body: bytes, count: int) -> list[ReportBlock]:
    blocks = []
    for i in range(count):
        start = i * REPORT_BLOCK_SIZE
        chunk = body[start:start + REPORT_BLOCK_SIZE]
        if len(chunk) < REPORT_BLOCK_SIZE:
            break
        blocks.append(ReportBlock(
            ssrc=int.from_bytes(chunk[0:4], 'big'),
            fraction_lost=chunk[4],
            cumulative_lost=_signed24(chunk[5:8]),
            highest_seq=int.from_bytes(chunk[8:12], 'big'),
            jitter=int.from_bytes(chunk[12:16], 'big'),
            lsr=int.from_bytes(chunk[16:20], 'big'),
            dlsr=int.from_bytes(chunk[20:24], 'big'),
        ))
    return blocks


def parse_compound(payload: bytes, arrival: float = 0.0,
                   source_ip: str | None = None,
                   epoch: float | None = None,
                   arrival_estimated: bool = False) -> list[RtcpPacket]:
    """解析一个 RTCP compound 包（可含多个 SR/RR/SDES...）

    截断或字段不足时停止解析当前包，但保留前面已经成功的部分；
    坏包不能影响同一抓包里其他 RTCP 统计。
    """
    out: list[RtcpPacket] = []
    offset = 0
    size = len(payload)
    while offset + 4 <= size:
        b0, pt = payload[offset], payload[offset + 1]
        if (b0 >> 6) != 2 or pt not in RTCP_TYPES:
            break
        length_words = _u16(payload[offset + 2:offset + 4])
        packet_len = (length_words + 1) * 4
        if packet_len < 4 or offset + packet_len > size:
            break
        pkt = payload[offset:offset + packet_len]
        rc = b0 & 0x1F
        if pt == PT_SR:
            if len(pkt) < 28:
                offset += packet_len
                continue
            p = RtcpPacket(
                pt=pt, ssrc=int.from_bytes(pkt[4:8], 'big'), arrival=arrival,
                arrival_estimated=arrival_estimated,
                source_ip=source_ip, epoch=epoch,
                ntp_msw=int.from_bytes(pkt[8:12], 'big'),
                ntp_lsw=int.from_bytes(pkt[12:16], 'big'),
                rtp_timestamp=int.from_bytes(pkt[16:20], 'big'),
                sender_packet_count=int.from_bytes(pkt[20:24], 'big'),
                sender_octet_count=int.from_bytes(pkt[24:28], 'big'),
            )
            p.ntp_seconds = ntp_to_seconds(p.ntp_msw, p.ntp_lsw)
            p.report_blocks = _parse_report_blocks(pkt[28:], rc)
            out.append(p)
        elif pt == PT_RR:
            if len(pkt) < 8:
                offset += packet_len
                continue
            p = RtcpPacket(
                pt=pt, ssrc=int.from_bytes(pkt[4:8], 'big'), arrival=arrival,
                arrival_estimated=arrival_estimated,
                source_ip=source_ip, epoch=epoch,
            )
            p.report_blocks = _parse_report_blocks(pkt[8:], rc)
            out.append(p)
        # SDES/BYE/APP/XR 等保留在 compound 中但不参与丢包与 RTT 统计。
        offset += packet_len
    return out


def summarize(events: list[dict]) -> dict:
    """把 RTCP 事件汇总成按 RTP SSRC 索引的指标

    events: [{'arrival': float, 'payload': bytes,
              'source_ip': str|None, 'epoch': float|None,
              'arrival_estimated': bool}, ...]

    `arrival_estimated=True` 表示到达时间是从 TCP 方向的时间窗插值出来的
    （TCP 没有逐帧时间戳）。这类 RTT 只是估算值，汇总里会带
    `rtt_estimated=True`，调用方展示时应注明。

    返回 {ssrc: {...}}。同一 SSRC 可能被多台设备复用，所以每个条目还带
    `source_ips`（观察到该 SSRC 的 SR 发送方）。调用方应核对媒体流的
    源地址是否在其中，避免把别的设备的接收报告挂到本流上。

    `sr_clock_offset_seconds` = 抓包机墙钟 − SR 的 NTP。它混合了发送端
    时钟偏差与单向传输时延，只能说明"两端时间差多少"，不能当成 RTT。
    """
    packets: list[RtcpPacket] = []
    for ev in sorted(events, key=lambda x: x.get('arrival') or 0.0):
        payload = ev.get('payload') or b''
        if payload:
            packets.extend(parse_compound(
                payload, ev.get('arrival') or 0.0, ev.get('source_ip'),
                ev.get('epoch'), bool(ev.get('arrival_estimated'))))
    if not packets:
        return {}

    srs = [p for p in packets if p.pt == PT_SR]
    summary: dict = {}

    for p in srs:
        item = summary.setdefault(p.ssrc, _empty_summary())
        item['sr_count'] += 1
        item['sender_packet_count'] = p.sender_packet_count
        item['sender_octet_count'] = p.sender_octet_count
        # NTP 字段全零表示发送端没有墙钟（RFC 3550 允许）。这时换算出来是
        # 1900 年，既不应用作 last_sr_ntp，也不能拿去和抓包机墙钟相减——
        # 否则会显示成约 127 年的时钟差。
        if p.ntp_msw or p.ntp_lsw:
            item['last_sr_ntp'] = round(p.ntp_seconds, 3)
            if p.epoch is not None:
                # 抓包机墙钟 − 发送端 NTP。含单向传输时延，只能说明
                # 两端时间差多少；多个 SR 取最新一个，便于看时钟是否漂移。
                item['sr_clock_offset_seconds'] = round(
                    p.epoch - p.ntp_seconds, 3)
        if p.source_ip and p.source_ip not in item['_sources']:
            item['_sources'].append(p.source_ip)

    for p in packets:
        for block in p.report_blocks:
            item = summary.setdefault(block.ssrc, _empty_summary())
            item['report_count'] += 1
            item['_fractions'].append(block.loss_percent)
            item['fraction_lost_latest'] = block.loss_percent
            item['cumulative_lost_latest'] = block.cumulative_lost
            item['peer_jitter_raw'] = block.jitter
            if block.lsr:
                # RTCP 的 LSR 是 SR NTP 的中间 32 位。只使用我们确实抓到、
                # 且发送端 SSRC 与报告对象一致的 SR，不靠本机绝对时钟猜。
                candidates = [sr for sr in srs
                              if sr.ssrc == block.ssrc
                              and sr.middle32 == block.lsr
                              and sr.arrival <= p.arrival]
                if candidates:
                    sr = max(candidates, key=lambda s: s.arrival)
                    rtt = (p.arrival - sr.arrival) - block.dlsr_seconds
                    if rtt >= 0:
                        item['_rtts'].append(rtt * 1000)
                        # 只要 SR 或 RR 有一端的时间是插值来的，RTT 就是
                        # 估算值：TCP 承载时两端都可能没有逐帧时间戳。
                        if p.arrival_estimated or sr.arrival_estimated:
                            item['_rtt_estimated'] = True

    for item in summary.values():
        fractions = item.pop('_fractions')
        rtts = item.pop('_rtts')
        estimated = item.pop('_rtt_estimated', False)
        item['source_ips'] = item.pop('_sources')
        if fractions:
            # RFC 3550 的 Fraction Lost 是"自上次报告以来"的区间值，不是
            # 累计值。这里对所有报告等权平均，得到的是"平均每区间丢包率"，
            # 不是整段会话的丢包率；要累计口径请看 cumulative_lost_latest。
            item['fraction_lost_avg'] = round(sum(fractions) / len(fractions), 3)
        if rtts:
            item['rtt_ms_latest'] = round(rtts[-1], 3)
            item['rtt_ms_avg'] = round(sum(rtts) / len(rtts), 3)
            item['rtt_estimated'] = bool(estimated)
    return summary


def _empty_summary() -> dict:
    return {
        'report_count': 0,
        'sr_count': 0,
        'fraction_lost_latest': None,
        'fraction_lost_avg': None,
        'cumulative_lost_latest': None,
        'peer_jitter_raw': None,
        'rtt_ms_latest': None,
        'rtt_ms_avg': None,
        'rtt_estimated': False,
        'sender_packet_count': None,
        'sender_octet_count': None,
        'last_sr_ntp': None,
        'sr_clock_offset_seconds': None,
        'source_ips': [],
        '_fractions': [],
        '_rtts': [],
        '_sources': [],
    }
