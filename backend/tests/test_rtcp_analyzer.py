#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RTCP SR/RR 解析、RTT 关联与诊断接线"""
from __future__ import annotations

import pytest

from app.parsers import rtcp_analyzer as rtcp
from app.services import diagnosis


def _block(ssrc, fraction=0, cum_lost=0, highest=100, jitter=0,
           lsr=0, dlsr=0) -> bytes:
    cum = cum_lost & 0xFFFFFF
    return (ssrc.to_bytes(4, 'big') + bytes([fraction])
            + cum.to_bytes(3, 'big') + highest.to_bytes(4, 'big')
            + jitter.to_bytes(4, 'big') + lsr.to_bytes(4, 'big')
            + dlsr.to_bytes(4, 'big'))


def _rtcp(pt, ssrc, blocks=(), *, ntp=(0, 0), rtp_ts=0,
          pkt_count=0, octet_count=0, count=None) -> bytes:
    rc = len(blocks) if count is None else count
    body = ssrc.to_bytes(4, 'big')
    if pt == rtcp.PT_SR:
        body += (int(ntp[0]).to_bytes(4, 'big') + int(ntp[1]).to_bytes(4, 'big')
                 + rtp_ts.to_bytes(4, 'big') + pkt_count.to_bytes(4, 'big')
                 + octet_count.to_bytes(4, 'big'))
    body += b''.join(blocks)
    length_words = len(body) // 4
    return bytes([0x80 | rc, pt]) + length_words.to_bytes(2, 'big') + body


