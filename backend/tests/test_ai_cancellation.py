"""AI 流式请求取消：客户端断开后 worker 与上游必须尽快停止。"""
import threading

import pytest

from app.services import ai


def test_generator_close_sets_cancel_event_and_stops_worker(db, make_task, monkeypatch):
    from app.models.entities import TaskStatus

    task = make_task(status=TaskStatus.COMPLETED)
    started = threading.Event()
    cancel_seen = threading.Event()
    observed = {}

    def fake_analyze(db_, task_id, on_delta=None, context=None, expert='general',
                     cancel_event=None):
        observed['cancel_event'] = cancel_event
        started.set()
        # 模拟一个持续生成的上游；客户端断开后 worker 必须自己停下来。
        while not cancel_event.wait(0.01):
            on_delta('token')
        cancel_seen.set()
        return ''

    monkeypatch.setattr(ai, 'analyze', fake_analyze)
    from app.api import ai as api_ai

    # The route exposes its cancel event on the response; simulate a client
    # abort by driving the raw generator and closing it.
    captured = {}
    original_response = api_ai.StreamingResponse

    class CapturingResponse(original_response):
        def __init__(self, content, *args, **kwargs):
            captured['gen'] = content
            super().__init__(content, *args, **kwargs)

    monkeypatch.setattr(api_ai, 'StreamingResponse', CapturingResponse)
    api_ai.analyze_stream(task.id, api_ai.AnalyzeIn(), db)
    gen = captured['gen']
    next(gen)  # worker starts and emits a delta
    assert started.wait(2)
    gen.close()
    assert cancel_seen.wait(2), 'worker did not stop after the generator was closed'
    assert observed['cancel_event'].is_set()


def test_post_with_precancelled_event_does_not_open_connection(monkeypatch):
    called = []

    def boom(*_args, **_kwargs):
        called.append(True)
        raise AssertionError('must not open an upstream connection')

    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    monkeypatch.setattr(ai, 'load_config', lambda: {})
    monkeypatch.setattr(ai.urllib.request, 'build_opener', boom)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(RuntimeError, match='请求已取消'):
        ai._post({}, lambda _: None, cancel_event=cancel)
    assert not called


def test_post_cancelled_midstream_closes_response_and_stops(monkeypatch):
    class Response:
        def __init__(self):
            self.closed = False
            self.read_count = 0

        def __iter__(self):
            def chunks():
                while True:
                    self.read_count += 1
                    yield b'data: {"choices":[{"delta":{"content":"partial"}}]}\n'
            return chunks()

        def close(self):
            self.closed = True

    class Opener:
        def __init__(self, response):
            self.response = response

        def open(self, request, timeout):
            return self.response

    response = Response()
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    monkeypatch.setattr(ai, 'load_config', lambda: {})
    monkeypatch.setattr(ai.urllib.request, 'build_opener', lambda *args: Opener(response))
    cancel = threading.Event()

    def on_delta(_value):
        # client disconnects while the first chunk is delivered
        cancel.set()
        raise AssertionError('delta delivered after client disconnected')

    with pytest.raises(RuntimeError, match='请求已取消'):
        ai._post({}, on_delta, cancel_event=cancel)
    assert response.closed
    assert response.read_count == 2  # 1 consumed + 1 prefetched by urllib, then stopped
