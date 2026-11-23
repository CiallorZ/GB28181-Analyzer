#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M09 诊断查询 / M12 报文查看"""
from __future__ import annotations

import binascii
import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.db import get_db
from ..models.entities import AnalysisTask, DiagnosticEvent, PacketIndex
from ..parsers import capture
from ..services.diagnosis import severity_order_clause
from ..schemas import task as S

router = APIRouter(tags=['diagnostics'])


@router.get('/tasks/{task_id}/diagnostics', response_model=S.DiagnosticList)
def list_diagnostics(task_id: int, page: int = 1, page_size: int = 50,
                     severity: str | None = None,
                     rule_id: str | None = None,
                     db: Session = Depends(get_db)):
    page = max(1, page)
    page_size = min(200, max(1, page_size))

    stmt = select(DiagnosticEvent).where(DiagnosticEvent.task_id == task_id)
    if severity:
        stmt = stmt.where(DiagnosticEvent.severity == severity)
    if rule_id:
        stmt = stmt.where(DiagnosticEvent.rule_id == rule_id)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(severity_order_clause(DiagnosticEvent.severity),
                      DiagnosticEvent.timestamp, DiagnosticEvent.id)
        .offset((page - 1) * page_size).limit(page_size)).all()

    return S.DiagnosticList(
        total=total, page=page, page_size=page_size,
        items=[S.DiagnosticOut.model_validate(r) for r in rows])


@router.get('/tasks/{task_id}/rule-stats')
def rule_stats(task_id: int, db: Session = Depends(get_db)):
    """规则命中统计 —— 便于看哪类问题最突出"""
    rows = db.scalars(
        select(DiagnosticEvent).where(DiagnosticEvent.task_id == task_id)).all()
    by_rule = {}
    by_sev = {}
    by_evidence = {}
    for r in rows:
        by_rule[r.rule_id] = by_rule.get(r.rule_id, 0) + 1
        by_sev[r.severity] = by_sev.get(r.severity, 0) + 1
        by_evidence[r.evidence_level] = by_evidence.get(r.evidence_level, 0) + 1
    return {
        'by_rule': by_rule, 'by_severity': by_sev,
        'by_evidence': by_evidence, 'total': len(rows),
    }


# ---------------------------------------------------------------
# M12 报文查看
# ---------------------------------------------------------------
@router.get('/tasks/{task_id}/packets', response_model=S.PacketList)
def list_packets(task_id: int, page: int = 1, page_size: int = 100,
                 ip: str | None = None, port: int | None = None,
                 protocol: str | None = None,
                 call_id: str | None = None,
                 session_id: int | None = None,
                 number_from: int | None = None,
                 number_to: int | None = None,
                 time_from: float | None = None, time_to: float | None = None,
                 descending: bool = False,
                 db: Session = Depends(get_db)):
    page = max(1, page)
    page_size = min(500, max(1, page_size))

    stmt = select(PacketIndex).where(PacketIndex.task_id == task_id)
    if ip:
        stmt = stmt.where((PacketIndex.source_ip == ip) |
                          (PacketIndex.destination_ip == ip))
    if port:
        stmt = stmt.where((PacketIndex.source_port == port) |
                          (PacketIndex.destination_port == port))
    if protocol:
        stmt = stmt.where(PacketIndex.protocol == protocol.upper())
    if call_id:
        stmt = stmt.where(PacketIndex.call_id == call_id)
    if session_id is not None:
        stmt = stmt.where(PacketIndex.session_id == session_id)
    if number_from is not None:
        stmt = stmt.where(PacketIndex.packet_number >= number_from)
    if number_to is not None:
        stmt = stmt.where(PacketIndex.packet_number <= number_to)

    if time_from is not None:
        stmt = stmt.where(PacketIndex.timestamp >= time_from)
    if time_to is not None:
        stmt = stmt.where(PacketIndex.timestamp <= time_to)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(PacketIndex.packet_number.desc() if descending else PacketIndex.packet_number)
        .offset((page - 1) * page_size).limit(page_size)).all()

    return S.PacketList(
        total=total, page=page, page_size=page_size,
        items=[S.PacketOut.model_validate(r) for r in rows])


