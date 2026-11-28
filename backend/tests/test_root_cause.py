#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""根因链：确定性、保守、只引用实际证据。"""
from __future__ import annotations

import random

from app.services.diagnosis import Diagnostic
from app.services.root_cause import build_root_cause

STATS = {'count': 100}


def diag(rule_id, severity='warning', level='confirmed', **kwargs):
    return Diagnostic(
        rule_id=rule_id, severity=severity, evidence_level=level,
        title=kwargs.pop('title', rule_id),
        description=kwargs.pop('description', ''),
        recommendations=kwargs.pop('recommendations', []),
        **kwargs,
    )


def sess(**kwargs):
    base = dict(id=1, device_id='34020000001320000001',
                signal_status='success', final_code=200,
                media_status='received', negotiated_ip='192.168.1.20',
                negotiated_port=8808, negotiated_transport='UDP')
    base.update(kwargs)
    return base


def stream(**kwargs):
    base = dict(id=11, session_id=1, ssrc='0x12345678',
                packet_count=1000, transport='UDP', codec='H.264',
                seq_gap_count=0, seq_gap_packets=0, jitter_avg=5,
                rebuild_error=None, rebuilt_ok=True)
    base.update(kwargs)
    return base


def build(diagnostics=None, sessions=None, streams=None, stats=None, limits=None):
    return build_root_cause(diagnostics or [],
                            sessions if sessions is not None else [sess()],
                            streams if streams is not None else [stream()],
                            stats if stats is not None else STATS, limits or [])


KEYS = {'failure_stage', 'label', 'confidence', 'chain',
        'evidence_rule_ids', 'next_check'}


def assert_shape(result):
    assert set(result) == KEYS
    assert result['failure_stage'] in {
        'signaling', 'negotiation', 'media_path', 'media_quality', 'codec',
        'capture_scope', 'unknown', 'none'}
    assert result['confidence'] in {'confirmed', 'suspected', 'insufficient'}
    assert isinstance(result['chain'], list) and len(result['chain']) <= 4
    assert all(isinstance(s, str) and s for s in result['chain'])
    assert isinstance(result['evidence_rule_ids'], list)
    assert result['next_check']
    assert result['label']


def test_capture_limits_are_reported_before_any_failure():
    diagnostics = [diag('SIP-003', severity='critical', session_id=1)]
    limits = [{'code': 'filter', 'level': 'warning', 'message': '仅捕获 SIP 信令'}]
    r = build(diagnostics, [sess(signal_status='failed', final_code=486)],
              [], limits=limits)
    assert_shape(r)
    assert r['failure_stage'] == 'capture_scope'
    assert r['confidence'] == 'insufficient'
    assert 'CAP-001' in r['evidence_rule_ids']
    assert 'SIP-003' not in r['evidence_rule_ids']
    assert any('抓包' in s for s in r['chain'])
    assert '抓包点' in r['next_check']
    assert '疑似' not in r['label']


def test_zero_packets_is_only_suspected():
    r = build([], [sess(media_status='no_media')], [], stats={'count': 0})
    assert_shape(r)
    assert r['failure_stage'] == 'capture_scope'
    assert r['confidence'] == 'suspected'
    assert r['label'].startswith('疑似')
    assert '抓包' in r['next_check']


def test_cap001_alone_is_insufficient():
    r = build([diag('CAP-001', severity='unknown', level='insufficient')])
    assert_shape(r)
    assert r['failure_stage'] == 'capture_scope'
    assert r['confidence'] == 'insufficient'
    assert r['evidence_rule_ids'] == ['CAP-001']


def test_signaling_failure_requires_confirmed_sip_evidence():
    failed = sess(signal_status='failed', final_code=486, media_status='no_media')
    r = build([diag('SIP-003', severity='critical', session_id=1,
                    title='点播被拒绝（SIP 486）')], [failed], [])
    assert_shape(r)
    assert r['failure_stage'] == 'signaling'
    assert r['confidence'] == 'confirmed'
    assert r['evidence_rule_ids'] == ['SIP-003']
    assert any('486' in s for s in r['chain'])
    assert any('192.168.1.20' in s for s in r['chain'])

    weak = build([diag('SIP-001', severity='critical', level='suspected')],
                 [sess(signal_status='incomplete', media_status='no_media')], [])
    assert weak['failure_stage'] == 'media_path'
    assert weak['confidence'] == 'suspected'


