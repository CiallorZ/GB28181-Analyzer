"""Verify the ZIP can be extracted and run with a fresh data directory."""
import argparse
import ctypes
import json
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from ctypes import wintypes
from pathlib import Path


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def expect_ready(base, process):
    deadline = time.monotonic() + 14
    while time.monotonic() < deadline and process.poll() is None:
        try:
            with urllib.request.urlopen(f'{base}/api/v1/health', timeout=0.5) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.2)
    raise RuntimeError('Portable application did not start within 15 seconds.')


def desktop_smoke(root):
    """Open the actual WebView2 host, close its own window, then check the engine exits."""
    port = free_port()
    base = f'http://127.0.0.1:{port}'
    exe = root / 'GB28181-Analyzer' / 'GB28181-Analyzer.exe'
    process = subprocess.Popen([exe, '--port', str(port), '--data-dir', root / 'data'])
    handles = []
    user32 = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def find_window(hwnd, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == process.pid and user32.IsWindowVisible(hwnd):
            title = ctypes.create_unicode_buffer(160)
            user32.GetWindowTextW(hwnd, title, len(title))
            if '视联网分析工作台' in title.value:
                handles.append(hwnd)
        return True

    try:
        expect_ready(base, process)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and process.poll() is None and not handles:
            user32.EnumWindows(find_window, 0)
            time.sleep(0.2)
        assert handles, 'Desktop workbench window missing'
        with urllib.request.urlopen(base + '/api/v1/comparisons', timeout=5) as response:
            assert json.load(response) == {'total': 0, 'items': []}
        with urllib.request.urlopen(base + '/compare', timeout=5) as response:
            assert 'GB28181 Analyzer' in response.read().decode()
        user32.PostMessageW(wintypes.HWND(handles[0]), 0x0010, 0, 0)  # WM_CLOSE
        assert process.wait(timeout=20) == 0
        with socket.socket() as probe:
            probe.settimeout(1)
            assert probe.connect_ex(('127.0.0.1', port)) != 0, 'Engine still listening'
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)


def smoke(archive):
    with tempfile.TemporaryDirectory(prefix='gb28181-smoke-') as temp:
        root = Path(temp)
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(root)
        exe = root / 'GB28181-Analyzer' / 'engine' / 'AnalyzerEngine.exe'
        version = subprocess.check_output([exe, '--version'], text=True, timeout=10).strip()
        port = free_port()
        base = f'http://127.0.0.1:{port}'
        log_path = root / 'desktop.log'
        with log_path.open('wb') as log:
            process = subprocess.Popen(
                [exe, '--no-browser', '--port', str(port), '--data-dir', root / 'data'],
                stdout=log, stderr=subprocess.STDOUT,
            )
            try:
                health = expect_ready(base, process)
                assert health['status'] == 'ok' and health['version'] == version
                duplicate = subprocess.run(
                    [exe, '--no-browser', '--port', str(free_port()), '--data-dir', root / 'data'],
                    capture_output=True, text=True, timeout=10, check=False,
                )
                assert duplicate.returncode == 1 and 'Another Analyzer instance' in duplicate.stderr
                with urllib.request.urlopen(f'{base}/tasks/1', timeout=5) as response:
                    assert 'GB28181 Analyzer' in response.read().decode()
                with urllib.request.urlopen(f'{base}/samples/gb28181-demo.pcap', timeout=5) as response:
                    assert response.read(4) == bytes.fromhex('d4 c3 b2 a1')
                with urllib.request.urlopen(f'{base}/api/v1/tasks', timeout=5) as response:
                    assert json.load(response)['items'] == []
                assert (root / 'data' / 'analyzer.db').is_file()
            except Exception:
                print(log_path.read_text(encoding='utf-8', errors='replace'))
                raise
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=10)
        desktop_smoke(root)
        print(f'Portable ZIP smoke test passed ({version}).')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    smoke(parser.parse_args().archive)
