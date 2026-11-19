#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0-15 回归：诊断必须先按严重度排序，再分页。

历史缺陷：先 `limit/offset` 再在 Python 里排序，导致第一页里可能一条
critical / warning 都没有，最该看的问题被翻页藏起来。
SQLite 里 Enum 存的是成员名（CRITICAL/WARNING/INFO），按字母序排是
CRITICAL → INFO → WARNING，warning 反而排到最后，所以用 warning 造样本
才能真正区分"按名字排序"和"按严重度排序"。
"""
from __future__ import annotations

from app.models.entities import DiagnosticEvent, DiagnosticSeverity


def _add(db, task_id, severity, n, ts_base):
    for i in range(n):
        db.add(DiagnosticEvent(
            task_id=task_id, rule_id='R-%s' % severity.name,
            severity=severity, title='%s-%d' % (severity.name, i),
            timestamp=ts_base + i, description=''))
    db.commit()


def test_diagnostics_sorted_before_pagination(client, db, make_task):
    task = make_task()
    _add(db, task.id, DiagnosticSeverity.INFO, 60, ts_base=0)
    _add(db, task.id, DiagnosticSeverity.WARNING, 5, ts_base=1000)

    r = client.get('/api/v1/tasks/%d/diagnostics?page=1&page_size=5' % task.id)
    assert r.status_code == 200
    body = r.json()

    assert body['total'] == 65
    assert len(body['items']) == 5
    # 第一页必须全是 warning，且按时间升序
    assert {i['severity'] for i in body['items']} == {'warning'}
    assert [i['timestamp'] for i in body['items']] == sorted(
        i['timestamp'] for i in body['items'])

    # 第二页开始才是 info
    r2 = client.get('/api/v1/tasks/%d/diagnostics?page=2&page_size=5' % task.id)
    assert len(r2.json()['items']) == 5
    assert {i['severity'] for i in r2.json()['items']} == {'info'}


def test_diagnostics_severity_filter_still_works(client, db, make_task):
    task = make_task()
    _add(db, task.id, DiagnosticSeverity.INFO, 3, ts_base=0)
    _add(db, task.id, DiagnosticSeverity.CRITICAL, 2, ts_base=100)

    r = client.get('/api/v1/tasks/%d/diagnostics?severity=critical' % task.id)
    body = r.json()
    assert body['total'] == 2
    assert all(i['severity'] == 'critical' for i in body['items'])