def test_negotiation_uses_sdp_evidence_addresses():
    no_media = sess(media_status='no_media')
    d = diag('SDP-002', severity='warning', session_id=1,
             evidence={'negotiated_ip': '192.168.1.20',
                       'negotiated_port': 8808,
                       'negotiated_transport': 'UDP',
                       'transport': 'TCP', 'ports': [5000, 8808],
                       'addresses': ['192.168.1.30', '192.168.1.20']})
    r = build([d], [no_media], [])
    assert_shape(r)
    assert r['failure_stage'] == 'negotiation'
    assert r['confidence'] == 'confirmed'
    assert r['evidence_rule_ids'] == ['SDP-002']
    chain_text = ' | '.join(r['chain'])
    assert '192.168.1.20:8808' in chain_text
    assert '5000' in chain_text
    ssrc_diag = diag('SDP-003', severity='warning', session_id=1,
                     evidence={'subject_ssrc': '0xabcdef01',
                               'sdp_ssrc': '0x12345678'})
    r2 = build([ssrc_diag], [no_media], [])
    assert r2['failure_stage'] == 'negotiation'
    assert any('0xabcdef01' in s and '0x12345678' in s for s in r2['chain'])

    # suspected SDP cannot be promoted to confirmed negotiation root cause
    d_suspected = diag('SDP-002', level='suspected', evidence=d.evidence)
    r3 = build([d_suspected], [no_media], [])
    assert r3['failure_stage'] == 'media_path'
    assert r3['confidence'] == 'suspected'


def test_media_path_is_suspected_not_confirmed():
    d = diag('MED-001', severity='critical', level='suspected', session_id=1)
    r = build([d], [sess(media_status='no_media')], [])
    assert_shape(r)
    assert r['failure_stage'] == 'media_path'
    assert r['label'].startswith('疑似')
    assert r['confidence'] == 'suspected'
    assert 'MED-001' in r['evidence_rule_ids']
    assert '192.168.1.20:8808' in ' '.join(r['chain'])
    assert '抓包点' in r['next_check']
    assert '已确认' not in r['label']


def test_media_quality_uses_confirmed_diagnostics():
    d = diag('MED-002', severity='critical', session_id=1,
             title='RTP 序号缺口', stream_id=11)
    r = build([d], [sess()], [stream(seq_gap_packets=50)])
    assert_shape(r)
    assert r['failure_stage'] == 'media_quality'
    assert r['confidence'] == 'confirmed'
    assert r['evidence_rule_ids'] == ['MED-002']
    assert any('SSRC' in s for s in r['chain'])
    assert any('1000' in s for s in r['chain'])

    for rule in ('MED-003', 'MED-009'):
        one = build([diag(rule, session_id=1)], [sess()], [stream()])
        assert one['failure_stage'] == 'media_quality'
        assert one['evidence_rule_ids'] == [rule]

    weak = build([diag('MED-002', level='suspected')], [sess()], [stream()])
    assert weak['failure_stage'] != 'media_quality'


def test_codec_stage_from_rebuild_failure():
    bad = stream(rebuilt_ok=False, rebuild_error='invalid NAL unit',
                 codec='H.265', has_video=True)
    d = diag('MED-008', severity='warning', level='suspected', session_id=1,
             stream_id=11, title='抓到 RTP 但视频重建失败')
    r = build([d], [sess()], [bad])
    assert_shape(r)
    assert r['failure_stage'] == 'codec'
    # MED-008 is suspected in the diagnostic engine; never call it confirmed.
    assert r['confidence'] == 'suspected'
    assert r['label'].startswith('疑似')
    assert r['evidence_rule_ids'] == ['MED-008']
    assert any('invalid NAL unit' in s for s in r['chain'])
    assert any('H.265' in s for s in r['chain'])
    assert '编码' in r['next_check']

    no_diag = build([], [sess()], [bad])
    assert no_diag['failure_stage'] == 'codec'
    assert no_diag['confidence'] == 'suspected'


