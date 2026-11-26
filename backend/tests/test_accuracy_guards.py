"""Regression tests for the v1.3.1 evidence-accuracy guards."""
from __future__ import annotations

from app.core.config import settings
from app.models.entities import AnalysisTask
from app.parsers import capture, rtp_analyzer
from app.services import analyzer, diagnosis


def _rtp(seq: int, ssrc: int = 0x11223344, pt: int = 96,
         timestamp: int = 0, payload: bytes = b'X' * 8) -> bytes:
    return bytes([
        0x80, pt,
        (seq >> 8) & 0xff, seq & 0xff,
        (timestamp >> 24) & 0xff, (timestamp >> 16) & 0xff,
        (timestamp >> 8) & 0xff, timestamp & 0xff,
        (ssrc >> 24) & 0xff, (ssrc >> 16) & 0xff,
        (ssrc >> 8) & 0xff, ssrc & 0xff,
    ]) + payload


def _frame(packet: bytes) -> bytes:
    return len(packet).to_bytes(2, 'big') + packet


def _rtcp_sr(ssrc: int = 0x11223344) -> bytes:
    # V=2, PT=200 (SR), length=6 意味着 28 字节；内容只需结构正确，
    # 解析层在识别 PT 后就会跳过，不会把它当作 RTP。
    return bytes([0x80, 200, 0, 6]) + b'\x00' * 24 + ssrc.to_bytes(4, 'big')


# ---------------------------------------------------------------
# RTCP 不是 RTP
# ---------------------------------------------------------------
def test_rtcp_payload_type_is_classified():
    assert rtp_analyzer.is_rtcp(_rtcp_sr())
    assert not rtp_analyzer.is_rtcp(_rtp(1))
    assert not rtp_analyzer.is_rtcp(b'')


def test_udp_extraction_returns_rtcp_separately(monkeypatch):
    rtcp = _rtcp_sr()
    rows = [
        ['1', '0.1', '10.0.0.1', '50000', '10.0.0.2', '50000',
         _rtp(1).hex()],
        ['2', '0.2', '10.0.0.1', '50001', '10.0.0.2', '50001',
         rtcp.hex()],
    ]
    monkeypatch.setattr(capture, 'TSHARK', '/bin/true')
    monkeypatch.setattr(capture, 'iter_fields', lambda *a, **k: iter(rows))

    rtp, rtcp_rows = capture.extract_udp_rtp_and_rtcp('ignored.pcap')

    assert len(rtp) == 1
    assert rtp[0]['payload'][1] == 96
    assert len(rtcp_rows) == 1
    assert rtcp_rows[0]['frame'] == 2
    assert rtcp_rows[0]['payload'] == rtcp


def test_udp_extraction_keeps_wall_clock_for_rtcp(monkeypatch):
    """RTCP 需要抓包机墙钟才能与 SR 的 NTP 比对；RTP 用不到这一列"""
    rtcp = _rtcp_sr()
    rows = [
        ['2', '0.2', '10.0.0.1', '50001', '10.0.0.2', '50001',
         rtcp.hex(), '1700000000.25'],
    ]
    monkeypatch.setattr(capture, 'TSHARK', '/bin/true')
    monkeypatch.setattr(capture, 'iter_fields', lambda *a, **k: iter(rows))

    _rtp_rows, rtcp_rows = capture.extract_udp_rtp_and_rtcp('ignored.pcap')

    assert rtcp_rows[0]['epoch'] == 1700000000.25


def test_tcp_rtcp_frames_are_reported_for_summary():
    buf = b''.join([_frame(_rtp(1)), _frame(_rtp(2)),
                    _frame(_rtcp_sr()), _frame(_rtp(3))])

    got = rtp_analyzer.parse_rfc4571_streams(buf)

    assert got is not None
    stats = got[2]
    assert len(stats['rtcp']) == 1
    pos, payload = stats['rtcp'][0]
    assert 0.0 <= pos <= 1.0
    assert payload == _rtcp_sr()


def test_tcp_rtcp_interleaved_does_not_truncate_rtp():
    buf = b''.join([
        _frame(_rtp(1)), _frame(_rtp(2)), _frame(_rtcp_sr()),
        _frame(_rtp(3)),
    ])
    got = rtp_analyzer.parse_rfc4571_ex(buf)
    assert got is not None
    assert [p.seq for p in got[1]] == [1, 2, 3]


