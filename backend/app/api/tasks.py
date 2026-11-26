#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M01 任务管理与文件上传"""
from __future__ import annotations

from pathlib import Path
import hashlib
import json
import os
import re
import threading
import uuid

from fastapi import (APIRouter, BackgroundTasks, Depends, File, HTTPException,
                     Response, UploadFile)
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from ..core import analysis_control
from ..core.config import settings
from ..core.db import SessionLocal, get_db
from ..core.security import looks_like_capture
from ..models.entities import (
    AnalysisTask, CaptureFile, DiagnosticEvent, TaskStatus, BusinessSession,
    MediaStream,
)
from ..parsers import capture
from ..services import analyzer, report
from ..services.diagnosis import severity_order_clause
from ..schemas import task as S

router = APIRouter(prefix='/tasks', tags=['tasks'])

_running = analysis_control.active_tasks
_run_lock = analysis_control.task_lock


# ---------------------------------------------------------------
# 上传
# ---------------------------------------------------------------
@router.post('/upload', response_model=S.UploadResult, status_code=201)
async def upload_file(file: UploadFile = File(...),
                      db: Session = Depends(get_db)):
    """上传抓包文件并创建分析任务"""
    name = os.path.basename(file.filename or 'upload.pcap')
    ext = os.path.splitext(name)[1].lower()
    if ext not in settings.ALLOWED_EXT:
        raise HTTPException(400, '只支持 %s 格式' % '、'.join(settings.ALLOWED_EXT))

    limit = settings.MAX_UPLOAD_MB * 1024 * 1024
    uid = uuid.uuid4().hex[:16]
    safe = re.sub(r'[^\w.\-]', '_', name)[:80] or 'upload.pcap'
    dest = settings.UPLOAD_DIR / ('%s_%s' % (uid, safe))

    # 流式落盘，不整包进内存
    size = 0
    sha = hashlib.sha256()
    try:
        with open(dest, 'wb') as out:
            first = True
            while True:
                chunk = await file.read(1 << 20)
                if not chunk:
                    break
                if first:
                    first = False
                    # 文件头不是 pcap/pcapng 魔数就别往下写，避免落盘垃圾数据
                    if not looks_like_capture(chunk):
                        raise HTTPException(
                            400, '文件内容不是有效的 pcap/pcapng 抓包文件'
                                 '（文件头魔数不匹配）')
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, '文件超过 %d MB 上限'
                                        % settings.MAX_UPLOAD_MB)
                sha.update(chunk)
                out.write(chunk)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(500, '写入文件失败：%s' % e)

    except BaseException:
        # Cancellation also owns the partially written capture.
        dest.unlink(missing_ok=True)
        raise

    if size == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, '上传的文件为空')

    return register_capture(db, name, dest, size, sha.hexdigest())


def register_capture(db, name, dest, size, checksum):
    ext = Path(name).suffix.lower()
    try:
        task = AnalysisTask(
            name=name,
            status=TaskStatus.PENDING,
            configuration={},
        )
        db.add(task)
        db.flush()

        cf = CaptureFile(
            task_id=task.id, filename=name,
            stored_path=str(dest), file_size=size,
            file_format=ext.lstrip('.'), checksum=checksum,
        )
        db.add(cf)
        db.commit()
    except Exception:
        db.rollback()
        dest.unlink(missing_ok=True)
        raise
    db.refresh(task)

    return S.UploadResult(task_id=task.id, file_id=cf.id,
                          filename=name, size=size)


# ---------------------------------------------------------------
# 任务列表 / 详情
# ---------------------------------------------------------------
@router.get('', response_model=S.TaskList)
def list_tasks(page: int = 1, page_size: int = 20,
               status: str | None = None,
               keyword: str | None = None,
               db: Session = Depends(get_db)):
    page = max(1, page)
    page_size = min(100, max(1, page_size))

    stmt = select(AnalysisTask)
    if status:
        stmt = stmt.where(AnalysisTask.status == status)
    if keyword:
        stmt = stmt.where(AnalysisTask.name.contains(keyword))

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.options(selectinload(AnalysisTask.files))
        .order_by(AnalysisTask.created_at.desc(), AnalysisTask.id.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ).all()

    return S.TaskList(
        total=total, page=page, page_size=page_size,
        items=[_task_brief(db, t) for t in rows],
    )


@router.get('/active-count')
def active_count(db: Session = Depends(get_db)):
    """Number of tasks that still own a worker or are queued for analysis."""
    count = db.scalar(
        select(func.count())
        .select_from(AnalysisTask)
        .where(
            (AnalysisTask.status == TaskStatus.ANALYZING) |
            ((AnalysisTask.status == TaskStatus.PENDING) & (AnalysisTask.stage == '排队中'))
        )
    )
    return {'count': int(count or 0)}


