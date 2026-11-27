import hashlib

from app.api import evidence
from app.models.entities import TaskStatus


def test_resume_checks_bytes_and_survives_retry(client):
    data = bytes.fromhex('d4c3b2a1') + bytes(80)
    manifest = {'name': 'demo.pcap', 'size': len(data), 'hashes': [hashlib.sha256(data).hexdigest()]}
    base = '/api/v1/intake/resume'
    key = client.post(base, json=manifest).json()['key']
    url = f'{base}/{key}'
    assert client.post(url + '/finish').status_code == 409
    assert client.put(url + '/0', files={'file': ('part', b'bad')}).status_code == 400
    assert client.put(url + '/0', files={'file': ('part', data)}).is_success
    assert client.post(base, json=manifest).json()['received'] == [0]
    task = client.post(url + '/finish').json()['task_id']
    assert client.post(url + '/finish').json()['task_id'] == task


def test_resume_enforces_configured_upload_limit(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, 'MAX_UPLOAD_MB', 1)
    manifest = {'name': 'too-large.pcap', 'size': 1024**2 + 1, 'hashes': ['0' * 64]}
    response = client.post('/api/v1/intake/resume', json=manifest)
    assert response.status_code == 413
    assert '1 MB' in response.json()['error']


def test_multichunk_resume_keeps_uploaded_prefix(client, db):
    from app.api.intake import CHUNK
    from app.models.entities import CaptureFile

    first = bytes.fromhex('d4c3b2a1') + bytes(CHUNK - 4)
    last = b'last fragment'
    manifest = {'name': 'resume.pcap', 'size': len(first) + len(last),
                'hashes': [hashlib.sha256(part).hexdigest() for part in (first, last)]}
    base = '/api/v1/intake/resume'
    key = client.post(base, json=manifest).json()['key']
    url = f'{base}/{key}'
    assert client.put(url+'/0', files={'file': ('chunk', first)}).is_success
    assert client.post(url+'/finish').status_code == 409
    assert client.post(base, json=manifest).json() == {'key': key, 'received': [0]}
    assert client.put(url+'/1', files={'file': ('chunk', last)}).is_success
    response = client.post(url+'/finish')
    assert response.is_success
    stored = db.query(CaptureFile).filter_by(task_id=response.json()['task_id']).one()
    assert stored.checksum == hashlib.sha256(first + last).hexdigest()


def test_report_blocks_and_export(client, make_task, tmp_path, monkeypatch):
    path = tmp_path / 'evidence.pcap'
    path.touch()
    task = make_task(path=str(path), status=TaskStatus.COMPLETED)
    base = f'/api/v1/tasks/{task.id}'
    monkeypatch.setattr(evidence, 'tshark', lambda args: '15\t0x1,0x2\t0,64\t0,4\t4,10\t\n')
    reports = client.get(base + '/rtcp').json()
    assert [r['loss'] for r in reports] == [0, 25]
    assert reports[1]['delay'] is None
    assert client.get(base + '/topology').json() == []
    assert '<table>' in client.get(base + '/report?format=html').text
    assert client.get(base + '/report?format=csv').content.startswith(b'\xef\xbb\xbf')


def test_recording_requires_desktop(client, monkeypatch):
    monkeypatch.delenv('GB_DESKTOP_CAPTURE', raising=False)
    assert client.get('/api/v1/intake/interfaces').status_code == 403
    assert client.post('/api/v1/intake/record', json={'interface':1, 'seconds':121}).status_code == 422


def test_expert_persists_in_report_and_chat(monkeypatch):
    from app.services import ai
    messages = []
    monkeypatch.setattr(ai, '_post', lambda body, callback: messages.append(body['messages'][0]['content']))
    ai.analyze(None, 1, context='synthetic', expert='sip')
    ai.chat(None, 1, [], 'synthetic?', context='synthetic', expert='sip')
    assert all(ai.EXPERTS['sip'] in m for m in messages)


def test_finished_recording_registers_capture(client, monkeypatch):
    from pathlib import Path
    from subprocess import CompletedProcess
    from app.api import intake

    def run(cmd, **kwargs):
        Path(cmd[-1]).write_bytes(bytes.fromhex('0a0d0d0a') + bytes(76))
        return CompletedProcess(cmd, 0)

    monkeypatch.setattr(intake, 'dumpcap', lambda: 'dumpcap')
    monkeypatch.setattr(intake.subprocess, 'run', run)
    res = client.post('/api/v1/intake/record', json={'interface': 1, 'seconds': 2})
    assert res.status_code == 200 and res.json()['size'] == 80
    assert client.get('/api/v1/tasks/' + str(res.json()['task_id'])).is_success

def test_resumable_disk_full_keeps_confirmed_chunks(client, monkeypatch, tmp_path):
    import errno
    from pathlib import Path

    from app.api import intake
    from app.core.config import settings

    monkeypatch.setattr(settings, 'UPLOAD_DIR', tmp_path)
    monkeypatch.setattr(intake, 'CHUNK', 8)
    chunks = [bytes.fromhex('d4c3b2a1') + bytes(4), b'last']
    manifest = {'name': 'space.pcap', 'size': 12,
                'hashes': [hashlib.sha256(chunk).hexdigest() for chunk in chunks]}
    base = '/api/v1/intake/resume'
    key = client.post(base, json=manifest).json()['key']
    url = f'{base}/{key}'
    assert client.put(url+'/0', files={'file': ('chunk', chunks[0])}).is_success
    write_bytes = Path.write_bytes

    def disk_full(path, data):
        if path.name == 'chunk.tmp':
            write_bytes(path, data[:2])
            raise OSError(errno.ENOSPC, 'disk full')
        return write_bytes(path, data)

    with monkeypatch.context() as patch:
        patch.setattr(Path, 'write_bytes', disk_full)
        assert client.put(url+'/1', files={'file': ('chunk', chunks[1])}).status_code == 507
    assert not (intake.directory(key) / 'chunk.tmp').exists()
    assert client.post(base, json=manifest).json()['received'] == [0]
    assert client.put(url+'/1', files={'file': ('chunk', chunks[1])}).is_success
    assert client.post(url+'/finish').is_success
