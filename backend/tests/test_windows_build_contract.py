from pathlib import Path


def test_windows_build_reports_missing_rust_toolchain():
    script = (Path(__file__).resolve().parents[2] / 'scripts' / 'build-windows.ps1').read_text(encoding='utf-8')
    assert 'Get-Command cargo' in script
    assert 'Native Shell desktop build needs Rust' in script
    assert '--locked' in script
    assert 'gb28181_scan.dll' in script


def test_desktop_close_has_bounded_exit():
    root = Path(__file__).resolve().parents[2]
    main = (root / 'desktop/src/main.rs').read_text(encoding='utf-8')
    shell = (root / 'desktop-nsh/App.tsx').read_text(encoding='utf-8')
    assert 'onClosePress={requestClose}' in shell
    assert 'drop(child.stdin.take())' in main
    assert 'JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE' in main
    assert 'child.try_wait()' in main


def test_offline_build_includes_dumpcap_and_real_versions():
    script = (Path(__file__).resolve().parents[2] / 'scripts' / 'offline' / 'build.py').read_text(encoding='utf-8')
    assert 'dumpcap.exe' in script
    assert 'tshark-version' in script
    assert 'webview-version' in script
    assert 'TShark 4.6.10' not in script


def test_offline_launcher_removes_stale_runtimes():
    launcher = (Path(__file__).resolve().parents[2] / 'scripts' / 'offline' / 'main.go').read_text(encoding='utf-8')
    assert 'removeOldRuntimes' in launcher
    assert 'os.RemoveAll' in launcher
