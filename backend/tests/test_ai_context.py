from app.services import ai


def test_context_does_not_claim_video_reconstruction_is_unimplemented(db, make_task):
    task = make_task()
    context = ai.build_context(db, task.id)
    assert '未实现视频解码' not in context
    assert '视频重建结果不等于客户端实际播放成功' in context


def test_connection_accepts_environment_key(monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    monkeypatch.setattr(ai, 'load_config', lambda: {})
    monkeypatch.setattr(ai, '_post', lambda body: 'OK')
    assert ai.test_connection() == 'OK'


def test_preview_and_analysis_use_same_context(client, db, make_task, monkeypatch):
    from app.models.entities import TaskStatus, MediaStream

    task = make_task(status=TaskStatus.COMPLETED)
    for ssrc in (None, 0, 37):
        db.add(MediaStream(task_id=task.id, ssrc=ssrc, start_time=0, end_time=1))
    db.add(MediaStream(task_id=task.id, ssrc=48, start_time=0, end_time=1, codec='H.264',
                       rebuild_error='private-video-path', extra={'rtcp': {
                           'fraction_lost_latest': 0, 'peer_jitter_ms': 1.25, 'rtt_ms_latest': 14.5}}))
    db.commit()
    preview = client.get(f'/api/v1/ai/context/{task.id}')
    assert preview.status_code == 200
    data = preview.json()
    for value in ('SSRC=未知 ', 'SSRC=0x00000000 ', 'SSRC=0x00000025 '):
        assert data['context'].count(value) == 1
    assert '对端最近报告丢包=0.00%' in data['context']
    assert '对端最近报告抖动=1.25 ms' in data['context']
    assert 'RTCP RTT=14.50 ms' in data['context']
    assert '未生成重建预览' in data['context'] and 'private-video-path' not in data['context']
    seen = {}

    def fake_analyze(db, task_id, on_delta=None, context=None, expert='general'):
        seen['context'] = context
        return '报告'

    monkeypatch.setattr(ai, 'analyze', fake_analyze)
    response = client.post(f'/api/v1/ai/analyze/{task.id}', json={'context_hash': data['context_hash']})
    assert response.status_code == 200
    assert 'event: done' in response.text
    assert seen['context'] == data['context']
    stale = client.post(f'/api/v1/ai/analyze/{task.id}', json={'context_hash': 'stale'})
    assert stale.status_code == 409


def test_preview_requires_completed_task(client, make_task):
    task = make_task()
    assert client.get(f'/api/v1/ai/context/{task.id}').status_code == 400
    assert client.get('/api/v1/ai/context/999999').status_code == 404


def test_context_prioritizes_diagnostics_and_discloses_truncation(db, make_task):
    from app.models.entities import DiagnosticEvent, DiagnosticSeverity

    task = make_task()
    for i in range(31):
        db.add(DiagnosticEvent(task_id=task.id, rule_id='INFO',
                               severity=DiagnosticSeverity.INFO,
                               title=f'info-{i}', timestamp=i))
    db.add(DiagnosticEvent(task_id=task.id, rule_id='CRITICAL',
                           severity=DiagnosticSeverity.CRITICAL,
                           title='重要事件', timestamp=100))
    db.commit()
    context = ai.build_context(db, task.id)
    assert '列出 30 / 32 条' in context
    assert '[critical]' in context
    assert '重要事件' not in context
    assert '摘要可能只列出部分' in context


def test_stream_requires_upstream_completion_marker(monkeypatch):
    import pytest

    class Response:
        def __init__(self, lines):
            self.lines = lines
            self.closed = False

        def __iter__(self):
            return iter(self.lines)

        def close(self):
            self.closed = True

    class Opener:
        def __init__(self, response):
            self.response = response

        def open(self, request, timeout):
            return self.response

    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    monkeypatch.setattr(ai, 'load_config', lambda: {})
    chunk = b'data: {"choices":[{"delta":{"content":"partial"}}]}\n'
    truncated = Response([chunk])
    monkeypatch.setattr(ai.urllib.request, 'build_opener', lambda *args: Opener(truncated))
    with pytest.raises(RuntimeError, match='响应不完整'):
        ai._post({}, lambda value: None)
    assert truncated.closed

    complete = Response([chunk, b'data: [DONE]\n'])
    monkeypatch.setattr(ai.urllib.request, 'build_opener', lambda *args: Opener(complete))
    assert ai._post({}, lambda value: None) == 'partial'
    assert complete.closed


def test_context_hides_sensitive_fields_and_chat_reuses_preview(client, db, make_task, monkeypatch):
    from app.models.entities import BusinessSession, DiagnosticEvent, DiagnosticSeverity, TaskStatus

    task = make_task(name='secret-camera', status=TaskStatus.COMPLETED)
    db.add(BusinessSession(task_id=task.id, session_type='live', device_id='34020000001310000001',
                           negotiated_ip='2001:db8::1', negotiated_port=8808, call_ids=[]))
    db.add(DiagnosticEvent(task_id=task.id, rule_id='MED-001', severity=DiagnosticSeverity.WARNING,
                           title='secret-camera', description='private 192.0.2.1', timestamp=1))
    db.commit()
    preview = client.get(f'/api/v1/ai/context/{task.id}').json()
    context = preview['context']
    for secret in ('secret-camera', '34020000001310000001', '2001:db8::1', '192.0.2.1'):
        assert secret not in context
    assert '设备1' in context and '地址1:8808' in context
    captured = {}

    def fake_chat(db, task_id, history, question, on_delta=None, context=None, expert='general'):
        captured['context'] = context
        return '回答'

    monkeypatch.setattr(ai, 'chat', fake_chat)
    payload = {'question': '下一步?', 'history': [], 'context_hash': preview['context_hash']}
    response = client.post(f'/api/v1/ai/chat/{task.id}', json=payload)
    assert response.status_code == 200 and 'event: done' in response.text
    assert captured['context'] == context
    payload['context_hash'] = 'stale'
    assert client.post(f'/api/v1/ai/chat/{task.id}', json=payload).status_code == 409
