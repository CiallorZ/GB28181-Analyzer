"""Read-only analysis of persisted observations; only the snapshot itself is written."""
import json
from html import escape
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, defer

from ..core.db import get_db
from ..models.entities import (AnalysisTask, BusinessSession, CaptureFile, DiagnosticEvent,
                               MediaStream, PacketIndex, TaskComparison, TaskStatus)
from ..schemas.comparison import ComparisonCreate
from ..services.comparison import SESSION_FIELDS, STREAM_FIELDS, snapshot

router = APIRouter(prefix='/comparisons', tags=['双抓包对比'])


def begin_snapshot(db, writing=False):
    # sqlite3 legacy transaction mode does not start a transaction for SELECT.
    conn = db.connection()
    if conn.dialect.name == 'sqlite' and not conn.connection.driver_connection.in_transaction:
        conn.exec_driver_sql('BEGIN IMMEDIATE' if writing else 'BEGIN')


def fingerprint(db, task):
    def count(entity):
        return db.scalar(select(func.count()).select_from(entity).where(entity.task_id == task.id))
    files = db.execute(select(CaptureFile.filename, CaptureFile.checksum)
                       .where(CaptureFile.task_id == task.id).order_by(CaptureFile.id))
    return dict(task_id=task.id, completed_at=task.completed_at.isoformat() if task.completed_at else None,
                files=[dict(f._mapping) for f in files], sessions=count(BusinessSession), streams=count(MediaStream))


def records(db, entity, fields, task):
    cols = [getattr(entity, k) for k in fields]
    return [dict(r) for r in db.execute(select(*cols).where(entity.task_id == task.id)
                                        .order_by(entity.id)).mappings()]


def input_rows(db, task):
    sessions = records(db, BusinessSession, ['id', 'device_id', 'channel_id', 'session_type', 'call_ids',
                                             *SESSION_FIELDS], task)
    streams = records(db, MediaStream, ['id', 'session_id', 'rebuilt_path', 'rebuild_error',
                                        *(f for f in STREAM_FIELDS if f not in ('present', 'rebuild'))], task)
    for row in streams:
        path, error = row.pop('rebuilt_path'), row.pop('rebuild_error')
        row.update(present=True, rebuild='success' if path else 'failed' if error else None)
    events = records(db, DiagnosticEvent, ['id', 'session_id', 'stream_id', 'severity', 'rule_id'], task)
    return sessions, streams, events


def brief(row):
    return dict(id=row.id, created_at=row.created_at.isoformat() + 'Z', task_a_id=row.task_a_id,
                task_b_id=row.task_b_id, label_a=row.label_a, label_b=row.label_b, summary=row.summary)


def detail(db, row):
    stale = False
    links = {}
    for side, tid in [('a', row.task_a_id), ('b', row.task_b_id)]:
        task = db.get(AnalysisTask, tid)
        stale |= task is None or task.status != TaskStatus.COMPLETED or fingerprint(db, task) != row.fingerprint[side]
        displayed = {pair['session_' + side] for layer in ('sessions', 'streams') for pair in row.result[layer]}
        session_ids = db.scalars(select(BusinessSession.id).where(
            BusinessSession.task_id == tid, BusinessSession.id.in_(displayed)).order_by(BusinessSession.id)).all()
        packet = db.scalar(select(PacketIndex.id).where(PacketIndex.task_id == tid).limit(1))
        links[side] = dict(sessions=session_ids, packets=packet is not None)
    return dict(**brief(row), fingerprint=row.fingerprint, result=row.result, stale=stale, links=links)


def lookup(db, comparison_id):
    row = db.get(TaskComparison, comparison_id)
    if row is None:
        raise HTTPException(404, '对比快照不存在')
    return row


@router.post('', status_code=201)
def create(body: ComparisonCreate, db: Session = Depends(get_db)):
    if body.task_a_id == body.task_b_id:
        raise HTTPException(400, '请选择两个不同的任务')
    begin_snapshot(db, writing=True)
    tasks = [db.get(AnalysisTask, tid) for tid in (body.task_a_id, body.task_b_id)]
    if not all(tasks):
        raise HTTPException(404, '任务不存在')
    if any(t.status != TaskStatus.COMPLETED for t in tasks):
        raise HTTPException(409, '仅支持已完成任务')
    prints = {side: fingerprint(db, t) for side, t in zip('ab', tasks)}
    result, summary = snapshot(*zip(*(input_rows(db, t) for t in tasks)))
    row = TaskComparison(**body.model_dump(), fingerprint=prints, result=result, summary=summary)
    db.add(row)
    db.flush()
    response = JSONResponse(detail(db, row), status_code=201)
    db.commit()
    return response