def _sdes(ssrc) -> bytes:
    # SDES：chunk = SSRC + 空 CNAME 项 + 对齐填充
    body = ssrc.to_bytes(4, 'big') + b'\x01\x01\x00\x00'
    return bytes([0x81, 202]) + (len(body) // 4).to_bytes(2, 'big') + body


# ---------------------------------------------------------------
# 基础解析
# ---------------------------------------------------------------
def test_parse_sender_report_fields():
    sr = _rtcp(rtcp.PT_SR, 0x11223344, ntp=(0xE0000000, 0x80000000),
               rtp_ts=90000, pkt_count=500, octet_count=700000)
    packets = rtcp.parse_compound(sr, arrival=1.5)

    assert len(packets) == 1
    p = packets[0]
    assert p.pt == rtcp.PT_SR
    assert p.ssrc == 0x11223344
    assert p.rtp_timestamp == 90000
    assert p.sender_packet_count == 500
    assert p.sender_octet_count == 700000
    # NTP 1900 纪元 → Unix 秒
    assert p.ntp_seconds == 0xE0000000 - rtcp.NTP_EPOCH_OFFSET + 0.5


def test_parse_receiver_report_fraction_and_cumulative():
    block = _block(0x11223344, fraction=64, cum_lost=-3 & 0xFFFFFF,
                   jitter=1800)
    rr = _rtcp(rtcp.PT_RR, 0x55667788, [block])
    p = rtcp.parse_compound(rr)[0]

    assert p.ssrc == 0x55667788            # 报告方
    assert p.report_blocks[0].ssrc == 0x11223344   # 被报告方
    assert p.report_blocks[0].loss_percent == 25.0
    assert p.report_blocks[0].cumulative_lost == -3
    assert p.report_blocks[0].jitter == 1800


def test_parse_compound_keeps_sdes_and_ignores_unknown():
    compound = _rtcp(rtcp.PT_SR, 1, ntp=(0, 0)) + _sdes(1) + b'\x00' * 3
    packets = rtcp.parse_compound(compound)

    assert [p.pt for p in packets] == [rtcp.PT_SR]


def test_truncated_packet_does_not_lose_earlier_ones():
    good = _rtcp(rtcp.PT_RR, 7, [_block(1, fraction=32)])
    broken = _rtcp(rtcp.PT_RR, 8, [_block(2)])[:-6]
    packets = rtcp.parse_compound(good + broken)

    assert len(packets) == 1
    assert packets[0].ssrc == 7


def test_non_rtcp_is_ignored():
    assert rtcp.parse_compound(b'\x80\x60\x00\x01abcd') == []
    assert rtcp.parse_compound(b'') == []


# ---------------------------------------------------------------
# RTT：用抓到的 SR 与 RR 的 LSR/DLSR 计算，不依赖本机绝对时钟
# ---------------------------------------------------------------
def test_rtt_uses_lsr_and_dlsr():
    ntp = (0xE0000001, 0x00000000)
    sr = _rtcp(rtcp.PT_SR, 0x1000, ntp=ntp)
    middle = rtcp.ntp_middle32(*ntp)
    # 100ms 后收到 RR，对端说距上次 SR 过了 60ms
    dlsr = int(0.060 * 65536)
    rr = _rtcp(rtcp.PT_RR, 0x2000, [_block(0x1000, lsr=middle, dlsr=dlsr)])

    summary = rtcp.summarize([
        {'arrival': 10.0, 'payload': sr},
        {'arrival': 10.1, 'payload': rr},
    ])

    assert summary[0x1000]['rtt_ms_latest'] == pytest.approx(40.0, abs=0.01)


def test_rtt_ignored_when_sr_not_observed():
    middle = rtcp.ntp_middle32(0xE0000001, 0)
    rr = _rtcp(rtcp.PT_RR, 0x2000, [_block(0x1000, lsr=middle, dlsr=0)])

    summary = rtcp.summarize([{'arrival': 1.0, 'payload': rr}])

    assert summary[0x1000]['rtt_ms_latest'] is None


def test_negative_rtt_is_not_reported():
    ntp = (0xE0000001, 0)
    sr = _rtcp(rtcp.PT_SR, 0x1000, ntp=ntp)
    # 声称 DLSR 比实际间隔还长，只能说明时间不可信
    rr = _rtcp(rtcp.PT_RR, 0x2000,
               [_block(0x1000, lsr=rtcp.ntp_middle32(*ntp),
                       dlsr=int(5 * 65536))])

    summary = rtcp.summarize([
        {'arrival': 1.0, 'payload': sr},
        {'arrival': 1.01, 'payload': rr},
    ])

    assert summary[0x1000]['rtt_ms_latest'] is None


# ---------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------
def test_summary_aggregates_reports_by_media_ssrc():
    rr1 = _rtcp(rtcp.PT_RR, 0x2000, [_block(0x1000, fraction=0)])
    rr2 = _rtcp(rtcp.PT_RR, 0x2000, [_block(0x1000, fraction=128)])
    sr = _rtcp(rtcp.PT_SR, 0x1000, ntp=(0xE0000002, 0),
               pkt_count=900, octet_count=1000)

    summary = rtcp.summarize([
        {'arrival': 1.0, 'payload': sr},
        {'arrival': 2.0, 'payload': rr1},
        {'arrival': 3.0, 'payload': rr2},
    ])

    item = summary[0x1000]
    assert item['sr_count'] == 1
    assert item['report_count'] == 2
    assert item['fraction_lost_latest'] == 50.0
    assert item['fraction_lost_avg'] == 25.0
    assert item['sender_packet_count'] == 900
    assert item['last_sr_ntp'] == 0xE0000002 - rtcp.NTP_EPOCH_OFFSET


def test_summary_empty_without_packets():
    assert rtcp.summarize([]) == {}
    assert rtcp.summarize([{'arrival': 0, 'payload': b''}]) == {}


# ---------------------------------------------------------------
# 诊断接线
# ---------------------------------------------------------------
def _stream(**extra):
    base = {'id': 1, 'ssrc': 0x1000, 'packet_count': 100,
            'seq_gap_packets': 0, 'seq_gap_count': 0, 'transport': 'UDP'}
    base.update(extra)
    return base


def test_med009_reports_peer_loss_without_local_gap():
    stream = _stream(rtcp={'fraction_lost_avg': 4.0,
                           'fraction_lost_latest': 5.0,
                           'cumulative_lost_latest': 20,
                           'report_count': 3, 'rtt_ms_latest': 12.0})

    events = diagnosis._check_media([], [stream], {})
    med009 = [e for e in events if e.rule_id == 'MED-009']

    assert len(med009) == 1
    assert med009[0].evidence_level == diagnosis.CONFIRMED
    assert med009[0].evidence['fraction_lost_avg'] == 4.0


def test_med009_not_emitted_when_local_gap_exists_or_loss_low():
    with_gap = _stream(seq_gap_packets=5,
                       rtcp={'fraction_lost_avg': 4.0})
    low_loss = _stream(rtcp={'fraction_lost_avg': 0.2})

    assert not [e for e in diagnosis._check_media([], [with_gap], {})
                if e.rule_id == 'MED-009']
    assert not [e for e in diagnosis._check_media([], [low_loss], {})
                if e.rule_id == 'MED-009']


def test_med002_uses_peer_loss_to_avoid_overclaiming():
    stream = _stream(seq_gap_packets=10, seq_gap_count=2,
                     rtcp={'fraction_lost_latest': 0.0,
                           'cumulative_lost_latest': 0})

    events = [e for e in diagnosis._check_media([], [stream], {})
              if e.rule_id == 'MED-002']

    assert len(events) == 1
    assert events[0].evidence_level == diagnosis.SUSPECTED
    assert events[0].evidence['rtcp_fraction_lost'] == 0.0


def test_med003_mentions_peer_jitter():
    stream = _stream(jitter_avg=80.0, jitter_max=120.0,
                     rtcp={'peer_jitter_ms': 10.0})

    events = [e for e in diagnosis._check_media([], [stream], {})
              if e.rule_id == 'MED-003']

    assert len(events) == 1
    assert '对端 RTCP' in events[0].description
    assert events[0].evidence['rtcp_jitter_ms'] == 10.0

# ---------------------------------------------------------------
# 关键帧时间换算：RTP 时间戳优先，缺失时退回到达时间
# ---------------------------------------------------------------
def _h264_pes(idr: bool) -> bytes:
    """一个最小视频 PES：PES 头 + AUD + (IDR 或 P) slice

    slice 头必须让 first_mb_in_slice == 0，否则不会被识别为新帧。
    """
    nal_type = b'\x65' if idr else b'\x41'
    slice_byte = b'\xb0' if idr else b'\xc0'   # P 帧 slice_type=0
    es = (b'\x00\x00\x00\x01\x09\xf0'
          + b'\x00\x00\x00\x01' + nal_type + slice_byte)
    return b'\x00\x00\x01\xe0' + b'\x00\x00' + b'\x80\x00\x00' + es


def _ps_payload(*pes_list) -> bytes:
    return b'\x00\x00\x01\xba' + b'\x00' * 10 + b''.join(pes_list)


def test_keyframe_times_use_rtp_timestamps():
    from app.parsers import ps_parser

    payloads = [_ps_payload(_h264_pes(True)),
                _ps_payload(_h264_pes(False)),
                _ps_payload(_h264_pes(True))]
    # 到达时间故意抖动；RTP 时间戳间隔 2 秒
    out = ps_parser.analyze_ps(
        payloads, [0.0, 0.3, 2.4],
        [90000 * 10, 90000 * 11, 90000 * 12], clock_rate=90000)

    assert out.video.keyframe_times == [0.0, 2.0]
    assert out.video.keyframe_gop_seconds == [2.0]
    assert out.video.first_keyframe_offset == 0.0


def test_keyframe_times_fall_back_to_arrival_time():
    from app.parsers import ps_parser

    payloads = [_ps_payload(_h264_pes(True)), _ps_payload(_h264_pes(True))]
    out = ps_parser.analyze_ps(payloads, [0.0, 1.5])

    assert out.video.keyframe_times == [0.0, 1.5]
    assert out.video.keyframe_gop_seconds == [1.5]


def test_keyframe_times_are_relative_to_stream_start():
    """关键帧在流中间时，偏移必须相对流起点，而不是相对首个关键帧

    否则"首关键帧耗时"会恒等于"首媒体耗时"，这个指标就失去意义。
    """
    from app.parsers import ps_parser

    payloads = [_ps_payload(_h264_pes(False)),
                _ps_payload(_h264_pes(False)),
                _ps_payload(_h264_pes(True)),
                _ps_payload(_h264_pes(True))]
    out = ps_parser.analyze_ps(
        payloads, [0.0, 1.0, 2.0, 4.0],
        [0, 90000, 180000, 360000], clock_rate=90000)

    assert out.video.keyframe_times == [2.0, 4.0]
    assert out.video.keyframe_gop_seconds == [2.0]
    assert out.video.first_keyframe_offset == 2.0


def test_keyframe_times_never_mix_rtp_and_arrival_sources():
    """部分关键帧缺少 RTP 时间戳时，整条序列退回到达时间

    混用两种时基会让相邻间隔变成"RTP 秒数减去到达秒数"，结果无意义。
    """
    from app.parsers import ps_parser

    payloads = [_ps_payload(_h264_pes(True)),
                _ps_payload(_h264_pes(True))]
    # 只给第一个包 RTP 时间戳，第二个缺失
    out = ps_parser.analyze_ps(payloads, [0.0, 1.5], [90000])

    assert out.video.keyframe_times == [0.0, 1.5]
    assert out.video.keyframe_gop_seconds == [1.5]


def test_keyframe_times_dropped_when_a_keyframe_cannot_be_located():
    """关键帧定位不到对应 RTP 包时整条序列作废

    跳过中间某个关键帧会让相邻间隔跨过它，GOP 直接翻倍，
    MED-010 会因此误报。
    """
    from app.parsers import ps_parser

    video = ps_parser.VideoInfo()
    video.keyframe_offsets = [10, 200]
    # 只有一段结束于 100，第二个关键帧（偏移 200）落在所有段之后
    marks = [(100, 0.0, 90000)]

    ps_parser._fill_keyframe_times(video, marks, 90000)

    assert video.keyframe_times == []
    assert video.keyframe_gop_seconds == []
    assert video.first_keyframe_offset is None


def test_keyframe_times_empty_without_any_time_source():
    from app.parsers import ps_parser

    out = ps_parser.analyze_ps([_ps_payload(_h264_pes(True))])

    assert out.video.keyframe_times == []
    assert out.video.first_keyframe_offset is None


# ---------------------------------------------------------------
# MED-010：关键帧间隔异常
# ---------------------------------------------------------------
def _video_stream(gops, first=0.0, has_video=True):
    return {'id': 1, 'ssrc': 0x1000, 'packet_count': 200,
            'has_video': has_video,
            'ps': {'video': {'keyframe_gop_seconds': gops,
                             'first_keyframe_offset': first}},
            'ps_sampled': False}


def test_med010_flags_long_gop():
    events = diagnosis._check_media([], [_video_stream([12.0, 12.5, 11.0])], {})
    med = [e for e in events if e.rule_id == 'MED-010']

    assert len(med) == 1
    assert med[0].evidence['gop_avg_seconds'] > 10
    assert med[0].evidence_level == diagnosis.CONFIRMED


def test_med010_flags_unstable_gop():
    events = diagnosis._check_media([], [_video_stream([1.0, 1.1, 6.0])], {})
    med = [e for e in events if e.rule_id == 'MED-010']

    assert len(med) == 1
    assert '波动' in med[0].description


def test_med010_silent_for_normal_or_short_gop():
    assert not [e for e in diagnosis._check_media(
        [], [_video_stream([2.0, 2.0, 2.1])], {}) if e.rule_id == 'MED-010']
    assert not [e for e in diagnosis._check_media(
        [], [_video_stream([12.0])], {}) if e.rule_id == 'MED-010']
    assert not [e for e in diagnosis._check_media(
        [], [_video_stream([12.0, 12.0], has_video=False)], {})
        if e.rule_id == 'MED-010']


# ---------------------------------------------------------------
# 会话层：首关键帧耗时 = 首媒体耗时 + 流内关键帧偏移
# ---------------------------------------------------------------
def test_link_media_derives_first_keyframe_latency():
    from app.parsers.session_builder import SessionInfo, link_media

    session = SessionInfo(device_id='d1', start_time=1.0, end_time=10.0,
                          negotiated_port=8000, negotiated_transport='UDP',
                          sdp_ssrc=str(0x11223344))
    stream = {'id': 1, 'ssrc': 0x11223344, 'src_port': 6000,
              'dst_port': 8000, 'transport': 'UDP',
              'start_time': 2.0, 'end_time': 5.0,
              'keyframe_offset': 0.8}

    link_media([session], [stream])

    assert session.first_media_latency == 1.0
    assert session.first_keyframe_latency == 1.8


def test_link_media_uses_keyframe_from_the_stream_that_started_first():
    """首关键帧耗时必须和首媒体耗时同源

    两条流都精确关联时，首媒体耗时取最早的那条；关键帧偏移也必须取同一条，
    否则两根时间轴对不上，相加结果没有意义。
    """
    from app.parsers.session_builder import SessionInfo, link_media

    session = SessionInfo(device_id='d1', start_time=1.0, end_time=10.0,
                          negotiated_port=8000, negotiated_transport='UDP',
                          sdp_ssrc=str(0x11223344))
    early = {'id': 1, 'ssrc': 0x11223344, 'src_port': 6000, 'dst_port': 8000,
             'transport': 'UDP', 'start_time': 2.0, 'end_time': 9.0,
             'keyframe_offset': None}          # 这条先到，但没有关键帧数据
    late = {'id': 2, 'ssrc': 0x11223344, 'src_port': 6001, 'dst_port': 8000,
            'transport': 'UDP', 'start_time': 4.0, 'end_time': 9.0,
            'keyframe_offset': 0.5}

    link_media([session], [early, late])

    assert session.first_media_latency == 1.0        # 来自 early
    # early 没有关键帧偏移，不能拿 late 的 0.5 去凑 1.5
    assert session.first_keyframe_latency is None


def test_link_media_leaves_keyframe_latency_unknown_without_es_data():
    from app.parsers.session_builder import SessionInfo, link_media

    session = SessionInfo(device_id='d1', start_time=1.0, end_time=10.0,
                          negotiated_port=8000, negotiated_transport='UDP',
                          sdp_ssrc=str(0x11223344))
    stream = {'id': 1, 'ssrc': 0x11223344, 'src_port': 6000,
              'dst_port': 8000, 'transport': 'UDP',
              'start_time': 2.0, 'end_time': 5.0, 'keyframe_offset': None}

    link_media([session], [stream])

    assert session.first_media_latency == 1.0
    assert session.first_keyframe_latency is None


# ---------------------------------------------------------------
# analyzer 辅助：从流 extra 取关键帧偏移、换算对端抖动
# ---------------------------------------------------------------
def test_keyframe_offset_reads_ps_extra():
    from app.models.entities import MediaStream
    from app.services import analyzer

    row = MediaStream(task_id=1, start_time=0, end_time=1,
                      extra={'ps': {'video': {'first_keyframe_offset': 1.25}}})
    assert analyzer._keyframe_offset(row) == 1.25

    empty = MediaStream(task_id=1, start_time=0, end_time=1, extra={})
    assert analyzer._keyframe_offset(empty) is None


def test_sr_clock_offset_uses_capture_wall_clock():
    """SR 的 NTP 与抓包机墙钟比对，给出两端时间差（含单向时延）"""
    ntp = (0xE0000001, 0)              # 一个确定的发送端时间
    sr = _rtcp(rtcp.PT_SR, 0x1000, ntp=ntp)
    ntp_seconds = 0xE0000001 - rtcp.NTP_EPOCH_OFFSET

    summary = rtcp.summarize([
        {'arrival': 1.0, 'payload': sr, 'epoch': ntp_seconds + 2.5},
    ])

    assert summary[0x1000]['sr_clock_offset_seconds'] == pytest.approx(2.5, abs=0.01)


def test_sr_clock_offset_absent_without_epoch():
    sr = _rtcp(rtcp.PT_SR, 0x1000, ntp=(0xE0000001, 0))

    summary = rtcp.summarize([{'arrival': 1.0, 'payload': sr}])

    assert summary[0x1000]['sr_clock_offset_seconds'] is None


def test_peer_jitter_is_converted_with_clock_rate():
    from app.services import analyzer
    from app.parsers.rtp_analyzer import StreamStat

    stat = StreamStat(clock_rate=90000, packet_count=10,
                      start_time=0.0, end_time=1.0)
    row = analyzer._save_stream(
        _FakeSession(), _FakeTask(), stat, (1, '10.0.0.1', 1, '10.0.0.2', 2),
        'UDP', {}, None, None,
        rtcp={'peer_jitter_raw': 900, 'fraction_lost_latest': 1.0})
    assert row.extra['rtcp']['peer_jitter_ms'] == 10.0


# ---------------------------------------------------------------
# SSRC 复用：RTCP 只能挂到源地址对得上的那条流
# ---------------------------------------------------------------
def test_summary_records_sr_source_ips():
    sr = _rtcp(rtcp.PT_SR, 0x1000, ntp=(0xE0000001, 0))

    summary = rtcp.summarize([
        {'arrival': 1.0, 'payload': sr, 'source_ip': '10.0.0.1'},
        {'arrival': 2.0, 'payload': sr, 'source_ip': '10.0.0.9'},
    ])

    assert summary[0x1000]['source_ips'] == ['10.0.0.1', '10.0.0.9']


def _stat(ssrc=0x1000):
    from app.parsers.rtp_analyzer import StreamStat
    return StreamStat(ssrc=ssrc, clock_rate=90000, packet_count=10,
                      start_time=0.0, end_time=1.0)


def test_rtcp_attached_when_source_matches():
    from app.services import analyzer

    summary = {0x1000: {'fraction_lost_latest': 2.0,
                        'source_ips': ['10.0.0.1']}}
    key = (0x1000, '10.0.0.1', 6000, '10.0.0.2', 8000)

    assert analyzer._rtcp_for_stream(summary, _stat(), key) is not None


def test_rtcp_not_attached_when_only_other_device_reports():
    """SSRC 相同但源地址对不上时不能认领，否则会把别的设备的报告算进来"""
    from app.services import analyzer

    summary = {0x1000: {'fraction_lost_latest': 2.0,
                        'source_ips': ['10.0.0.9']}}
    key = (0x1000, '10.0.0.1', 6000, '10.0.0.2', 8000)

    assert analyzer._rtcp_for_stream(summary, _stat(), key) is None


def test_rtcp_attached_when_no_source_known():
    """只有 RR、没有 SR 时拿不到发送方地址，此时仍按 SSRC 挂上"""
    from app.services import analyzer

    summary = {0x1000: {'fraction_lost_latest': 2.0, 'source_ips': []}}
    key = (0x1000, '10.0.0.1', 6000, '10.0.0.2', 8000)

    assert analyzer._rtcp_for_stream(summary, _stat(), key) is not None


def test_rtcp_missing_ssrc_returns_none():
    from app.services import analyzer

    assert analyzer._rtcp_for_stream({}, _stat(ssrc=None),
                                     (None, 'a', 1, 'b', 2)) is None


class _FakeSession:
    def add(self, _obj):
        pass

    def flush(self):
        pass

    def commit(self):
        pass


class _FakeTask:
    id = 1
