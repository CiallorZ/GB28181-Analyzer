#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M05 / M06 会话查询与信令时序"""
from __future__ import annotations

from collections import defaultdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..models.entities import (
    BusinessSession, DiagnosticEvent, MediaMetric, MediaStream, SipMessage,
)
from ..schemas import task as S
from ..services.diagnosis import severity_order_clause

router = APIRouter(tags=['sessions'])


@router.get('/tasks/{task_id}/sessions', response_model=S.SessionList)
def list_sessions(task_id: int, page: int = 1, page_size: int = 20,
                  signal_status: str | None = None,
                  media_status: str | None = None,
                  device_id: str | None = None,
                  db: Session = Depends(get_db)):
    page = max(1, page)
    page_size = min(200, max(1, page_size))

    stmt = select(BusinessSession).where(BusinessSession.task_id == task_id)
    if signal_status:
        stmt = stmt.where(BusinessSession.signal_status == signal_status)
    if media_status:
        stmt = stmt.where(BusinessSession.media_status == media_status)
    if device_id:
        stmt = stmt.where(BusinessSession.device_id.contains(device_id))

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(BusinessSession.start_time)
        .offset((page - 1) * page_size).limit(page_size)).all()

    return S.SessionList(total=total, page=page, page_size=page_size,
                         items=[S.SessionBrief.model_validate(r) for r in rows])


@router.get('/sessions/{session_id}', response_model=S.SessionDetail)
def get_session(session_id: int, db: Session = Depends(get_db)):
    row = db.get(BusinessSession, session_id)
    if not row:
        raise HTTPException(404, '会话不存在')
    return S.SessionDetail.model_validate(row)


@router.get('/sessions/{session_id}/sip')
def session_sip(session_id: int, db: Session = Depends(get_db)):
    """会话关联的 SIP 消息（M06 时序图数据源）"""
    row = db.get(BusinessSession, session_id)
    if not row:
        raise HTTPException(404, '会话不存在')

    call_ids = row.call_ids or []
    if not call_ids:
        return {'items': [], 'note': '该会话未关联到 SIP 消息'}

    msgs = db.scalars(
        select(SipMessage)
        .where(SipMessage.task_id == row.task_id)
        .where(SipMessage.call_id.in_(call_ids))
        .order_by(SipMessage.timestamp)
    ).all()

    items = []
    for m in msgs:
        items.append({
            'id': m.id,
            'packet_id': m.packet_id,
            'timestamp': m.timestamp,
            'is_request': m.is_request,
            'method': m.method,
            'status_code': m.status_code,
            'call_id': m.call_id,
            'from_tag': m.from_tag,
            'to_tag': m.to_tag,
            'cseq': ('%s %s' % (m.cseq_number, m.cseq_method)
                     if m.cseq_number is not None else None),
            'source_ip': m.source_ip,
            'source_port': m.source_port,
            'destination_ip': m.destination_ip,
            'destination_port': m.destination_port,
            'gb_command': m.gb_command,
            'device_id': m.device_id,
            'sdp': m.sdp,
            'headers': m.headers,
            'body_preview': (m.body or '')[:400],
        })
    return {'items': items}


@router.get('/sessions/{session_id}/timeline')
def session_timeline(session_id: int, db: Session = Depends(get_db)):
    """会话时间线：SIP 消息 + 媒体关键事件（M06 要求）"""
    row = db.get(BusinessSession, session_id)
    if not row:
        raise HTTPException(404, '会话不存在')

    events = []

    # SIP 消息
    call_ids = row.call_ids or []
    if call_ids:
        msgs = db.scalars(
            select(SipMessage)
            .where(SipMessage.task_id == row.task_id)
            .where(SipMessage.call_id.in_(call_ids))
            .order_by(SipMessage.timestamp)).all()
        for m in msgs:
            label = m.method if m.is_request else str(m.status_code or '')
            events.append({
                'type': 'sip',
                'timestamp': m.timestamp,
                'label': label,
                'detail': ('%s → %s' % (m.source_ip, m.destination_ip)),
                'packet_id': m.packet_id,
                'session_message_id': m.id,
                'severity': 'normal',
            })

    # 媒体事件
    streams = db.scalars(
        select(MediaStream).where(MediaStream.session_id == session_id)).all()
    for st in streams:
        events.append({
            'type': 'media',
            'timestamp': st.start_time,
            'label': 'RTP 首包',
            'detail': 'SSRC=%08x %s' % (st.ssrc or 0, st.transport),
            'stream_id': st.id,
            'severity': 'normal',
        })
        events.append({
            'type': 'media',
            'timestamp': st.end_time,
            'label': 'RTP 末包',
            'detail': 'SSRC=%08x' % (st.ssrc or 0),
            'stream_id': st.id,
            'severity': 'normal',
        })
    # 诊断事件
    for d in db.scalars(
            select(DiagnosticEvent)
            .where(DiagnosticEvent.session_id == session_id)).all():
        events.append({
            'type': 'diagnostic',
            'timestamp': d.timestamp,
            'label': d.title,
            'detail': d.description[:160],
            'rule_id': d.rule_id,
            'severity': d.severity,
            'diagnostic_id': d.id,
            'related_packet_ids': d.related_packet_ids or [],
        })

    events = [e for e in events if e.get('timestamp') is not None]
    events.sort(key=lambda e: e['timestamp'])
    return {'items': events, 'session_id': session_id}