@router.get('/{task_id}', response_model=S.TaskDetail)
def get_task(task_id: int, db: Session = Depends(get_db)):
    task = db.get(AnalysisTask, task_id)
    if not task:
        raise HTTPException(404, '任务不存在')
    return _task_detail(db, task)


def _task_brief(db: Session, t: AnalysisTask) -> S.TaskBrief:
    cf = t.files[0] if t.files else None
    s = t.summary or {}
    return S.TaskBrief(
        id=t.id, name=t.name, status=t.status, progress=t.progress,
        stage=t.stage, created_at=t.created_at,
        file_size=cf.file_size if cf else None,
        packet_count=cf.packet_count if cf else None,
        duration=cf.duration if cf else None,
        session_count=s.get('session_count'),
        diagnostic_count=(sum(s['diagnostics'].values())
                          if isinstance(s.get('diagnostics'), dict) else None),
        error_message=t.error_message,
    )


def _task_detail(db: Session, t: AnalysisTask) -> S.TaskDetail:
    cf = t.files[0] if t.files else None
    return S.TaskDetail(
        id=t.id, name=t.name, status=t.status, progress=t.progress,
        stage=t.stage, created_at=t.created_at,
        started_at=t.started_at, completed_at=t.completed_at,
        error_message=t.error_message,
        configuration=t.configuration or {},
        summary=t.summary or {},
        file=S.FileInfo(
            id=cf.id, filename=cf.filename, file_size=cf.file_size,
            file_format=cf.file_format, checksum=cf.checksum,
            packet_count=cf.packet_count,
            capture_start=cf.capture_start, capture_end=cf.capture_end,
            duration=cf.duration, link_type=cf.link_type,
            ip_count=cf.ip_count, tcp_count=cf.tcp_count,
            udp_count=cf.udp_count, warnings=cf.warnings or [],
        ) if cf else None,
    )


# ---------------------------------------------------------------
# 启动 / 取消 / 删除
# ---------------------------------------------------------------
@router.get('/{task_id}/report')
def task_report(task_id: int, format: str = 'md',
                db: Session = Depends(get_db)):
    """导出分析报告：format=md（默认）或 json

    报告只读已入库的结果，不重新分析 —— 同一个任务在页面与报告里
    必须给出同一组数字。
    """
    task = db.get(AnalysisTask, task_id)
    if not task:
        raise HTTPException(404, '任务不存在')
    if task.status != TaskStatus.COMPLETED:
        raise HTTPException(409, '任务尚未完成分析，暂不能导出报告')

    file = task.files[0] if task.files else None
    sessions = db.scalars(
        select(BusinessSession)
        .where(BusinessSession.task_id == task_id)
        .order_by(BusinessSession.start_time)).all()
    streams = db.scalars(
        select(MediaStream)
        .where(MediaStream.task_id == task_id)
        .order_by(MediaStream.id)).all()
    diagnostics = db.scalars(
        select(DiagnosticEvent)
        .where(DiagnosticEvent.task_id == task_id)
        .order_by(severity_order_clause(DiagnosticEvent.severity),
                  DiagnosticEvent.id)).all()

    if format == 'json':
        payload = report.build_payload(task, file, sessions, streams,
                                       diagnostics)
        return Response(
            json.dumps(payload, ensure_ascii=False, indent=2),
            media_type='application/json; charset=utf-8',
            headers={'Content-Disposition':
                     'attachment; filename="gb28181-report-%d.json"' % task_id})

    if format == 'csv':
        import csv
        import io
        out = io.StringIO(newline='')
        writer = csv.writer(out)
        writer.writerow(['规则', '严重度', '诊断', '建议'])
        for item in diagnostics:
            cells = [item.rule_id, item.severity.value, item.title, '；'.join(map(str, item.recommendations or []))]
            writer.writerow([("'" + str(v)) if str(v).lstrip().startswith(('=', '+', '-', '@')) else v for v in cells])
        return Response(out.getvalue().encode('utf-8-sig'), media_type='text/csv',
                        headers={'Content-Disposition': f'attachment; filename="diagnostics-{task_id}.csv"'})
    if format == 'html':
        from html import escape
        def table(headers, rows):
            head = ''.join('<th>' + escape(h) + '</th>' for h in headers)
            body = ''.join('<tr>' + ''.join('<td>' + escape(str(v if v is not None else '—')) +
                           '</td>' for v in row) + '</tr>' for row in rows)
            return '<table><thead><tr>' + head + '</tr></thead><tbody>' + body + '</tbody></table>'
        html = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>抓包分析报告</title>'
                '<style>body{max-width:1000px;margin:3em auto;padding:1em;font:16px system-ui;color:#203044}'
                'h1{border-bottom:3px solid #d70c1a}table{border-collapse:collapse;width:100%}'
                'td,th{padding:8px;text-align:left;border-bottom:1px solid #ddd}</style>'
                '<h1>GB28181 抓包分析报告</h1><p>' + escape(file.filename if file else task.name) +
                '</p><h2>会话</h2>' + table(['会话', '设备', '类型', '信令', '媒体'],
                    ((v.id, v.device_id, v.session_type, v.signal_status.value, v.media_status.value) for v in sessions)) +
                '<h2>媒体流</h2>' + table(['SSRC', '传输', '源端', '接收端', 'RTP 包数', '编码'],
                    ((v.ssrc, v.transport, v.source_ip, v.destination_ip, v.packet_count, v.codec) for v in streams)) +
                '<h2>诊断与处置</h2>' + table(['规则', '严重度', '结论', '依据', '建议'],
                    ((v.rule_id, v.severity.value, v.title, v.description, '；'.join(map(str, v.recommendations or [])))
                     for v in diagnostics)) + '</html>')
        return Response(html, media_type='text/html',
                        headers={'Content-Disposition': f'attachment; filename="report-{task_id}.html"'})
    if format != 'md':
        raise HTTPException(400, '不支持的格式，可选 md / json')

    md = report.build_markdown(task, file, sessions, streams, diagnostics)
    return Response(
        md, media_type='text/markdown; charset=utf-8',
        headers={'Content-Disposition':
                 'attachment; filename="gb28181-report-%d.md"' % task_id})