def test_no_evidence_is_insufficient_or_unknown():
    r = build([], [], [], stats={'count': 0}, limits=[{'code': 'empty'}])
    assert r['failure_stage'] == 'capture_scope'
    r = build([], [], [], stats={'count': 0})
    assert_shape(r)
    assert r['failure_stage'] == 'capture_scope'

    none = build([], [], [], stats={'count': 0}, limits=[])
    assert none['confidence'] in {'insufficient', 'suspected'}

    info_only = build([diag('SIP-005', severity='info', level='insufficient')])
    assert_shape(info_only)
    assert info_only['confidence'] == 'insufficient' or info_only['confidence'] == 'confirmed'
    assert info_only['evidence_rule_ids'] == []

    problem_without_link = build(
        [diag('MED-008', severity='warning', level='suspected')],
        [], [], stats={'count': 100})
    assert problem_without_link['failure_stage'] == 'unknown'
    assert problem_without_link['confidence'] == 'insufficient'


def test_confirmed_healthy_requires_positive_end_to_end_evidence():
    r = build([], [sess(media_status='received')], [stream(rebuilt_ok=True)])
    assert_shape(r)
    assert r['failure_stage'] == 'none'
    assert r['confidence'] == 'confirmed'
    assert not r['label'].startswith('疑似')
    assert r['evidence_rule_ids'] == []
    assert len(r['chain']) >= 2

    partial = build([], [sess(media_status='received')], [stream(rebuilt_ok=None)])
    assert partial['failure_stage'] == 'none'
    assert partial['confidence'] == 'insufficient'


def test_result_is_deterministic_and_never_invents_addresses():
    d = diag('MED-002', severity='warning', session_id=1,
             title='RTP 序号缺口', stream_id=11)
    shuffled = [d, diag('MED-003', severity='warning', session_id=1,
                       title='RTP 抖动偏高', stream_id=11)]
    shuffled2 = shuffled[:]
    random.Random(7).shuffle(shuffled2)
    a = build(shuffled)
    b = build(shuffled2)
    assert a == b
    assert a['failure_stage'] == 'media_quality'
    assert a['evidence_rule_ids'] == ['MED-002', 'MED-003']

    plain = build([], [sess(negotiated_ip=None, negotiated_port=None)], [])
    assert '192.168.1.20' not in ' '.join(plain['chain'])
    assert len(plain['chain']) <= 4


def test_summary_attaches_root_cause_additively():
    from app.services.analyzer import _build_summary

    class Row:
        pass

    row = Row()
    row.signal_status = 'success'
    row.media_status = 'no_media'
    row.final_code = 200
    row.first_media_latency = None
    row.first_keyframe_latency = None
    row.device_id = 'dev'
    row.channel_id = None
    row.negotiated_ip = '10.0.0.1'
    row.negotiated_port = 9000
    row.link_mode = None
    row.end_reason = None
    row.start_time = None
    row.end_time = None
    row.negotiated_transport = 'UDP'
    row.subject_ssrc = None
    row.sdp_ssrc = None
    row.subject_packet = None
    row.sdp_ssrc_packet = None
    row.call_ids = []
    diagnostics = [diag('MED-001', severity='critical', level='suspected',
                        session_id=1)]
    summary = _build_summary(None, [(row, 1)], [], diagnostics, STATS, [])
    assert summary['verdict']
    assert summary['diagnostics']
    assert summary['capture_warnings'] == 0
    rc = summary['root_cause']
    assert_shape(rc)
    assert rc['failure_stage'] == 'media_path'
    assert '10.0.0.1:9000' in ' '.join(rc['chain'])
