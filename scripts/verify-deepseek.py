"""Live DeepSeek acceptance using synthetic observations in a disposable local database."""
import json
import os
import sys
import tempfile
from pathlib import Path


def collect(response):
    response.raise_for_status()
    chunks = []
    final = None
    for block in response.text.strip().split('\n\n'):
        event, payload = block.split('\n', 1)
        data = json.loads(payload.removeprefix('data: '))
        if event == 'event: error':
            raise RuntimeError(data['error'])
        if event == 'event: delta':
            chunks.append(data['t'])
        if event == 'event: done':
            final = data['text']
    if not final or not chunks or final != ''.join(chunks):
        raise RuntimeError('响应缺少完整的流式正文或结束事件')
    return final


def verify():
    from app.core.db import SessionLocal
    from app.main import app
    from app.models.entities import AnalysisTask, BusinessSession, TaskStatus
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        with SessionLocal() as db:
            task = AnalysisTask(name='合成点播验收', status=TaskStatus.COMPLETED,
                                summary={'session_count': 1, 'signal_success_rate': 100, 'total_streams': 0})
            db.add(task)
            db.flush()
            task_id = task.id
            db.add(BusinessSession(task_id=task_id, call_ids=['synthetic-call'], signal_status='success',
                                   media_status='no_media', negotiated_port=6000))
            db.commit()
        cfg = client.get('/api/v1/ai/config').json()
        if cfg['base_url'] != 'https://api.deepseek.com':
            raise RuntimeError('验收要求使用官方接口')
        base = '/api/v1/ai'
        preview = client.get(f'{base}/context/{task_id}')
        preview.raise_for_status()
        common = {'context_hash': preview.json()['context_hash'], 'expert': 'sip'}
        report = collect(client.post(f'{base}/analyze/{task_id}', json=common))
        followup = collect(client.post(f'{base}/chat/{task_id}', json={
            **common, 'history': [{'role':'assistant','content':report}],
            'question':'根据同一份摘要，说明已观察到的信令状态和一项仍需补充的媒体证据。'}))
        print(f"PASS model={cfg['model']} analysis_chars={len(report)} followup_chars={len(followup)}")


if __name__ == '__main__':
    if not os.environ.get('DEEPSEEK_API_KEY', '').strip():
        raise SystemExit('需要通过环境变量 DEEPSEEK_API_KEY 提供真实服务凭据')
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
    with tempfile.TemporaryDirectory(prefix='gb-live-ai-') as temporary:
        os.environ.update(DATA_DIR=temporary, DATABASE_URL='sqlite:///' + (Path(temporary)/'ai.db').as_posix(),
                          ALLOWED_HOSTS='testserver')
        try:
            verify()
        finally:
            from app.core.db import engine
            engine.dispose()