@router.get('/sessions/{session_id}/media', response_model=S.StreamList)
def session_media(session_id: int, db: Session = Depends(get_db)):
    rows = db.scalars(
        select(MediaStream).where(MediaStream.session_id == session_id)
        .order_by(MediaStream.start_time)).all()
    return S.StreamList(total=len(rows),
                        items=[S.StreamOut.model_validate(r) for r in rows])


@router.get('/sessions/{session_id}/metrics')
def session_metrics(session_id: int, db: Session = Depends(get_db)):
    """媒体指标时间序列（M07-04 图表数据）"""
    streams = db.scalars(
        select(MediaStream).where(MediaStream.session_id == session_id)
        .order_by(MediaStream.id)).all()
    return {'items': _metric_series(db, streams)}


@router.get('/tasks/{task_id}/media-metrics')
def task_metrics(task_id: int, stream_id: Annotated[list[int], Query(min_length=1, max_length=12)],
                 db: Session = Depends(get_db)):
    """批量读取总览趋势，包含尚未关联到信令的 RTP 流。"""
    streams = db.scalars(select(MediaStream).where(
        MediaStream.task_id == task_id, MediaStream.id.in_(stream_id),
    ).order_by(MediaStream.id)).all()
    return {'items': _metric_series(db, streams)}


def _metric_series(db: Session, streams):
    if not streams:
        return []
    metrics_by_stream = defaultdict(list)
    stmt = (
        select(MediaMetric.stream_id, MediaMetric.timestamp, MediaMetric.bitrate, MediaMetric.jitter)
        .where(MediaMetric.stream_id.in_([stream.id for stream in streams]))
        .order_by(MediaMetric.stream_id, MediaMetric.timestamp, MediaMetric.id)
    )
    for row in db.execute(stmt):
        metrics_by_stream[row.stream_id].append(row)

    out = []
    for st in streams:
        metrics = metrics_by_stream[st.id]
        out.append({
            'stream_id': st.id,
            'ssrc': '%08x' % (st.ssrc or 0) if st.ssrc else None,
            'transport': st.transport,
            'clock_rate': st.clock_rate,
            'bitrate_series': [
                {'t': m.timestamp, 'v': m.bitrate}
                for m in metrics if m.bitrate is not None
            ],
            'jitter_series': [
                {'t': m.timestamp, 'v': m.jitter}
                for m in metrics if m.jitter is not None
            ],
            'extra': st.extra or {},
        })
    return out


@router.get('/sessions/{session_id}/diagnostics',
            response_model=S.DiagnosticList)
def session_diagnostics(session_id: int, db: Session = Depends(get_db)):
    rows = db.scalars(
        select(DiagnosticEvent)
        .where(DiagnosticEvent.session_id == session_id)
        .order_by(severity_order_clause(DiagnosticEvent.severity),
                  DiagnosticEvent.timestamp)).all()
    return S.DiagnosticList(
        total=len(rows), page=1, page_size=len(rows) or 1,
        items=[S.DiagnosticOut.model_validate(r) for r in rows])

# ---------------------------------------------------------------
# 任务级媒体流（M07）
# ---------------------------------------------------------------
@router.get('/tasks/{task_id}/media', response_model=S.StreamList)
def task_media(task_id: int,
               only_rebuilt: bool = False,
               db: Session = Depends(get_db)):
    """按任务列出所有媒体流

    为什么需要这个接口：
      有些抓包只有媒体没有信令（例如纯 RTP 码流包），
      这些流无法关联到业务会话（session_id 为空）。
      如果前端只按会话取流，这类包就完全看不到结果。
      这里提供任务级视图，让「无信令但有媒体」的场景也能展示。
    """
    stmt = select(MediaStream).where(MediaStream.task_id == task_id)
    if only_rebuilt:
        stmt = stmt.where(MediaStream.rebuilt_path.isnot(None))
    rows = db.scalars(stmt.order_by(MediaStream.packet_count.desc(), MediaStream.id)).all()
    return S.StreamList(total=len(rows),
                        items=[S.StreamOut.model_validate(r) for r in rows])


@router.get('/tasks/{task_id}/media-stats')
def task_media_stats(task_id: int, db: Session = Depends(get_db)):
    """媒体流统计（用于概览展示）"""
    rows = db.scalars(
        select(MediaStream).where(MediaStream.task_id == task_id)).all()
    if not rows:
        return {
            'total': 0, 'rebuilt': 0, 'total_packets': 0,
            'total_bitrate': 0, 'avg_jitter': None,
            'resolutions': {}, 'codecs': {},
            'has_signal': False,
        }

    rebuilt = [r for r in rows if r.rebuilt_path]
    brs = [r.avg_bitrate for r in rows if r.avg_bitrate is not None]
    jts = [r.jitter_avg for r in rows if r.jitter_avg is not None]

    res = {}
    for r in rows:
        if r.width and r.height:
            k = '%dx%d' % (r.width, r.height)
            res[k] = res.get(k, 0) + 1

    codecs = {}
    for r in rows:
        if r.codec:
            codecs[r.codec] = codecs.get(r.codec, 0) + 1

    # 是否有信令（决定前端如何展示）
    from ..models.entities import SipMessage
    sip_count = db.scalar(
        select(func.count()).select_from(SipMessage)
        .where(SipMessage.task_id == task_id)) or 0

    return {
        'total': len(rows),
        'rebuilt': len(rebuilt),
        'total_packets': sum(r.packet_count for r in rows),
        'total_bitrate': round(sum(brs), 1) if brs else 0,
        'avg_jitter': round(sum(jts) / len(jts), 2) if jts else None,
        'resolutions': res,
        'codecs': codecs,
        'has_signal': sip_count > 0,
        'sip_count': sip_count,
    }
