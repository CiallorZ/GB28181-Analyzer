from pathlib import Path


def test_windows_build_reports_missing_rust_toolchain():
    script = (Path(__file__).resolve().parents[2] / 'scripts' / 'build-windows.ps1').read_text(encoding='utf-8')
    assert 'Get-Command cargo' in script
    assert 'Tauri desktop build needs Rust' in script
    assert '--locked' in script
    main = (Path(__file__).resolve().parents[2] / 'desktop' / 'src' / 'main.rs').read_text(encoding='utf-8')
    assert 'set_analysis_busy' in main
    assert 'pick_executable' in main
    assert 'generate_handler![set_analysis_busy, pick_executable]' in main


def test_desktop_close_has_bounded_exit():
    # WebView2 卸载卡住时，关窗必须仍能在有限时间内结束进程
    main = (Path(__file__).resolve().parents[2] / 'desktop' / 'src' / 'main.rs').read_text(encoding='utf-8')
    assert 'CloseRequested' in main
    assert 'std::process::exit(0)' in main
    assert 'Duration::from_secs(6)' in main

    assert 'CloseRequested' in main
    assert 'prevent_close' in main


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