@router.get('')
def listing(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    stmt = select(TaskComparison).options(defer(TaskComparison.result), defer(TaskComparison.fingerprint))
    rows = db.scalars(stmt.order_by(TaskComparison.created_at.desc(), TaskComparison.id.desc()).limit(limit).offset(offset))
    return {'total': db.scalar(select(func.count(TaskComparison.id))), 'items': [brief(r) for r in rows]}


@router.get('/{comparison_id}')
def get(comparison_id: int, db: Session = Depends(get_db)):
    begin_snapshot(db)
    return JSONResponse(detail(db, lookup(db, comparison_id)))


@router.delete('/{comparison_id}', status_code=204)
def remove(comparison_id: int, db: Session = Depends(get_db)):
    db.delete(lookup(db, comparison_id))
    db.commit()
    return Response(status_code=204)


def cell(v):
    if v is None:
        return '未知'
    safe = escape(str(v)).replace('\\', '\\\\')
    for char in ('[', ']', '*', '_', '`'):
        safe = safe.replace(char, '\\' + char)
    return safe.replace('|', '&#124;').replace('\n', ' ').replace('\r', ' ')


def markdown(data):
    result = data['result']
    lines = ['# 双抓包对比报告', '', '## 对比范围',
             f"生成时间 {data['created_at']}　快照过期 {'是' if data['stale'] else '否'}"]
    for side in 'ab':
        fp = data['fingerprint'][side]
        lines.append(f"- {side.upper()} · {cell(data['label_'+side])} · 指纹 {cell(json.dumps(fp, ensure_ascii=False))}")
    summary = data['summary']
    lines.extend(['', '## 对齐方法与置信度', result['methods'], '', '## 结论摘要',
                  f"已对齐 {summary['aligned_sessions']} 个会话、{summary['aligned_streams']} 条媒体流。"
                  f"结构或精确值差异 {summary['structural']} 项，超出对比容差 {summary['beyond_tolerance']} 项，"
                  f"无法比较 {summary['unknown']} 项。单列未对齐记录 {summary['unaligned']} 条。"])
    unknowns = 0
    sdp = {k for k in SESSION_FIELDS if k.startswith(('negotiated_', 'sdp_'))} | {'subject_ssrc'}
    encoding = {'codec', 'width', 'height', 'fps', 'keyframe_count', 'has_audio', 'rebuild'}
    for layer, name, columns in (
        ('sessions', '信令与会话', set(SESSION_FIELDS) - sdp), ('sessions', 'SDP 协商', sdp),
        ('streams', '媒体传输', set(STREAM_FIELDS) - encoding), ('streams', '编码与重建', encoding),
        ('diagnostics', '诊断规则', {'count', 'severity'}),
    ):
        lines.extend(['', '## '+name, '| 对象 | 对齐 | 字段 | A | B | 判定 |', '|---|---|---|---|---|---|'])
        for r in result[layer]:
            obj = r['rule_id'] if 'rule_id' in r else f"#{r['a']} / #{r['b']}"
            method = r.get('method', 'rule_id') + ('（低置信度）' if r.get('confidence') == 'low' else '')
            if 'evidence' in r:
                method += ' ' + cell(json.dumps(r['evidence'], ensure_ascii=False))
            for field, (a, b, status) in r['fields'].items():
                if field not in columns:
                    continue
                unknowns += status == 'unknown'
                note = '（超出对比容差）' if status == 'different' and field in result['tolerances'] else ''
                lines.append(f'| {cell(obj)} | {method} | {field} | {cell(a)} | {cell(b)} | {status}{note} |')
    lines.extend(['', '## 未对齐项（不计入差异汇总）'])
    lines.extend(f"- {r['layer']} · {r['side'].upper()} #{r['id']} · {r['method']} · {r['status']} · "
                 f"{cell(json.dumps(r['observed'], ensure_ascii=False))}" for r in result['unmatched'])
    lines.extend(['', '## 无法比较项', f'表内 {unknowns} 项标记 unknown。', '',
                  f"明细截断：{'是' if result['truncated'] else '否'}；完整数量 {result['totals']}；未对齐数量 {result['unmatched_totals']}",
                  '', '## 局限声明', *result['limitations']])
    return '\n'.join(lines)


@router.get('/{comparison_id}/report')
def report(comparison_id: int, format: Literal['md', 'json'] = 'md', db: Session = Depends(get_db)):
    begin_snapshot(db)
    data = detail(db, lookup(db, comparison_id))
    content = markdown(data) if format == 'md' else json.dumps(data, ensure_ascii=False)
    return Response(content, media_type='text/markdown' if format == 'md' else 'application/json',
                    headers={'Content-Disposition': f'attachment; filename="comparison-{comparison_id}.{format}"'})
