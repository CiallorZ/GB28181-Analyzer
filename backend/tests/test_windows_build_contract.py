from pathlib import Path


def test_windows_build_reports_missing_rust_toolchain():
    script = (Path(__file__).resolve().parents[2] / 'scripts' / 'build-windows.ps1').read_text(encoding='utf-8')
    assert 'Get-Command cargo' in script
    assert 'Tauri desktop build needs Rust' in script
    assert '--locked' in script