def test_tcp_rtcp_only_is_not_media():
    buf = b''.join(_frame(_rtcp_sr()) for _ in range(5))
    assert rtp_analyzer.parse_rfc4571_ex(buf) is None


def test_tcp_multiple_ssrcs_are_parsed_separately():
    frames = []
    for seq in range(1, 5):
        frames.append(_frame(_rtp(seq, ssrc=0x11111111)))
        frames.append(_frame(_rtp(seq, ssrc=0x22222222)))
    buf = b''.join(frames)

    got = rtp_analyzer.parse_rfc4571_streams(buf)

    assert got is not None
    _off, groups, _stats = got
    assert set(groups) == {0x11111111, 0x22222222}
    assert [p.seq for p in groups[0x11111111]] == [1, 2, 3, 4]
    assert [p.seq for p in groups[0x22222222]] == [1, 2, 3, 4]


def test_tcp_alignment_scan_reaches_past_old_8k_limit():
    buf = b'\x00' * 9000 + b''.join(
        _frame(_rtp(seq)) for seq in range(1, 6))

    got = rtp_analyzer.parse_rfc4571_streams(buf)

    assert got is not None
    assert got[0] == 9000
    assert len(next(iter(got[1].values()))) == 5


# ---------------------------------------------------------------
# 大抓包：载荷有界保留，统计字段不失真
# ---------------------------------------------------------------
def test_udp_payload_budget_keeps_header_and_real_size(monkeypatch):
    payload = b'X' * 20
    rows = [
        ['1', '0.0', '10.0.0.1', '5000', '10.0.0.2', '6000',
         _rtp(1, payload=payload).hex()],
        ['2', '0.1', '10.0.0.1', '5000', '10.0.0.2', '6000',
         _rtp(2, payload=payload).hex()],
        ['3', '0.2', '10.0.0.1', '5000', '10.0.0.2', '6000',
         _rtp(3, payload=payload).hex()],
    ]
    monkeypatch.setattr(capture, 'TSHARK', '/bin/true')
    monkeypatch.setattr(capture, 'iter_fields', lambda *a, **k: iter(rows))
    monkeypatch.setattr(capture, 'RTP_PAYLOAD_KEEP_BYTES', 64)

    out = capture.extract_udp_rtp('ignored.pcap')

    assert [p['payload_size'] for p in out] == [32, 32, 32]
    assert not out[0]['payload_truncated']
    assert not out[1]['payload_truncated']
    assert out[2]['payload_truncated']
    assert len(out[2]['payload']) == capture.RTP_HEADER_BYTES
    assert len(out[0]['payload']) == 32


def test_udp_payload_time_window_limits_sample(monkeypatch):
    rows = [
        ['1', '0.0', 'a', '1', 'b', '2', _rtp(1).hex()],
        ['2', '0.1', 'a', '1', 'b', '2', _rtp(2).hex()],
        ['3', '2.0', 'a', '1', 'b', '2', _rtp(3).hex()],
    ]
    monkeypatch.setattr(capture, 'TSHARK', '/bin/true')
    monkeypatch.setattr(capture, 'iter_fields', lambda *a, **k: iter(rows))
    monkeypatch.setattr(capture, 'RTP_PAYLOAD_KEEP_SECONDS', 1.0)

    out = capture.extract_udp_rtp('ignored.pcap')

    assert [p['payload_truncated'] for p in out] == [False, False, True]


def test_payload_bytes_uses_real_size_even_when_sampled():
    pkt = rtp_analyzer.RtpPacket(
        seq=1, timestamp=0, arrival=0.0, size=1400,
        payload=b'', payload_size=1392)
    stats = rtp_analyzer.analyze_stream([pkt], clock_rate=90000)
    assert stats.byte_count == 1400
    assert stats.payload_bytes == 1392


# ---------------------------------------------------------------
# 弱关联流不能污染会话的耗时指标
# ---------------------------------------------------------------
def _packets(spec):
    return [
        rtp_analyzer.RtpPacket(seq=seq, timestamp=ts, arrival=arrival, size=100)
        for seq, ts, arrival in spec
    ]


def test_small_timestamp_reorder_is_not_an_anomaly():
    # 包 3 先到（时间戳 6000），包 2 后到（时间戳 3000）：合法的乱序
    stats = rtp_analyzer.analyze_stream(
        _packets([(1, 0, 0.0), (3, 6000, 0.02), (2, 3000, 0.03)]),
        clock_rate=90000,
    )
    assert not [a for a in stats.ts_anomalies
                if a['type'] == 'timestamp_backward']


