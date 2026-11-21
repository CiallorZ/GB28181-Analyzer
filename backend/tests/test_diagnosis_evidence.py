#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断必须能指回具体报文（P0-14）"""
from __future__ import annotations

from app.services import diagnosis as d


def _session(**kw):
    base = {
        'id': 1, 'device_id': '34020000001320000001',
        'signal_status': 'success', 'media_status': 'received',
        'end_reason': 'normal', 'start_time': 1.0, 'end_time': 9.0,
        'call_ids': ['call-1'], 'final_code': 200,
    }
    base.update(kw)
    return base


def _msg(packet, **kw):
    base = {'packet_number': packet, 'timestamp': 1.0,
            'call_id': 'call-1', 'method': None,
            'is_request': False, 'status_code': None}
    base.update(kw)
    return base


def test_sip_003_points_at_failure_response():
    out = d.diagnose({
        'sessions': [_session(signal_status='failed', final_code=404)],
        'streams': [],
        'messages': [
            _msg(10, method='INVITE', is_request=True),
            _msg(12, status_code=404),
            _msg(13, status_code=200),
        ],
    })
    ev = next(x for x in out if x.rule_id == 'SIP-003')
    assert ev.related_packet_ids == [12]


def test_sip_001_points_at_invite():
    out = d.diagnose({
        'sessions': [_session(signal_status='incomplete', final_code=None,
                              media_status='no_media')],
        'streams': [],
        'messages': [
            _msg(10, method='INVITE', is_request=True),
            _msg(11, status_code=100),
        ],
    })
    ev = next(x for x in out if x.rule_id == 'SIP-001')
    assert ev.related_packet_ids == [10]


def test_sip_008_points_at_bye():
    out = d.diagnose({
        'sessions': [_session(end_reason='abnormal')],
        'streams': [],
        'messages': [
            _msg(10, method='INVITE', is_request=True),
            _msg(30, method='BYE', is_request=True),
        ],
    })
    ev = next(x for x in out if x.rule_id == 'SIP-008')
    assert ev.related_packet_ids == [30]


def test_med_002_points_at_packet_after_gap():
    out = d.diagnose({
        'sessions': [_session()],
        'streams': [{
            'id': 3, 'session_id': 1, 'ssrc': 0x1234, 'transport': 'UDP',
            'packet_count': 100, 'seq_gap_packets': 2,
            'seq_gap_count': 1, 'start_time': 1.0,
            'seq_gap_events': [{'after_seq': 40, 'gap': 2,
                                'time': 0.5, 'packet': 77,
                                'prev_packet': 76}],
        }],
        'messages': [],
    })
    ev = next(x for x in out if x.rule_id == 'MED-002')
    assert ev.related_packet_ids == [77]


def test_media_diagnostic_does_not_claim_an_unobserved_ack():
    out = d.diagnose({'sessions': [_session(media_status='no_media')],
                      'streams': [], 'messages': []})
    event = next(x for x in out if x.rule_id == 'MED-001')
    assert 'ACK' not in event.description
    assert '成功最终响应' in event.description


def test_rebuild_environment_error_is_not_reported_as_invalid_media():
    from app.services import diagnosis

    events = diagnosis._check_media([], [{
        'id': 1, 'ssrc': 1234, 'packet_count': 12,
        'rebuild_error': '未找到 ffmpeg，无法转码',
    }], {})
    event = next(event for event in events if event.rule_id == 'MED-008')
    assert event.evidence['rebuild_error'] == '未找到 ffmpeg，无法转码'
    assert '无法被解码器接受' not in event.description
    assert 'FFmpeg' in event.recommendations[0]