@router.post('/{task_id}/analyze', response_model=S.TaskBrief)
def start_analyze(task_id: int, bg: BackgroundTasks,
                  db: Session = Depends(get_db)):
    task = db.get(AnalysisTask, task_id)
    if not task:
        raise HTTPException(404, '任务不存在')

    # 源文件不在了就直接拒绝。若放行，worker 会先把上一次的结果全部删掉，
    # 再因为文件缺失失败 —— 用户等于白丢一份分析结果。
    if not task.files:
        raise HTTPException(409, '任务没有关联抓包文件')
    if task.status == TaskStatus.COMPLETED and not (
        capture.TSHARK and os.path.isfile(capture.TSHARK)
    ):
        raise HTTPException(409, '未找到 tshark，已保留现有分析结果。请安装 Wireshark 后重启工作台。')

    with _run_lock:
        # 只要本进程还有该任务的 worker 在跑，就一律拒绝 ——
        # 不能只看 DB 状态：worker 启动后有一小段时间状态仍是 PENDING，
        # 此时再点一次会起第二个线程，两个线程同时删同一批结果。
        if task_id in _running:
            raise HTTPException(409, '任务正在分析中')

        missing = [cf.filename for cf in task.files
                   if not cf.stored_path or not os.path.isfile(cf.stored_path)]
        if missing:
            raise HTTPException(
                409, '源文件已不存在（可能被保留策略清理）：%s，请重新上传'
                     % '、'.join(missing))

        running = sum(1 for v in _running.values() if v)
        if running >= settings.MAX_CONCURRENT_TASKS:
            raise HTTPException(429, '同时分析的任务过多（上限 %d）'
                                % settings.MAX_CONCURRENT_TASKS)
        # 占位必须与"检查"在同一把锁内完成，否则两个并发请求都能通过检查
        _running[task_id] = analysis_control.Control()

        try:
            task.status = TaskStatus.PENDING
            task.progress = 0
            task.stage = '排队中'
            task.error_message = None
            db.commit()
            threading.Thread(target=_worker, args=(task_id,), daemon=True).start()
        except BaseException:
            _running.pop(task_id, None)
            raise

    db.refresh(task)
    return _task_brief(db, task)


def _worker(task_id: int):
    """后台分析线程 —— 不阻塞 HTTP 请求"""
    db = SessionLocal()
    token = analysis_control.current.set(_running[task_id])
    try:
        analyzer.run_analysis(db, task_id)
    except Exception:
        pass          # 状态已由 run_analysis 写入
    finally:
        analysis_control.current.reset(token)
        db.close()
        with _run_lock:
            _running.pop(task_id, None)


@router.post('/{task_id}/cancel', response_model=S.TaskBrief)
def cancel_task(task_id: int, db: Session = Depends(get_db)):
    """取消指定任务并结束其正在运行的解析与重建进程。"""
    with _run_lock:
        task = db.get(AnalysisTask, task_id)
        if not task:
            raise HTTPException(404, '任务不存在')
        changed = db.execute(update(AnalysisTask).where(
            AnalysisTask.id == task_id,
            AnalysisTask.status.notin_((TaskStatus.COMPLETED, TaskStatus.FAILED)),
        ).values(status=TaskStatus.CANCELLED, stage='已取消')).rowcount
        if not changed:
            raise HTTPException(409, '任务已结束，无法取消')
        db.commit()
        control = _running.get(task_id)
        if control:
            control.cancel()
    db.refresh(task)
    return _task_brief(db, task)