def test_large_timestamp_backward_is_reported():
    stats = rtp_analyzer.analyze_stream(
        _packets([(1, 0, 0.0), (2, 90000 * 3, 1.0), (3, 0, 2.0)]),
        clock_rate=90000,
    )
    assert any(a['type'] == 'timestamp_backward'
               for a in stats.ts_anomalies)


def test_low_clock_backward_tolerance_follows_clock_rate():
    # 8 kHz 下 3 秒才超过阈值；0.4 秒的乱序不应上报
    ok = rtp_analyzer.analyze_stream(
        _packets([(1, 0, 0.0), (2, 8000 * 0.4, 0.4)]),
        clock_rate=8000,
    )
    assert not ok.ts_anomalies
    bad = rtp_analyzer.analyze_stream(
        _packets([(1, 0, 0.0), (2, 8000 * 3, 1.0), (3, 0, 2.0)]),
        clock_rate=8000,
    )
    assert any(a['type'] == 'timestamp_backward' for a in bad.ts_anomalies)


# ---------------------------------------------------------------
# 短流仍记录为媒体，但不重建
# ---------------------------------------------------------------
def test_single_packet_stream_is_kept_and_flagged():
    stats = rtp_analyzer.analyze_stream(
        _packets([(1, 0, 0.0)]),
        clock_rate=90000,
    )
    assert stats.packet_count == 1
    assert stats.duration is None
    assert any('样本仅 1' in n for n in stats.notes)
    assert analyzer.should_rebuild([object()]) is False


def test_rebuild_requires_minimum_packets():
    assert analyzer.should_rebuild([object()] * 4) is False
    assert analyzer.should_rebuild([object()] * 5) is True


# ---------------------------------------------------------------
# MED-008 只针对视频
# ---------------------------------------------------------------
def test_med008_is_not_emitted_for_audio_only_or_non_video():
    stream = {
        'id': 1, 'ssrc': 1, 'packet_count': 10,
        'rebuild_error': 'PS 数据不足', 'has_video': False,
    }
    events = diagnosis._check_media([], [stream], {})
    assert not [e for e in events if e.rule_id == 'MED-008']

    events = diagnosis._check_media([], [{**stream, 'has_video': True}], {})
    assert [e for e in events if e.rule_id == 'MED-008']


# ---------------------------------------------------------------
# 删除任务要连预览产物一起清理
# ---------------------------------------------------------------
def test_delete_task_removes_rebuilt_media(client, make_task):
    task = make_task('待删除')
    rebuilt = settings.REBUILD_DIR / str(task.id)
    rebuilt.mkdir(parents=True, exist_ok=True)
    (rebuilt / 'udp0.mp4').write_bytes(b'preview')

    response = client.delete('/api/v1/tasks/%d' % task.id)

    assert response.status_code == 204
    assert not rebuilt.exists()
    # 走一个新会话查库：原会话的身份映射里还留着已删除对象。
    from app.core.db import SessionLocal
    with SessionLocal() as fresh:
        assert fresh.get(AnalysisTask, task.id) is None


# ---------------------------------------------------------------
# 弱关联流不能污染会话的耗时指标
# ---------------------------------------------------------------
def _weak_session():
    from app.parsers.session_builder import SessionInfo
    return SessionInfo(
        device_id='34020000001320000001', start_time=1.0, end_time=10.0,
        negotiated_port=8000, negotiated_transport='UDP')


def _stream(ssrc=0x11223344):
    return {
        'id': 1, 'ssrc': ssrc, 'src_port': 6000, 'dst_port': 8000,
        'transport': 'UDP', 'start_time': 2.0, 'end_time': 5.0,
        'src_ip': '10.0.0.1',
    }


def test_weak_link_does_not_produce_timing_metrics():
    from app.parsers.session_builder import link_media
    session = _weak_session()
    stream = _stream()

    link_media([session], [stream])

    assert session.link_mode == 'weak'
    assert session.media_status == 'received'
    assert session.first_media_latency is None
    assert session.media_duration is None
    assert any('弱关联' in n for n in session.notes)
    assert stream['link_mode'] == 'weak'


def test_exact_ssrc_link_still_produces_timing_metrics():
    from app.parsers.session_builder import link_media
    session = _weak_session()
    session.sdp_ssrc = str(0x11223344)

    link_media([session], [_stream()])

    assert session.link_mode == 'exact'
    assert session.first_media_latency == 1.0
    assert session.media_duration == 3.0