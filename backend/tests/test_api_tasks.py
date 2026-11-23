#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""任务 API 与并发控制回归

覆盖三个曾经真实存在、后果不可逆的缺陷：
  1. 并发点击"开始分析"会起多个 worker，同时删同一批结果
  2. 源文件被清掉后重新分析，会先删光旧结果再失败
  3. 分析异常分支里 traceback 是局部名，抛 UnboundLocalError 掩盖真实异常
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time

import pytest
from sqlalchemy import select

from app.models.entities import (
    AnalysisTask, BusinessSession, MediaStream, TaskStatus,
)
from app.services import analyzer


def _wait_until(pred, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


def _add_old_result(db, task_id):
    """给任务造一份"上一次分析的结果"，用于验证不会被误删"""
    db.add(BusinessSession(task_id=task_id, session_type='live',
                           signal_status='success', media_status='received',
                           call_ids=['old-call-id']))
    db.add(MediaStream(task_id=task_id, ssrc=0x1234, transport='UDP',
                       start_time=0.0, end_time=1.0, packet_count=10))
    db.commit()


def _count_old_results(db, task_id):
    s = db.scalar(select(BusinessSession).where(
        BusinessSession.task_id == task_id))
    m = db.scalar(select(MediaStream).where(MediaStream.task_id == task_id))
    return (1 if s else 0) + (1 if m else 0)


def test_upload_cleans_file_when_database_flush_fails(db, tmp_path, monkeypatch):
    import asyncio
    import io
    from fastapi import UploadFile
    from app.api import tasks

    monkeypatch.setattr(tasks.settings, 'UPLOAD_DIR', tmp_path)
    def fail_flush():
        raise RuntimeError('database unavailable')
    monkeypatch.setattr(db, 'flush', fail_flush)
    upload = UploadFile(filename='test.pcap', file=io.BytesIO(b'\xd4\xc3\xb2\xa1' + b'\x00' * 24))
    with pytest.raises(RuntimeError, match='database unavailable'):
        asyncio.run(tasks.upload_file(upload, db))
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------
# 1. 并发触发
# ---------------------------------------------------------------
def test_concurrent_analyze_starts_only_one_worker(client, db, make_task,
                                                   monkeypatch):
    task = make_task(path=__file__)          # 文件存在即可，不会真被解析

    started = threading.Event()
    release = threading.Event()

    def fake_run(_db, _task_id):
        started.set()
        release.wait(10)

    monkeypatch.setattr(analyzer, 'run_analysis', fake_run)

    r1 = client.post('/api/v1/tasks/%d/analyze' % task.id)
    assert r1.status_code == 200, r1.text
    assert started.wait(5), 'worker 未启动'

    # 第二次点击：必须 409，而不是再起一个线程
    r2 = client.post('/api/v1/tasks/%d/analyze' % task.id)
    assert r2.status_code == 409, r2.text
    assert '正在分析' in r2.json()['error']

    from app.api import tasks as tasks_api
    with tasks_api._run_lock:
        assert task.id in tasks_api._running

    release.set()
    assert _wait_until(lambda: not _running_has(task.id)), \
        'worker 结束后未归还并发槽位'


def _running_has(task_id):
    from app.api import tasks as tasks_api
    with tasks_api._run_lock:
        return task_id in tasks_api._running


def test_many_concurrent_requests_start_exactly_one_worker(client, db,
                                                           make_task,
                                                           monkeypatch):
    """真实并发：8 个线程同时打，只能有 1 个 200，其余 409"""
    task = make_task(path=__file__)

    calls = []
    started = threading.Event()
    release = threading.Event()

    def fake_run(_db, task_id):
        calls.append(task_id)
        started.set()
        release.wait(10)

    monkeypatch.setattr(analyzer, 'run_analysis', fake_run)

    codes = []
    lock = threading.Lock()

    def hit():
        r = client.post('/api/v1/tasks/%d/analyze' % task.id)
        with lock:
            codes.append(r.status_code)

    threads = [threading.Thread(target=hit) for _ in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(20)

    assert started.wait(5)
    assert codes.count(200) == 1, codes
    assert codes.count(409) == 7, codes
    assert len(calls) == 1, '启动了 %d 个 worker' % len(calls)

    release.set()
    assert _wait_until(lambda: not _running_has(task.id))


def test_analyze_rejected_while_slot_busy(client, db, make_task, monkeypatch):
    """并发上限生效时返回 429，且不会污染槽位"""
    from app.api import tasks as tasks_api

    a = make_task(name='A', path=__file__)
    b = make_task(name='B', path=__file__)

    started = threading.Event()
    release = threading.Event()

    def fake_run(_db, _task_id):
        started.set()
        release.wait(10)

    monkeypatch.setattr(analyzer, 'run_analysis', fake_run)

    assert client.post('/api/v1/tasks/%d/analyze' % a.id).status_code == 200
    assert started.wait(5)

    # 上限是 2：再占一个（手工塞），第三个应 429
    with tasks_api._run_lock:
        tasks_api._running[999999] = True
    try:
        r = client.post('/api/v1/tasks/%d/analyze' % b.id)
        assert r.status_code == 429, r.text
        assert b.id not in tasks_api._running
    finally:
        with tasks_api._run_lock:
            tasks_api._running.pop(999999, None)

    release.set()
    assert _wait_until(lambda: not _running_has(a.id))


def test_delete_rejected_while_running(client, db, make_task, monkeypatch):
    task = make_task(path=__file__)
    started = threading.Event()
    release = threading.Event()

    def fake_run(_db, _task_id):
        started.set()
        release.wait(10)

    monkeypatch.setattr(analyzer, 'run_analysis', fake_run)
    assert client.post('/api/v1/tasks/%d/analyze' % task.id).status_code == 200
    assert started.wait(5)

    r = client.delete('/api/v1/tasks/%d' % task.id)
    assert r.status_code == 409, r.text
    assert db.get(AnalysisTask, task.id) is not None

    release.set()
    assert _wait_until(lambda: not _running_has(task.id))


# ---------------------------------------------------------------
# 2. 源文件缺失时重新分析
# ---------------------------------------------------------------
def test_reanalyze_with_missing_file_keeps_old_results(client, db, make_task):
    task = make_task(path='C:/nonexistent/never-there.pcap')
    _add_old_result(db, task.id)
    assert _count_old_results(db, task.id) == 2

    r = client.post('/api/v1/tasks/%d/analyze' % task.id)
    assert r.status_code == 409, r.text
    assert '源文件' in r.json()['error']

    db.expire_all()
    assert _count_old_results(db, task.id) == 2, '旧分析结果被删掉了'


def test_run_analysis_missing_file_does_not_wipe(db, make_task):
    """即使绕过 API 直接调 service，也不能先删后失败"""
    task = make_task(path='C:/nonexistent/never-there.pcap')
    _add_old_result(db, task.id)

    from app.parsers import capture
    with pytest.raises(capture.CaptureError):
        analyzer.run_analysis(db, task.id)

    db.expire_all()
    assert _count_old_results(db, task.id) == 2
    t = db.get(AnalysisTask, task.id)
    assert t.status == TaskStatus.FAILED
    assert '源文件' in (t.error_message or '')


# ---------------------------------------------------------------
# 3. 异常路径
# ---------------------------------------------------------------
def test_unexpected_error_sets_failed_and_propagates_original(db, make_task,
                                                              monkeypatch):
    """回归：异常分支曾因 traceback 是局部名而抛 UnboundLocalError"""
    task = make_task(path=__file__)

    def boom(_db, _task):
        raise ValueError('故意失败')

    monkeypatch.setattr(analyzer, '_run', boom)

    with pytest.raises(ValueError, match='故意失败'):
        analyzer.run_analysis(db, task.id)

    db.expire_all()
    t = db.get(AnalysisTask, task.id)
    assert t.status == TaskStatus.FAILED
    assert 'ValueError' in t.error_message
    assert t.stage == '分析异常'


def test_cancelled_status_not_overwritten_by_completion(db, make_task,
                                                        monkeypatch):
    """用户点了取消，worker 跑完不能把状态改回 completed"""
    task = make_task(path=__file__)
    def fake_run(_db, t):
        # 模拟分析期间用户点取消：worker 内部看到的是旧对象，
        # 所以取消必须由另一个会话写库才贴近真实场景
        from app.core.db import SessionLocal
        s = SessionLocal()
        try:
            row = s.get(AnalysisTask, t.id)
            row.status = TaskStatus.CANCELLED
            row.stage = '已取消'
            s.commit()
        finally:
            s.close()

    monkeypatch.setattr(analyzer, '_run', fake_run)
    analyzer.run_analysis(db, task.id)

    db.expire_all()
    t = db.get(AnalysisTask, task.id)
    assert t.status == TaskStatus.CANCELLED
    assert t.stage == '已取消'


def test_failed_status_not_overwritten_when_cancelled(db, make_task,
                                                      monkeypatch):
    """取消后即使分析失败，也不该被改成 failed"""
    task = make_task(path=__file__)
    def boom(_db, t):
        from app.core.db import SessionLocal
        s = SessionLocal()
        try:
            row = s.get(AnalysisTask, t.id)
            row.status = TaskStatus.CANCELLED
            s.commit()
        finally:
            s.close()
        raise RuntimeError('取消后仍抛错')

    monkeypatch.setattr(analyzer, '_run', boom)
    with pytest.raises(RuntimeError):
        analyzer.run_analysis(db, task.id)

    db.expire_all()
    assert db.get(AnalysisTask, task.id).status == TaskStatus.CANCELLED


def test_cancelled_before_worker_preserves_results(db, make_task, monkeypatch):
    task = make_task(path=__file__)
    task.status = TaskStatus.CANCELLED
    task.stage = '已取消'
    db.commit()
    monkeypatch.setattr(analyzer, '_run', lambda *_: pytest.fail('cancelled worker ran'))
    analyzer.run_analysis(db, task.id)
    db.refresh(task)
    assert (task.status, task.stage) == (TaskStatus.CANCELLED, '已取消')


def test_cancel_terminates_owned_child_and_returns_slot(client, db, make_task, monkeypatch):
    from app.core import analysis_control

    started = threading.Event()
    children = []

    def analyze(_db, _task_id):
        with subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']) as proc:
            children.append(proc)
            with analysis_control.track(proc):
                started.set()
                proc.wait(timeout=10)

    monkeypatch.setattr(analyzer, 'run_analysis', analyze)
    task = make_task(path=__file__)
    endpoint = f'/api/v1/tasks/{task.id}'
    assert client.post(endpoint + '/analyze').status_code == 200
    assert started.wait(5)
    assert client.post(endpoint + '/cancel').json()['status'] == 'cancelled'
    assert _wait_until(lambda: not _running_has(task.id))
    assert children[0].returncode is not None
    assert client.get(endpoint).json()['stage'] == '已取消'


def test_task_without_tshark_reports_failure(client, db, make_task, monkeypatch):
    from app.parsers import capture

    monkeypatch.setattr(capture, 'TSHARK', None)
    task = make_task(path=__file__)
    endpoint = f'/api/v1/tasks/{task.id}'
    assert client.post(endpoint + '/analyze').status_code == 200
    assert _wait_until(lambda: not _running_has(task.id))
    detail = client.get(endpoint).json()
    assert detail['status'] == 'failed'
    assert 'tshark' in detail['error_message']
    assert client.get(endpoint + '/report').status_code == 409


def test_reanalysis_without_tshark_preserves_report(client, db, make_task, monkeypatch):
    from app.parsers import capture

    task = make_task(path=__file__, status=TaskStatus.COMPLETED)
    _add_old_result(db, task.id)
    endpoint = f'/api/v1/tasks/{task.id}'
    original = client.get(endpoint + '/report?format=json')
    assert original.status_code == 200
    monkeypatch.setattr(capture, 'TSHARK', None)
    assert client.post(endpoint + '/analyze').status_code == 409
    assert client.get(endpoint + '/report?format=json').json() == original.json()


def test_packet_range_sort_and_pagination(client, db, make_task):
    from app.models.entities import PacketIndex

    task = make_task(path=__file__)
    for number, timestamp in enumerate([None, 0.0, 1.0, 2.0], start=1):
        db.add(PacketIndex(task_id=task.id, file_id=task.files[0].id,
                           packet_number=number, timestamp=timestamp))
    db.commit()
    params = dict(time_from=0.0, time_to=1.0, descending=True, page_size=1)
    url = f'/api/v1/tasks/{task.id}/packets'
    for page, expected in enumerate([3, 2], start=1):
        result = client.get(url, params={**params, 'page': page}).json()
        assert result['total'] == 2
        assert [row['packet_number'] for row in result['items']] == [expected]
    assert client.get(url).json()['items'][0]['packet_number'] == 1
