# -*- coding: utf-8 -*-
"""抓包局限检测：只依赖聚合量（count / first_ts / has_rtp）"""
from app.parsers.session_builder import SessionInfo, detect_capture_limits


def test_no_packets_is_critical():
    warns = detect_capture_limits([], [], {'count': 0})
    assert warns and warns[0]['code'] == 'no_packets'
    assert warns[0]['level'] == 'critical'


def test_session_cut_start_uses_first_ts():
    s = SessionInfo(device_id='34020000001310000001', start_time=0.0)
    s.dialogs = [type('D', (), {'invite_time': None})()]
    warns = detect_capture_limits([s], [], {'count': 10, 'first_ts': 0.0})
    assert [w['code'] for w in warns] == ['session_cut_start']


def test_session_started_after_capture_is_not_flagged():
    s = SessionInfo(device_id='34020000001310000001', start_time=3.0)
    s.dialogs = [type('D', (), {'invite_time': 3.0})()]
    warns = detect_capture_limits([s], [], {'count': 10, 'first_ts': 0.0})
    assert warns == []


def test_media_without_signalling_needs_rtp():
    s = SessionInfo(device_id='34020000001310000001')
    s.media_status = 'received'
    with_rtp = detect_capture_limits([s], [], {'count': 10, 'has_rtp': True})
    without = detect_capture_limits([s], [], {'count': 10, 'has_rtp': False})
    assert [w['code'] for w in with_rtp] == ['no_signal']
    assert with_rtp[0]['level'] == 'info'
    assert without == []


def test_capture_ended_marks_incomplete_media():
    s = SessionInfo(device_id='34020000001310000001', end_reason='capture_ended')
    warns = detect_capture_limits([s], [], {'count': 10, 'has_rtp': True})
    assert 'session_cut_end' in [w['code'] for w in warns]
