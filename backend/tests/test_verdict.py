#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一句话结论：确定性、保守、与现有诊断共存。"""
from __future__ import annotations

from app.services.diagnosis import Diagnostic, build_verdict

SESSIONS = [{'id': 1, 'device_id': '34020000001320000001',
             'signal_status': 'success', 'media_status': 'no_media'}]
STREAMS = []
STATS = {'count': 100}


def verdict(diagnostics, limits=None, stats=None, sessions=None, streams=None):
    return build_verdict(diagnostics, sessions if sessions is not None else SESSIONS,
                         streams if streams is not None else STREAMS,
                         stats if stats is not None else STATS, limits or [])


def test_no_diagnostics_is_healthy():
    v = verdict([])
    assert v['status'] == 'healthy'
    assert v['headline']
    assert '无问题' not in v['headline'] or '未发现' in v['headline']
    assert v['lead_rule_ids'] == []
    assert v['actions']
    assert v['confidence'] == 'insufficient'


def test_confirmed_critical_is_blocked_with_lead_and_action():
    d = Diagnostic(
        rule_id='MED-002', severity='critical', evidence_level='confirmed',
        title='RTP 序号缺口', description='丢包率超过阈值',
        recommendations=['核对 RTCP 报告', '在发送端补抓包', '检查中间链路'],
    )
    v = verdict([d])
    assert v['status'] == 'blocked'
    assert 'MED-002' in v['lead_rule_ids']
    assert 'RTP 序号缺口' in v['headline']
    assert v['confidence'] == 'confirmed'
    assert '核对 RTCP 报告' in v['actions']
    assert len(v['actions']) <= 3


def test_warning_and_insufficient_mix_is_attention_and_conservative():
    warning = Diagnostic(
        rule_id='SDP-002', severity='warning', evidence_level='suspected',
        title='协商与实际媒体不匹配',
        recommendations=['核对 SDP 与实际媒体地址'],
    )
    insufficient = Diagnostic(
        rule_id='CAP-001', severity='warning', evidence_level='insufficient',
        title='抓包不完整', recommendations=['补抓包'],
    )
    v = verdict([insufficient, warning])
    assert v['status'] == 'attention'
    assert '疑似' in v['headline'] or '复核' in v['headline']
    assert v['confidence'] == 'suspected'
    assert '已确认' not in v['headline']
    assert '抓包点' in v['headline']
    assert v['lead_rule_ids'][0] == 'SDP-002'


def test_only_insufficient_or_info_is_observation_not_confirmed():
    items = [
        Diagnostic(rule_id='SIP-005', severity='info', evidence_level='insufficient',
                   title='抓包中未找到请求', recommendations=[]),
        Diagnostic(rule_id='CAP-001', severity='unknown', evidence_level='insufficient',
                   title='抓包不完整', recommendations=['补抓包']),
    ]
    v = verdict(items)
    assert v['status'] == 'observation'
    assert v['confidence'] == 'insufficient'
    assert '已确认' not in v['headline']
    assert '复核' in v['headline'] or '不足' in v['headline']
    assert all('已确认' not in a for a in v['actions'])


def test_capture_limits_are_mentioned():
    limits = [{'code': 'no_media_captured', 'level': 'warning',
               'message': '信令成功但未捕获到媒体流'}]
    v = verdict([], limits=limits)
    assert v['status'] == 'observation'
    assert '抓包点' in v['headline']
    assert any('补抓包' in a for a in v['actions'])


def test_empty_capture_never_claims_no_problem():
    v = verdict([], stats={'count': 0})
    assert v['status'] == 'observation'
    assert '无法判断' in v['headline']


def test_verdict_is_deterministic_and_additive():
    import random

    diagnostics = [
        Diagnostic(rule_id='MED-001', severity='critical', evidence_level='suspected',
                   title='信令成功但未发现 RTP', recommendations=['在媒体路径上补抓包']),
        Diagnostic(rule_id='CAP-001', severity='warning', evidence_level='insufficient',
                   title='抓包不完整', recommendations=['补抓包']),
    ]
    shuffled = diagnostics[:]
    random.Random(1).shuffle(shuffled)
    a = build_verdict(diagnostics, SESSIONS, STREAMS, STATS, [])
    b = build_verdict(shuffled, SESSIONS, STREAMS, STATS, [])
    assert a == b

    # verdict 本身包含 stages；_build_summary 会直接透传 build_verdict 的结果。
    assert 'stages' in a
    assert [x['key'] for x in a['stages']] == [
        'signal', 'negotiation', 'media', 'codec', 'capture']


