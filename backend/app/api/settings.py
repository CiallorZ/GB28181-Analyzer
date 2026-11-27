"""User-controlled external tool paths."""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from pathlib import Path
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..core import toolchain
from ..core.config import settings
from ..parsers import capture

router = APIRouter(prefix='/settings', tags=['settings'])


class ToolsIn(BaseModel):
    tshark: str | None = None
    capinfos: str | None = None
    ffmpeg: str | None = None
    ffprobe: str | None = None
    dumpcap: str | None = None


class ProbeIn(BaseModel):
    name: str
    path: str


def local_settings(request: Request):
    if settings.ALLOW_REMOTE_SETTINGS:
        return
    host = request.client.host if request.client else ''
    if host not in ('127.0.0.1', '::1', 'testclient'):
        raise HTTPException(403, '工具路径只能从本机修改')


@router.get('/tools')
def get_tools():
    return toolchain.status()


@router.put('/tools')
def set_tools(body: ToolsIn, _local=Depends(local_settings)):
    current = toolchain.load_config()
    for name in toolchain.TOOL_NAMES:
        value = getattr(body, name)
        if value is None:
            continue
        value = value.strip()
        if not value:
            current.pop(name, None)
            continue
        path = Path(value).expanduser()
        if not path.is_file():
            raise HTTPException(400, '%s 路径不存在或不是文件：%s' % (name, value))
        current[name] = str(path)
    toolchain.save_config(current)
    capture.refresh_tools()
    return toolchain.status()


@router.post('/tools/probe')
def probe_tool(body: ProbeIn, _local=Depends(local_settings)):
    return toolchain.probe_tool(body.name, body.path)


@router.delete('/tools')
def reset_tools(_local=Depends(local_settings)):
    toolchain.clear_config()
    capture.refresh_tools()
    return toolchain.status()


_picker = Lock()


@router.post('/tools/pick')
def pick_tool(request: Request, _local=Depends(local_settings)):
    if (os.environ.get('GB_DESKTOP_CAPTURE') != '1' or not hasattr(sys, '_MEIPASS')
            or not request.client or request.client.host != '127.0.0.1'):
        raise HTTPException(403, '请在 Windows 桌面版选择工具，或手工输入路径')
    if not _picker.acquire(blocking=False):
        raise HTTPException(409, '文件选择器已打开')
    try:
        pick = ctypes.CDLL(str(Path(sys._MEIPASS) / 'gb28181_scan.dll')).gb_pick_executable
        pick.argtypes = [ctypes.POINTER(ctypes.c_wchar), ctypes.c_uint32]
        pick.restype = ctypes.c_int
        path = ctypes.create_unicode_buffer(32768)
        if pick(path, len(path)) < 0:
            raise HTTPException(503, '无法打开 Windows 文件选择器')
        return {'path': path.value or None}
    finally:
        _picker.release()


_install = Lock()


@router.post('/tools/install')
def install_tools(request: Request, _local=Depends(local_settings)):
    if (sys.platform != 'win32' or not hasattr(sys, '_MEIPASS')
            or os.environ.get('GB_DESKTOP_CAPTURE') != '1'
            or not request.client or request.client.host != '127.0.0.1'):
        raise HTTPException(403, '请在 Windows 桌面版安装依赖')
    if not _install.acquire(blocking=False):
        raise HTTPException(409, '安装正在进行中')
    try:
        tools = toolchain.status()['tools']
        groups = [('WiresharkFoundation.Wireshark', ('tshark', 'capinfos', 'dumpcap')),
                  ('Gyan.FFmpeg', ('ffmpeg', 'ffprobe'))]
        for package, names in groups:
            if all(tools[name]['available'] for name in names):
                continue
            local_app_data = os.environ.get('LOCALAPPDATA')
            if not local_app_data:
                raise HTTPException(503, '无法定位当前 Windows 用户的应用安装程序')
            winget = Path(local_app_data) / 'Microsoft/WindowsApps/winget.exe'
            if not winget.is_file():
                raise HTTPException(503, '请先通过 Microsoft Store 安装应用安装程序（WinGet）')
            result = subprocess.run([str(winget), 'install', '--exact', '--id', package,
                                     '--source', 'winget', '--accept-source-agreements',
                                     '--accept-package-agreements'], timeout=900,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode:
                raise HTTPException(502, f'{package} 安装未完成，退出码 {result.returncode}')
        return toolchain.status()
    except OSError:
        raise HTTPException(503, '无法启动 WinGet，请检查应用安装程序是否可用')
    except subprocess.TimeoutExpired:
        raise HTTPException(504, '安装超时，请检查网络后重试')
    finally:
        try:
            capture.refresh_tools()
        finally:
            _install.release()