@router.get('/packets/{packet_id}', response_model=S.PacketDetail)
def get_packet(packet_id: int, db: Session = Depends(get_db)):
    row = db.get(PacketIndex, packet_id)
    if not row:
        raise HTTPException(404, '报文不存在')

    detail = S.PacketDetail.model_validate(row)
    task = db.get(AnalysisTask, row.task_id)
    if task and task.files:
        path = task.files[0].stored_path
        raw = capture.extract_raw_packet(path, row.packet_number)
        if raw:
            detail.raw_hex = binascii.hexlify(raw).decode()
        layers = _build_layers(path, row.packet_number)
        detail.layers = layers
    return detail


def _build_layers(path: str, number: int) -> list[dict]:
    """用 tshark -V 生成协议树（M12 第二栏）

    注意：只提取关键行，避免返回上万行文本。
    """
    import subprocess
    if not capture.TSHARK:
        return []
    try:
        r = subprocess.run(
            [capture.TSHARK, '-r', path, '-Y', 'frame.number==%d' % number, '-V'],
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            capture_output=True, text=True, errors='replace', timeout=60)
    except Exception:
        return []
    if r.returncode != 0:
        return []

    layers = []
    cur = None
    for line in r.stdout.splitlines():
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        text = line.strip()
        if indent == 0 and not text.startswith('['):
            # 新的协议层
            if cur:
                layers.append(cur)
            cur = {'name': text, 'fields': []}
        elif cur is not None and ':' in text:
            k, v = text.split(':', 1)
            cur['fields'].append({
                'name': k.strip(),
                'value': v.strip()[:300],
                'indent': indent,
            })
    if cur:
        layers.append(cur)
    # 限制规模
    for L in layers:
        L['fields'] = L['fields'][:80]
    return layers[:20]

# ---------------------------------------------------------------
# M08-04 媒体文件服务
# ---------------------------------------------------------------
def _safe_media_path(path: str | None) -> str | None:
    """校验媒体文件路径在允许目录内

    数据库里的路径理论上可信，但如果 DB 被篡改或迁移出错，
    不校验就可能读到任意文件。这里强制限定在 REBUILD_DIR 下。
    """
    if not path:
        return None
    try:
        real = os.path.realpath(path)
        base = os.path.realpath(str(settings.REBUILD_DIR))
        if os.path.commonpath([real, base]) != base:
            return None
        if not os.path.isfile(real):
            return None
        return real
    except (ValueError, OSError):
        return None

@router.get('/streams/{stream_id}/video')
def stream_video(stream_id: int, db: Session = Depends(get_db)):
    """返回重建后的 MP4（支持 Range，浏览器可拖动进度）"""
    from fastapi.responses import FileResponse
    from ..models.entities import MediaStream
    row = db.get(MediaStream, stream_id)
    if not row:
        raise HTTPException(404, '流不存在')
    real = _safe_media_path(row.rebuilt_path)
    if not real:
        raise HTTPException(404, row.rebuild_error or '该流未成功重建视频')
    return FileResponse(real, media_type='video/mp4',
                        filename='stream-%d.mp4' % stream_id)


@router.get('/streams/{stream_id}/poster')
def stream_poster(stream_id: int, db: Session = Depends(get_db)):
    """返回关键帧封面图"""
    from fastapi.responses import FileResponse
    from ..models.entities import MediaStream
    row = db.get(MediaStream, stream_id)
    if not row:
        raise HTTPException(404, '流不存在')
    # 封面路径约定：与 mp4 同目录同名 .jpg
    if row.rebuilt_path:
        real = _safe_media_path(os.path.splitext(row.rebuilt_path)[0] + '.jpg')
        if real:
            return FileResponse(real, media_type='image/jpeg')
    raise HTTPException(404, '该流没有封面图')


@router.get('/streams/{stream_id}/rebuild-info')
def rebuild_info(stream_id: int, db: Session = Depends(get_db)):
    """重建详情（供前端展示失败原因）"""
    from ..models.entities import MediaStream
    row = db.get(MediaStream, stream_id)
    if not row:
        raise HTTPException(404, '流不存在')
    rb = (row.extra or {}).get('rebuild') or {}
    return {
        'stream_id': row.id,
        'ok': bool(rb.get('ok')),
        'has_video': bool(row.rebuilt_path),
        'has_poster': bool(rb.get('poster')),
        'aligned': bool(rb.get('aligned')),
        'duration': rb.get('duration'),
        'ps_bytes': rb.get('ps_bytes'),
        'codec': row.codec,
        'width': row.width,
        'height': row.height,
        'fps': row.fps,
        'frame_count': row.frame_count,
        'error': rb.get('error') or row.rebuild_error,
    }
