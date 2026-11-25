"""External tool discovery with a user override stored in the data directory."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from .config import settings

TOOL_NAMES = ('tshark', 'capinfos', 'ffmpeg', 'ffprobe', 'dumpcap')
ENV_KEYS = {
    'tshark': 'TSHARK_PATH',
    'capinfos': 'CAPINFOS_PATH',
    'ffmpeg': 'FFMPEG_PATH',
    'ffprobe': 'FFPROBE_PATH',
    'dumpcap': 'DUMPCAP_PATH',
}
CONFIG_PATH = settings.DATA_DIR / 'tools.json'
CANDIDATES = {
    'tshark': [
        r'C:\Program Files\Wireshark\tshark.exe',
        r'D:\Program Files\Wireshark\tshark.exe',
    ],
    'capinfos': [
        r'C:\Program Files\Wireshark\capinfos.exe',
        r'D:\Program Files\Wireshark\capinfos.exe',
    ],
    'dumpcap': [
        r'C:\Program Files\Wireshark\dumpcap.exe',
        r'D:\Program Files\Wireshark\dumpcap.exe',
    ],
    'ffmpeg': [
        r'C:\Program Files\ffmpeg\bin\ffmpeg.exe',
        r'D:\Program Files\ffmpeg-7.0.2-full_build\bin\ffmpeg.exe',
    ],
    'ffprobe': [
        r'C:\Program Files\ffmpeg\bin\ffprobe.exe',
        r'D:\Program Files\ffmpeg-7.0.2-full_build\bin\ffprobe.exe',
    ],
}


def _valid_file(value: str | None) -> str | None:
    if not value:
        return None
    path = Path(value).expanduser()
    return str(path) if path.is_file() else None


def load_config() -> dict:
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {name: str(data[name]).strip() for name in TOOL_NAMES
            if isinstance(data.get(name), str) and data[name].strip()}


def save_config(values: dict) -> dict:
    clean = {name: str(values[name]).strip() for name in TOOL_NAMES
             if values.get(name)}
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = CONFIG_PATH.with_suffix('.tmp')
    temp.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, CONFIG_PATH)
    return clean


def clear_config() -> None:
    CONFIG_PATH.unlink(missing_ok=True)


def _environment_candidates(name: str) -> list[tuple[str, str]]:
    out = []
    env_path = _valid_file(os.environ.get(ENV_KEYS[name]))
    if env_path:
        out.append((env_path, 'environment'))
    if name in ('capinfos', 'dumpcap'):
        tshark = _valid_file(os.environ.get(ENV_KEYS['tshark']))
        if tshark:
            out.append((str(Path(tshark).with_name(name + '.exe')), 'environment'))
    if name == 'ffprobe':
        ffmpeg = _valid_file(os.environ.get(ENV_KEYS['ffmpeg']))
        if ffmpeg:
            out.append((str(Path(ffmpeg).with_name('ffprobe.exe')), 'environment'))
    return out


def find_tool(name: str) -> str | None:
    if name not in TOOL_NAMES:
        return None
    configured = _valid_file(load_config().get(name))
    if configured:
        return configured
    for path, _source in _environment_candidates(name):
        if Path(path).is_file():
            return path
    found = shutil.which(name)
    if found:
        return found
    for path in CANDIDATES[name]:
        if Path(path).is_file():
            return path
    return None


def tool_source(name: str, path: str | None) -> str:
    if not path:
        return 'missing'
    if path == _valid_file(load_config().get(name)):
        return 'manual'
    if any(path == candidate for candidate, _source in _environment_candidates(name)):
        return 'environment'
    if path == shutil.which(name):
        return 'path'
    return 'auto'


def status() -> dict:
    configured = load_config()
    tools = {}
    for name in TOOL_NAMES:
        path = find_tool(name)
        configured_path = configured.get(name)
        tools[name] = {
            'path': path,
            'source': tool_source(name, path),
            'available': bool(path),
            'configured': configured_path,
            'configured_missing': bool(
                configured_path and not _valid_file(configured_path)
            ),
        }
    return {'config_path': str(CONFIG_PATH), 'tools': tools}
