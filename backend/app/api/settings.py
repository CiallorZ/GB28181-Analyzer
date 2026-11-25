"""User-controlled external tool paths."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..core import toolchain
from ..parsers import capture

router = APIRouter(prefix='/settings', tags=['settings'])


class ToolsIn(BaseModel):
    tshark: str | None = None
    capinfos: str | None = None
    ffmpeg: str | None = None
    ffprobe: str | None = None
    dumpcap: str | None = None


@router.get('/tools')
def get_tools():
    return toolchain.status()


@router.put('/tools')
def set_tools(body: ToolsIn):
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


@router.delete('/tools')
def reset_tools():
    toolchain.clear_config()
    capture.refresh_tools()
    return toolchain.status()
