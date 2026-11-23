# -*- coding: utf-8 -*-
"""报告导出：内容、格式与状态门槛"""
from __future__ import annotations

from app.models.entities import (
    BusinessSession, DiagnosticEvent, DiagnosticSeverity, MediaStream,
    TaskStatus,
)


def _seed(db, task):
    task.status = TaskStatus.COMPLETED
    task.summary = {
        'packet_count': 126, 'session_count': 1, 'signal_success': 1,
        'signal_success_rate': 100.0, 'sessions_with_media': 1,
        'total_streams': 1, 'avg_first_media_latency': 0.24,
        'avg_jitter_ms': None,
        'diagnostics': {'critical': 0, 'warning': 1, 'info': 0},
    }
    s = BusinessSession(
        task_id=task.id, device_id='34020000001310000001',
        channel_id='34020000001320000001', session_type='live',
        start_time=0.0, end_time=5.0, signal_status='success',
        media_status='received', end_reason='NORMAL', diagnostic_count=1)
    db.add(s)
    db.flush()
    db.add(MediaStream(
        task_id=task.id, session_id=s.id, ssrc=0x1234, transport='UDP',
        start_time=0.24, end_time=4.9, packet_count=120, byte_count=96000,
        avg_bitrate=61.0, codec='H.264', width=1280, height=720))
    db.add(DiagnosticEvent(
        task_id=task.id, session_id=s.id, rule_id='SDP-003',
        severity=DiagnosticSeverity.WARNING, evidence_level='confirmed',
        title='SSRC 不一致', description='Subject 与 SDP 中的 SSRC 不同。',
        evidence={'subject': '00001234', 'sdp': '00005678'}))
    db.commit()
    return s


def test_markdown_report(client, db, make_task):
    task = make_task()
    _seed(db, task)
    r = client.get('/api/v1/tasks/%d/report' % task.id)
    assert r.status_code == 200
    assert r.headers['content-type'].startswith('text/markdown')
    assert 'attachment' in r.headers['content-disposition']
    body = r.text
    assert '# GB28181 抓包分析报告' in body
    assert 'SDP-003' in body and 'SSRC 不一致' in body
    assert '34020000001310000001' in body
    # 无法计算的指标必须留 "—"，不能写成 0
    assert 'RTP 平均抖动 | — ms' in body
    # 证据要落到报告里，而不是只给一句结论
    assert '00005678' in body


def test_json_report_matches_endpoints(client, db, make_task):
    task = make_task()
    _seed(db, task)
    r = client.get('/api/v1/tasks/%d/report?format=json' % task.id)
    assert r.status_code == 200
    body = r.json()
    assert body['task']['id'] == task.id
    assert body['summary']['packet_count'] == 126
    assert body['sessions'][0]['device_id'] == '34020000001310000001'
    assert body['streams'][0]['ssrc'] == 0x1234
    assert body['diagnostics'][0]['rule_id'] == 'SDP-003'


def test_report_requires_completed_task(client, db, make_task):
    task = make_task()          # 默认 PENDING
    r = client.get('/api/v1/tasks/%d/report' % task.id)
    assert r.status_code == 409


def test_report_rejects_unknown_format(client, db, make_task):
    task = make_task()
    _seed(db, task)
    assert client.get('/api/v1/tasks/%d/report?format=pdf'
                      % task.id).status_code == 400


def test_report_localizes_insufficient_evidence(client, db, make_task):
    task = make_task()
    session = _seed(db, task)
    db.add(DiagnosticEvent(task_id=task.id, session_id=session.id, rule_id='CAP-001',
                           severity=DiagnosticSeverity.INFO, evidence_level='insufficient',
                           title='观察窗口有限'))
    db.commit()
    response = client.get(f'/api/v1/tasks/{task.id}/report?format=md')
    assert response.status_code == 200
    assert '证据等级：证据不足' in response.text
    assert 'EvidenceLevel.' not in response.text