@router.delete('/{task_id}', status_code=204)
def delete_task(task_id: int, db: Session = Depends(get_db)):
    from ..services import retention

    task = db.get(AnalysisTask, task_id)
    if not task:
        raise HTTPException(404, '任务不存在')
    # worker 正在跑时删除，会让它写回一堆已不存在的行（外键报错/脏状态）
    with _run_lock:
        if task_id in _running:
            raise HTTPException(409, '任务正在分析中，请先取消再删除')
        # 统一走保留策略的彻底删除：上传的抓包、rebuilt/<id> 预览与
        # 数据库记录一起清理。只删数据库会让预览视频永久留在磁盘上。
        if not retention.delete_task_completely(db, task_id):
            raise HTTPException(404, '任务不存在')
    return None


# ---------------------------------------------------------------
# 概览（M10）
# ---------------------------------------------------------------
@router.get('/{task_id}/overview', response_model=S.Overview)
def get_overview(task_id: int, db: Session = Depends(get_db)):
    task = db.get(AnalysisTask, task_id)
    if not task:
        raise HTTPException(404, '任务不存在')

    from ..models.entities import SipMessage

    message_fields = (SipMessage.is_request, SipMessage.method, SipMessage.status_code)
    message_counts = db.execute(
        select(*message_fields, func.count())
        .where(SipMessage.task_id == task_id).group_by(*message_fields)
    )
    method_dist = {}
    code_dist = {}
    for is_request, method, status_code, count in message_counts:
        if method and is_request:
            method_dist[method] = method_dist.get(method, 0) + count
        elif status_code:
            code = str(status_code)
            code_dist[code] = code_dist.get(code, 0) + count

    sev_dist = dict(db.execute(
        select(DiagnosticEvent.severity, func.count())
        .where(DiagnosticEvent.task_id == task_id).group_by(DiagnosticEvent.severity)
    ).tuples().all())
    sig_dist = {}
    med_dist = {}
    type_dist = {}
    session_fields = (BusinessSession.signal_status, BusinessSession.media_status,
                      BusinessSession.session_type)
    for signal, media, session_type, count in db.execute(
        select(*session_fields, func.count())
        .where(BusinessSession.task_id == task_id).group_by(*session_fields)
    ):
        sig_dist[signal] = sig_dist.get(signal, 0) + count
        med_dist[media] = med_dist.get(media, 0) + count
        type_dist[session_type] = type_dist.get(session_type, 0) + count

    return S.Overview(
        task_id=task.id,
        summary=task.summary or {},
        method_distribution=method_dist,
        code_distribution=code_dist,
        severity_distribution=sev_dist,
        signal_distribution=sig_dist,
        media_distribution=med_dist,
        session_types=type_dist,
    )


# ---------------------------------------------------------------
# 存储管理
# ---------------------------------------------------------------
@router.get('/storage/usage')
def storage_usage(db: Session = Depends(get_db)):
    """磁盘占用与保留策略"""
    from ..services import retention
    return {
        'usage': retention.total_disk_usage(),
        'policy': {
            'keep_tasks': settings.KEEP_TASKS,
            'keep_days': settings.KEEP_DAYS,
            'disk_budget_mb': settings.DISK_BUDGET_MB,
            'keep_uploads': settings.KEEP_UPLOADS,
        },
    }


@router.post('/storage/purge')
def storage_purge(keep: int | None = None, db: Session = Depends(get_db)):
    """手动清理：只保留最近 N 个任务的媒体文件

    keep 为空时按当前策略执行
    """
    from ..services import retention
    return retention.auto_purge(db, keep_tasks=None if keep is None else max(0, keep))


@router.delete('/storage/all')
def storage_purge_all(db: Session = Depends(get_db)):
    """清空所有任务的媒体文件（保留数据库统计）"""
    from ..services import retention
    from sqlalchemy import select as _select
    tasks = db.scalars(_select(AnalysisTask)).all()
    total = {'removed': 0, 'freed_mb': 0, 'tasks': 0}
    for t in tasks:
        r = retention.purge_task_media(db, t.id, drop_task=False)
        if r['removed']:
            total['removed'] += r['removed']
            total['freed_mb'] = round(total['freed_mb'] + r['freed_mb'], 2)
            total['tasks'] += 1
    # SQLite 需要 VACUUM 才能真正回收磁盘
    total['vacuum'] = retention.vacuum_db(db)
    total['usage'] = retention.total_disk_usage()
    return total
