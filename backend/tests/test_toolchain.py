import pytest

from app.core import toolchain
from app.parsers import capture


@pytest.fixture(autouse=True)
def reset_tool_config():
    toolchain.clear_config()
    capture.refresh_tools()
    yield
    toolchain.clear_config()
    capture.refresh_tools()


def test_manual_path_wins_over_environment(tmp_path, monkeypatch):
    manual = tmp_path / 'manual-tshark.exe'
    environment = tmp_path / 'env-tshark.exe'
    manual.write_bytes(b'MZ')
    environment.write_bytes(b'MZ')
    monkeypatch.setenv('TSHARK_PATH', str(environment))

    toolchain.save_config({'tshark': str(manual)})
    assert toolchain.find_tool('tshark') == str(manual)
    state = toolchain.status()['tools']['tshark']
    assert state['source'] == 'manual'
    assert state['available'] is True

    toolchain.clear_config()
    assert toolchain.find_tool('tshark') == str(environment)


def test_tool_api_saves_and_resets_manual_path(client, tmp_path):
    manual = tmp_path / 'custom-tshark.exe'
    manual.write_bytes(b'MZ')

    response = client.put('/api/v1/settings/tools', json={'tshark': str(manual)})
    assert response.status_code == 200
    assert response.json()['tools']['tshark']['source'] == 'manual'
    assert client.get('/api/v1/health').json()['tshark_path'] == str(manual)

    reset = client.delete('/api/v1/settings/tools')
    assert reset.status_code == 200
    assert reset.json()['tools']['tshark']['configured'] is None


def test_tool_api_rejects_missing_path(client, tmp_path):
    response = client.put('/api/v1/settings/tools', json={
        'ffmpeg': str(tmp_path / 'missing.exe'),
    })
    assert response.status_code == 400
    assert '路径不存在' in response.json()['error']

