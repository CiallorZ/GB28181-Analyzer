"""Exercise the application using two observation windows of the public SRS playback."""
import argparse
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SOURCE_SHA256 = '40cea5afc4ad535f85047cae8dc0edaec8028c24ed7e9f95eafaeb42300483c7'
WINDOW = 'not tcp.port == 9000 or frame.number <= 1600'


def import_capture(client, path):
    with path.open('rb') as f:
        response = client.post('/api/v1/tasks/upload', files={'file': (path.name, f)})
    response.raise_for_status()
    task_id = response.json()['task_id']
    endpoint = f'/api/v1/tasks/{task_id}'
    client.post(endpoint + '/analyze').raise_for_status()
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        response = client.get(endpoint)
        response.raise_for_status()
        status = response.json()['status']
        if status == 'completed':
            return task_id
        if status in ('failed', 'cancelled'):
            raise RuntimeError(f'{path.name}: {status}')
        time.sleep(0.25)
    raise TimeoutError(path.name)


def verify(source, output):
    from app.main import app
    from app.parsers import capture
    from fastapi.testclient import TestClient

    if not all((capture.TSHARK, capture.FFMPEG, capture.FFPROBE)):
        raise RuntimeError('需要 TShark、FFmpeg 和 FFprobe')
    if hashlib.sha256(source.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError('输入需要是 SRS 的 gb-media-ps-normal.pcapng')
    output.mkdir(parents=True, exist_ok=False)
    a, b = output / 'A-full.pcapng', output / 'B-short-media.pcapng'
    shutil.copyfile(source, a)
    subprocess.run([capture.TSHARK, '-n', '-r', str(a), '-Y', WINDOW, '-w', str(b)], check=True)
    with TestClient(app) as client:
        task_a = import_capture(client, a)
        task_b = import_capture(client, b)
        response = client.post('/api/v1/comparisons', json={
            'task_a_id': task_a, 'task_b_id': task_b, 'label_a': '完整观察', 'label_b': '模拟较短媒体窗口'})
        response.raise_for_status()
        detail = response.json()
        result = detail['result']
        assert not detail['stale'] and not result['truncated']
        assert result['totals']['sessions'] == result['totals']['streams'] == 1
        session, stream = result['sessions'][0], result['streams'][0]
        assert session['method'] == stream['method'] == 'exact'
        assert session['confidence'] == stream['confidence'] == 'high'
        assert session['evidence']['call_ids'] == ['854k7337207yxpfj']
        assert stream['fields']['ssrc'][2] == 'same'
        count_a, count_b, status = stream['fields']['packet_count']
        assert count_a > count_b > 0 and status == 'different'
        assert stream['fields']['rebuild'] == ['success', 'success', 'same']
        for side in 'ab':
            response = client.get(f"/api/v1/streams/{stream[side]}/video")
            response.raise_for_status()
            video = output / f'{side.upper()}.mp4'
            video.write_bytes(response.content)
            probe = subprocess.check_output([capture.FFPROBE, '-v', 'error', '-select_streams', 'v:0',
                '-show_entries', 'stream=width,height,codec_name', '-of', 'json', str(video)])
            info = json.loads(probe)['streams'][0]
            assert (info['width'], info['height']) == (640, 480)
            print(f"{video.name}: {info['codec_name']} {info['width']}x{info['height']}")
        url = f"/api/v1/comparisons/{detail['id']}/report"
        for fmt in ('md', 'json'):
            response = client.get(url, params={'format': fmt})
            response.raise_for_status()
            assert 'attachment' in response.headers['Content-Disposition']
            if fmt == 'json':
                assert response.json() == detail
            else:
                assert f'| packet_count | {count_a} | {count_b} | different |' in response.text
            (output / f'comparison.{fmt}').write_bytes(response.content)
        print(f"PASS Call-ID={session['evidence']['call_ids'][0]}, SSRC={stream['evidence']['ssrc']}, "
              f"media packets={count_a}/{count_b}, reports={output}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path, help='新的输出目录')
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
    with tempfile.TemporaryDirectory(prefix='gb-playback-') as temporary:
        os.environ.update(DATA_DIR=temporary, DATABASE_URL='sqlite:///' + (Path(temporary)/'verify.db').as_posix(),
                          ALLOWED_HOSTS='testserver', KEEP_TASKS='5', KEEP_DAYS='0')
        try:
            verify(args.source, args.output)
        finally:
            from app.core.db import engine
            engine.dispose()
            logging.shutdown()
