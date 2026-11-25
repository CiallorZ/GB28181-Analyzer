"""User-controlled external tool paths."""
from __future__ import annotations

from pathlib import Path

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
