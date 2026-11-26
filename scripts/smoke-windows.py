"""Verify the ZIP can be extracted and run with a fresh data directory."""
import argparse
import ctypes
import hashlib
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

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    expected_host = exe.parent / 'shell' / 'AnalyzerShell.exe'
    GA_ROOT = 2

    @callback_type
    def find_window(hwnd, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not user32.IsWindowVisible(hwnd):
            return True
        # WebView2 会创建继承同一标题的子窗口，只有顶层窗口才响应关窗
        if user32.GetAncestor(hwnd, GA_ROOT) != hwnd:
            return True
        title = ctypes.create_unicode_buffer(160)
        user32.GetWindowTextW(hwnd, title, len(title))
        if '视联网分析工作台' in title.value:
            handle = kernel.OpenProcess(0x1000, False, pid.value)
            if handle:
                try:
                    path = ctypes.create_unicode_buffer(32768)
                    length = wintypes.DWORD(len(path))
                    if kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(length)) and Path(path.value) == expected_host:
                        handles.append(hwnd)
                finally:
                    kernel.CloseHandle(handle)
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
        # A visible HWND may precede the WebView2 event loop being ready.
        # Retry the normal close message without treating a forced kill as success.
        hwnd = wintypes.HWND(handles[0])
        deadline = time.monotonic() + 20
        while process.poll() is None and time.monotonic() < deadline:
            if user32.IsWindow(hwnd):
                assert user32.PostMessageW(hwnd, 0x0010, 0, 0), 'WM_CLOSE could not be queued'
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                continue
        assert process.returncode == 0, f'Desktop did not exit cleanly after WM_CLOSE (rc={process.returncode})'
        with socket.socket() as probe:
            probe.settimeout(1)
            assert probe.connect_ex(('127.0.0.1', port)) != 0, 'Engine still listening'
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)


def analyze_sample(base, sample):
    boundary = 'gb28181-portable-smoke'
    body = (f'--{boundary}\r\n'
            'Content-Disposition: form-data; name="file"; filename="gb28181-demo.pcap"\r\n'
            'Content-Type: application/octet-stream\r\n\r\n').encode()
    upload = urllib.request.Request(
        base + '/api/v1/tasks/upload', data=body + sample + f'\r\n--{boundary}--\r\n'.encode(),
        headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})
    with urllib.request.urlopen(upload, timeout=10) as response:
        task_id = json.load(response)['task_id']
    endpoint = f'{base}/api/v1/tasks/{task_id}'
    with urllib.request.urlopen(urllib.request.Request(endpoint + '/analyze', data=b''), timeout=10):
        pass
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        with urllib.request.urlopen(endpoint, timeout=5) as response:
            state = json.load(response)
        if state['status'] == 'completed':
            break
        assert state['status'] not in ('failed', 'cancelled'), state
        time.sleep(0.2)
    assert state['status'] == 'completed', state
    assert state['summary']['packet_count'] == 126
    with urllib.request.urlopen(endpoint + '/packets?page_size=1', timeout=5) as response:
        packet = json.load(response)['items'][0]
    with urllib.request.urlopen(f"{base}/api/v1/packets/{packet['id']}", timeout=10) as response:
        detail = json.load(response)
    assert bytes.fromhex(detail['raw_hex'])[26:30] == bytes([192, 168, 1, 10])
    assert any(field.get('offset') == 26 and field.get('size') == 4
               for layer in detail['layers'] for field in layer['fields']), 'Verified IP byte span missing'
    with urllib.request.urlopen(endpoint + '/report', timeout=5) as response:
        assert 'attachment' in response.headers.get('Content-Disposition', '')


def smoke(archive, browser_only=False, run_analysis=False):
    checksum_path = archive.with_suffix(archive.suffix + '.sha256')
    if checksum_path.is_file():
        expected = checksum_path.read_text(encoding='ascii').split()[0]
        with archive.open('rb') as file:
            assert hashlib.file_digest(file, 'sha256').hexdigest() == expected, 'Portable ZIP checksum mismatch'
    with tempfile.TemporaryDirectory(prefix='gb28181-smoke-', ignore_cleanup_errors=True) as temp:
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
                    sample = response.read()
                    assert sample[:4] == bytes.fromhex('d4 c3 b2 a1')
                with urllib.request.urlopen(f'{base}/api/v1/tasks', timeout=5) as response:
                    assert json.load(response)['items'] == []
                assert (root / 'data' / 'analyzer.db').is_file()
                if run_analysis:
                    assert health['dependencies']['tshark'], 'TShark required for the analysis smoke test'
                    analyze_sample(base, sample)
            except Exception:
                print(log_path.read_text(encoding='utf-8', errors='replace'))
                raise
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=10)
        if browser_only:
            starter = root / 'GB28181-Analyzer' / 'Start-Analyzer.cmd'
            result = subprocess.check_output(['cmd.exe', '/d', '/c', 'call', str(starter), '--version'],
                                             cwd=starter.parent, text=True, timeout=10).strip()
            assert result == version, f'Browser launcher returned an unexpected version: {result}'
        else:
            desktop_smoke(root)
        variant = 'browser' if browser_only else 'desktop'
        print(f'Portable {variant} ZIP smoke test passed ({version}).')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--browser-only', action='store_true')
    parser.add_argument('--analyze-sample', action='store_true', help='Run the bundled PCAP through TShark')
    args = parser.parse_args()
    smoke(args.archive, browser_only=args.browser_only, run_analysis=args.analyze_sample)
