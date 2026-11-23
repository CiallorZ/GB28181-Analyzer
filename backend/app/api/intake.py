"""Resumable capture import and bounded local desktop recording."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.db import get_db
from ..core.security import looks_like_capture
from ..models.entities import CaptureFile
from ..parsers import capture
from .tasks import register_capture

router = APIRouter(prefix='/intake')
lock = threading.Lock()
recording = threading.Lock()
CHUNK = 8 * 1024 * 1024


class Manifest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0, le=16 * 1024**3)
    hashes: list[str] = Field(min_length=1, max_length=2048)


def directory(key):
    if not re.fullmatch('[a-f0-9]{64}', key):
        raise HTTPException(404, '上传标识无效')
    return settings.UPLOAD_DIR / ('.resume-' + key)


@router.post('/resume')
def resume(body: Manifest, db: Session = Depends(get_db)):
    if Path(body.name).suffix.lower() not in settings.ALLOWED_EXT or len(body.hashes) != (body.size + CHUNK-1)//CHUNK or not all(re.fullmatch('[a-f0-9]{64}', h) for h in body.hashes):
        raise HTTPException(400, '文件清单无效')
    raw = json.dumps(body.model_dump(), sort_keys=True).encode()
    key = hashlib.sha256(raw).hexdigest()
    folder = directory(key)
    dest = settings.UPLOAD_DIR / (key + Path(body.name).suffix.lower())
    with lock:
        prior = db.scalar(select(CaptureFile).where(CaptureFile.stored_path == str(dest)))
        if prior and dest.is_file():
            return {'key': key, 'received': list(range(len(body.hashes)))}
        cutoff = time.time() - 7 * 86400
        for old in settings.UPLOAD_DIR.glob('.resume-*'):
            if old != folder and old.is_dir() and old.stat().st_mtime < cutoff:
                shutil.rmtree(old, ignore_errors=True)
        folder.mkdir(exist_ok=True)
        temp = folder / 'manifest.tmp'
        temp.write_bytes(raw)
        temp.replace(folder / 'manifest')
        return {'key': key, 'received': [int(p.name) for p in folder.iterdir() if p.name.isdigit()]}


def manifest(folder):
    try:
        return Manifest.model_validate_json((folder / 'manifest').read_bytes())
    except FileNotFoundError:
        raise HTTPException(404, '请重新选择抓包')


@router.put('/resume/{key}/{index}')
def part(key: str, index: int, file: UploadFile = File(...)):
    folder = directory(key)
    body = manifest(folder)
    if not 0 <= index < len(body.hashes):
        raise HTTPException(400, '分片编号无效')
    data = file.file.read(CHUNK+1)
    if len(data) != min(CHUNK, body.size-index*CHUNK) or hashlib.sha256(data).hexdigest() != body.hashes[index]:
        raise HTTPException(400, '分片校验失败')
    if index == 0 and not looks_like_capture(data):
        raise HTTPException(400, '无效抓包头')
    with lock:
        tmp = folder / 'chunk.tmp'
        tmp.write_bytes(data)
        tmp.replace(folder / str(index))
    return {'received': index}


@router.post('/resume/{key}/finish')
def finish(key: str, db: Session = Depends(get_db)):
    folder = directory(key)
    with lock:
        body = manifest(folder)
        dest = settings.UPLOAD_DIR / (key + Path(body.name).suffix.lower())
        prior = db.scalar(select(CaptureFile).where(CaptureFile.stored_path == str(dest)))
        if prior and dest.is_file():
            return {'task_id': prior.task_id, 'size': prior.file_size}
        if shutil.disk_usage(folder).free < body.size:
            raise HTTPException(507, '剩余空间不足以合并分片，释放空间后可重试')
        digest = hashlib.sha256()
        temp = folder / 'joining'
        try:
            with temp.open('wb') as out:
                for i in range(len(body.hashes)):
                    part = folder / str(i)
                    if not part.is_file():
                        raise HTTPException(409, '仍有未上传分片')
                    data = part.read_bytes()
                    if hashlib.sha256(data).hexdigest() != body.hashes[i]:
                        part.unlink()
                        raise HTTPException(409, '分片校验失败，请重新选择文件')
                    digest.update(data)
                    out.write(data)
            temp.replace(dest)
            result = register_capture(db, body.name, dest, body.size, digest.hexdigest())
            for i in range(len(body.hashes)):
                (folder / str(i)).unlink(missing_ok=True)
            return result
        finally:
            temp.unlink(missing_ok=True)


class Recording(BaseModel):
    interface: int = Field(ge=1, le=65535)
    seconds: int = Field(ge=1, le=120)


def dumpcap():
    if os.getenv('GB_DESKTOP_CAPTURE') != '1':
        raise HTTPException(403, '实时采集仅在本机桌面工作台提供')
    path = shutil.which('dumpcap') or (Path(capture.TSHARK).with_name('dumpcap.exe') if capture.TSHARK else None)
    if not path or not Path(path).is_file():
        raise HTTPException(503, '未找到 dumpcap，请安装 Wireshark 和 Npcap')
    return str(path)


@router.get('/interfaces')
def interfaces():
    result = capture._run([dumpcap(), '-D'], 8, '读取网卡')
    if result.returncode:
        raise HTTPException(503, '无法读取网卡，请检查 Npcap 和采集权限')
    return [{'id': int(m[1]), 'name': m[2]} for m in re.finditer(r'^(\d+)\. (.+)$', result.stdout, re.M)]


@router.post('/record')
def record(body: Recording, db: Session = Depends(get_db)):
    tool = dumpcap()
    if not recording.acquire(blocking=False):
        raise HTTPException(409, '正在采集，请等待完成')
    dest = settings.UPLOAD_DIR / (uuid.uuid4().hex + '.pcapng')
    try:
        result = subprocess.run([tool, '-p', '-i', str(body.interface), '-a', f'duration:{body.seconds}',
                                 '-a', 'filesize:65536', '-w', str(dest)], capture_output=True,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=body.seconds+15)
        if result.returncode or not dest.is_file():
            raise HTTPException(422, '采集失败，请检查网卡及 Npcap 权限')
        return register_capture(db, f'网卡{body.interface}.pcapng', dest, dest.stat().st_size(), capture.file_checksum(str(dest)))
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    finally:
        recording.release()