STAGE_KEYS = {'key', 'label', 'status', 'summary', 'rule_ids', 'evidence_hint'}


def test_stage_conclusions_all_ok():
    v = verdict([])
    stages = v['stages']
    assert len(stages) == 5
    for stage in stages:
        assert set(stage) == STAGE_KEYS
        assert stage['status'] == 'ok'
        assert stage['summary'] in ('未发现可确认异常', '未观察到相关数据')
        assert stage['rule_ids'] == []
        assert stage['evidence_hint']


def test_stage_conclusions_fixed_order_and_labels():
    stages = verdict([])['stages']
    assert [x['key'] for x in stages] == [
        'signal', 'negotiation', 'media', 'codec', 'capture']
    assert [x['label'] for x in stages] == [
        '信令事务', 'SDP 协商', '媒体链路', '编码与画面', '抓包范围']


def test_stage_conclusions_blocked_media_stage():
    d = Diagnostic(
        rule_id='MED-002', severity='critical', evidence_level='confirmed',
        title='RTP 序号缺口', description='丢包率超过阈值',
    )
    stages = verdict([d])['stages']
    media = next(s for s in stages if s['key'] == 'media')
    assert media['status'] == 'blocked'
    assert 'RTP 序号缺口' in media['summary']
    assert media['rule_ids'] == ['MED-002']
    assert all(s['status'] == 'ok' for s in stages if s['key'] != 'media')


def test_stage_conclusions_routes_rules_by_stage_prefix():
    items = [
        Diagnostic(rule_id='SIP-003', severity='critical', evidence_level='confirmed',
                   title='点播被拒绝'),
        Diagnostic(rule_id='SDP-003', severity='warning', evidence_level='confirmed',
                   title='SSRC 不一致'),
        Diagnostic(rule_id='MED-002', severity='warning', evidence_level='suspected',
                   title='RTP 序号缺口'),
        Diagnostic(rule_id='MED-010', severity='warning', evidence_level='confirmed',
                   title='关键帧间隔异常'),
        Diagnostic(rule_id='CAP-001', severity='warning', evidence_level='insufficient',
                   title='抓包不完整'),
    ]
    stages = {s['key']: s for s in verdict(items)['stages']}
    assert stages['signal']['rule_ids'] == ['SIP-003']
    assert stages['negotiation']['rule_ids'] == ['SDP-003']
    assert stages['media']['rule_ids'] == ['MED-002']
    assert stages['codec']['rule_ids'] == ['MED-010']
    assert stages['capture']['rule_ids'] == ['CAP-001']
    assert stages['signal']['status'] == 'blocked'
    assert stages['negotiation']['status'] == 'attention'
    assert stages['media']['status'] == 'attention'
    assert stages['codec']['status'] == 'attention'


def test_stage_conclusions_insufficient_not_confirmed():
    items = [
        Diagnostic(rule_id='SIP-001', severity='critical', evidence_level='suspected',
                   title='INVITE 未收到最终响应'),
        Diagnostic(rule_id='MED-001', severity='critical', evidence_level='insufficient',
                   title='信令成功但未发现 RTP'),
    ]
    stages = {s['key']: s for s in verdict(items)['stages']}
    assert stages['signal']['status'] == 'attention'
    assert stages['signal']['summary'].startswith('疑似')
    assert stages['media']['status'] == 'observation'
    assert '疑似' in stages['media']['summary']
    assert '已确认' not in stages['media']['summary']


def test_stage_conclusions_capture_limit_mentioned():
    limits = [{'code': 'no_media_captured', 'level': 'warning',
               'message': '信令成功但未捕获到媒体流'}]
    stages = {s['key']: s for s in verdict([], limits=limits)['stages']}
    capture = stages['capture']
    assert capture['rule_ids'] == ['CAP-001']
    assert '信令成功但未捕获到媒体流' in capture['summary']
    assert '信令成功但未捕获到媒体流' in capture['evidence_hint']
    assert '已确认' not in capture['summary']
    # 抓包局限证据等级为 insufficient，按规则只作观察，不能写成已确认。
    assert capture['status'] == 'observation'


def test_stage_conclusions_no_data_shows_observation():
    v = build_verdict([], [], [], {'count': 0}, [])
    stages = {s['key']: s for s in v['stages']}
    assert stages['media']['status'] == 'ok'
    assert stages['media']['summary'].startswith('疑似') is False
