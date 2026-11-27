#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务保留与清理

设计取舍：
  这个工具是一次性的分析工具，不是长期存档平台。
  用户的真实需求是「上传 → 看结果 → 关掉」，历史任务留着只会占盘。

策略（可配置）：
  KEEP_TASKS=0   不保留：分析完成立刻删原文件与重建产物，
                 只保留数据库里的统计结果（几十 KB，不占空间）
  KEEP_TASKS=N   保留最近 N 个任务的完整数据
  KEEP_DAYS=N    超过 N 天自动清理
  DISK_BUDGET_MB 总占用超限时，从最旧的开始删
  KEEP_UPLOADS=0 任务完成后只清原始抓包，保留重建视频与数据库结果

清理采用两阶段：文件先移入 DATA_DIR/quarantine/<task_id>，数据库提交成功
后才删除隔离目录。若在移动与删除之间进程崩溃，文件留在隔离区；下次启动
由 reconcile_quarantine() 按数据库状态决定删除（任务已清除/已标记清理）
还是恢复（数据库仍引用这些文件）。
"""
from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..core import analysis_control
from ..core.config import settings
from ..core.timeutil import utcnow
from ..models.entities import AnalysisTask, TaskComparison, TaskStatus


def _task_size(task: AnalysisTask) -> int:
    """估算一个任务占用的磁盘空间（字节）"""
    total = 0
    for cf in task.files:
        try:
            if cf.stored_path and os.path.isfile(cf.stored_path):
                total += os.path.getsize(cf.stored_path)
        except OSError:
            pass
    # 重建产物目录
    d = os.path.join(settings.REBUILD_DIR, str(task.id))
    if os.path.isdir(d):
        for name in os.listdir(d):
            p = os.path.join(d, name)
            try:
                if os.path.isfile(p):
                    total += os.path.getsize(p)
            except OSError:
                pass
    return total


def total_disk_usage() -> dict:
    """统计总占用"""
    uploads = 0
    if os.path.isdir(settings.UPLOAD_DIR):
        for name in os.listdir(settings.UPLOAD_DIR):
            p = os.path.join(settings.UPLOAD_DIR, name)
            try:
                if os.path.isfile(p):
                    uploads += os.path.getsize(p)
            except OSError:
                pass
            if name.startswith('.resume-') and os.path.isdir(p):
                for root, _dirs, files in os.walk(p):
                    for filename in files:
                        try:
                            uploads += os.path.getsize(os.path.join(root, filename))
                        except OSError:
                            pass

    rebuilt = 0
    if os.path.isdir(settings.REBUILD_DIR):
        for root, _dirs, files in os.walk(settings.REBUILD_DIR):
            for name in files:
                try:
                    rebuilt += os.path.getsize(os.path.join(root, name))
                except OSError:
                    pass

    db_size = 0
    db_path = getattr(settings, 'DATABASE_URL', '').replace('sqlite:///', '')
    for suffix in ('', '-wal', '-shm'):
        p = db_path + suffix
        if db_path and os.path.isfile(p):
            try:
                db_size += os.path.getsize(p)
            except OSError:
                pass

    return {
        'uploads_mb': round(uploads / 1024 / 1024, 1),
        'rebuilt_mb': round(rebuilt / 1024 / 1024, 1),
        'db_mb': round(db_size / 1024 / 1024, 1),
        'total_mb': round((uploads + rebuilt + db_size) / 1024 / 1024, 1),
    }


def purge_task_media(db: Session, task_id: int, drop_task: bool = False) -> dict:
    """清掉一个任务的媒体文件（保留数据库记录）

    drop_task=True 时连任务记录一起删（彻底删除）
    """
    if drop_task:
        return _purge_task_media(db, task_id, True)
    with analysis_control.task_lock:
        task = db.get(AnalysisTask, task_id, populate_existing=True)
        if not task or task.status == TaskStatus.ANALYZING or (
            task_id in analysis_control.active_tasks and task.status != TaskStatus.COMPLETED
        ):
            return {'removed': 0, 'freed_mb': 0}
        return _purge_task_media(db, task_id, False)


def quarantine_dir(task_id: int):
    """单个任务的隔离目录（移动先于提交，提交成功后再删除）"""
    return settings.DATA_DIR / 'quarantine' / str(task_id)


def _size_of(path) -> int:
    try:
        return os.path.getsize(path) if os.path.isfile(path) else 0
    except OSError:
        return 0


MANIFEST_NAME = 'quarantine.json'


def _write_manifest(qdir, task_id: int, manifest: dict, drop_task: bool,
                    upload_only: bool) -> None:
    """记录文件原始路径；提交前崩溃后靠它把文件恢复回去。"""
    data = {**manifest, 'task_id': task_id, 'drop_task': drop_task,
            'upload_only': upload_only}
    try:
        qdir.mkdir(parents=True, exist_ok=True)
        (qdir / MANIFEST_NAME).write_text(
            json.dumps(data, ensure_ascii=False), encoding='utf-8')
    except OSError:
        pass


def _read_manifest(qdir):
    try:
        data = json.loads((qdir / MANIFEST_NAME).read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _restore_quarantine(qdir) -> bool:
    """把隔离文件恢复到 manifest 记录的原始位置（尽力而为）。"""
    manifest = _read_manifest(qdir)
    restored = False
    for item in manifest.get('files') or []:
        src = None
        try:
            name = item.get('quarantined_as')
            if name:
                candidate = qdir / name
                if candidate.is_file():
                    src = candidate
            if src is None:
                # 老版本/清单损坏时按扩展名猜测唯一候选
                candidates = [p for p in qdir.iterdir() if p.is_file()
                              and p.name != MANIFEST_NAME]
                if len(candidates) == 1:
                    src = candidates[0]
            dest = item.get('path')
            if src and dest:
                dest_dir = os.path.dirname(dest)
                if dest_dir:
                    os.makedirs(dest_dir, exist_ok=True)
                if not os.path.exists(dest):
                    shutil.move(src, dest)
                    restored = True
        except (OSError, TypeError, AttributeError):
            continue
    rebuilt = qdir / 'rebuilt'
    if isinstance(manifest.get('rebuild'), str) and rebuilt.is_dir():
        dest = manifest['rebuild']
        try:
            if not os.path.exists(dest):
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.move(rebuilt, dest)
                restored = True
        except OSError:
            pass
    return restored


def reconcile_quarantine(db: Session | None = None) -> dict:
    """启动时协调隔离区与数据库状态。

    - 任务已不存在，或数据库已标记 media_purged/index_purged/upload_purged：
      直接删除隔离目录（提交已经生效）。
    - 任务仍在引用文件（提交前崩溃）：恢复文件到原路径，再删除隔离目录。
    - 无 manifest 的旧隔离目录：只在任务已消失/已清理时删除，避免误删可恢复文件。

    限制：恢复发生在「移动后、提交前」的崩溃场景；如果提交成功但还没来得及
    删除隔离区，则按已清理处理。单个文件被外部移动/改名且清单缺失时无法恢复。
    """
    root = settings.DATA_DIR / 'quarantine'
    result = {'deleted': 0, 'restored': 0, 'kept': 0}
    if not root.is_dir():
        return result

    own_session = db is None
    if own_session:
        from ..core.db import SessionLocal
        db = SessionLocal()
    try:
        for entry in list(root.iterdir()):
            if not entry.is_dir() or not entry.name.isdigit():
                continue
            task_id = int(entry.name)
            task = db.get(AnalysisTask, task_id)
            manifest = _read_manifest(entry)
            cfg = (task.configuration or {}) if task else {}
            purged = bool(cfg.get('media_purged') or cfg.get('index_purged')
                          or (cfg.get('upload_purged') and
                              not any(cf.stored_path and os.path.isfile(cf.stored_path)
                                      for cf in task.files)))
            if task is None or purged or manifest.get('drop_task'):
                shutil.rmtree(entry, ignore_errors=True)
                result['deleted'] += 1
                continue
            if manifest and _restore_quarantine(entry):
                result['restored'] += 1
                shutil.rmtree(entry, ignore_errors=True)
            else:
                # 无法恢复（例如数据库状态不明）：保留文件等待人工介入
                result['kept'] += 1
        return result
    finally:
        if own_session:
            db.close()


def _purge_task_media(db: Session, task_id: int, drop_task: bool,
                      upload_only: bool = False) -> dict:
    task = db.get(AnalysisTask, task_id)
    if not task:
        return {'removed': 0, 'freed_mb': 0}

    qdir = quarantine_dir(task_id)
    moved = 0
    freed = 0

    manifest = {'files': [], 'rebuild': False}

    def _quarantine(src):
        nonlocal moved, freed
        try:
            if not os.path.isfile(src):
                return
            qdir.mkdir(parents=True, exist_ok=True)
            dest = qdir / (uuid.uuid4().hex + os.path.splitext(src)[1])
            size = _size_of(src)
            shutil.move(src, dest)
            freed += size
            moved += 1
            return dest.name
        except OSError:
            return None

    # 阶段一：把文件移出原位置（不删除），记录元数据供恢复使用。
    for cf in task.files:
        if cf.stored_path and os.path.isfile(cf.stored_path):
            name = _quarantine(cf.stored_path)
            manifest['files'].append({'id': cf.id, 'path': cf.stored_path,
                                      'quarantined_as': name})

    d = os.path.join(settings.REBUILD_DIR, str(task_id))
    if not upload_only and os.path.isdir(d):
        # 整个重建目录移入隔离区，保留原始路径以便恢复
        rebuild_q = qdir / 'rebuilt'
        try:
            qdir.mkdir(parents=True, exist_ok=True)
            if os.path.exists(rebuild_q):
                shutil.rmtree(rebuild_q, ignore_errors=True)
            shutil.move(d, rebuild_q)
            manifest['rebuild'] = d
            for root, _dirs, files in os.walk(rebuild_q):
                for name in files:
                    freed += _size_of(os.path.join(root, name))
                    moved += 1
        except OSError:
            pass

    if moved:
        _write_manifest(qdir, task_id, manifest, drop_task, upload_only)

    # 阶段二：更新数据库并提交。提交失败时文件仍在隔离区，可由
    # reconcile_quarantine() 恢复；不会再次出现「DB 引用已删除文件」。
    if drop_task:
        db.delete(task)
    elif upload_only:
        task.configuration = {
            **(task.configuration or {}),
            'upload_purged': True,
            'upload_purged_at': utcnow().isoformat(),
        }
    else:
        # 媒体清了，报文索引也就没意义（无法再打开原始报文）
        from sqlalchemy import delete as _del
        from ..models.entities import PacketIndex
        db.execute(_del(PacketIndex).where(PacketIndex.task_id == task_id))

        task.configuration = {
            **(task.configuration or {}),
            'media_purged': True,
            'media_purged_at': utcnow().isoformat(),
            'index_purged': True,
        }

    try:
        db.commit()
    except Exception:
        db.rollback()
        # 提交失败：尝试把隔离文件恢复到原位置
        _restore_quarantine(qdir)
        raise

    # 阶段三：提交成功后才真正删除隔离目录
    if qdir.is_dir():
        shutil.rmtree(qdir, ignore_errors=True)
    return {
        'removed': moved + (0 if drop_task or upload_only else 1),
        'freed_mb': round(freed / 1024 / 1024, 2),
        'task_id': task_id,
        'dropped': drop_task,
    }


def cleanup_orphan_resumes(max_age_hours: float | None = None) -> dict:
    """清理 UPLOAD_DIR 下长时间未完成的 .resume-* 分片目录。

    按目录 mtime 判断陈旧程度；正常上传每次写分片都会更新 mtime。
    阈值可取 settings.RESUME_MAX_AGE_HOURS（若配置存在），默认 24 小时。
    """
    if max_age_hours is None:
        max_age_hours = getattr(settings, 'RESUME_MAX_AGE_HOURS', 24)
    cutoff = time.time() - max_age_hours * 3600
    removed = []
    upload_dir = settings.UPLOAD_DIR
    if upload_dir.is_dir():
        for entry in upload_dir.glob('.resume-*'):
            try:
                if entry.is_dir() and entry.stat().st_mtime < cutoff:
                    shutil.rmtree(entry, ignore_errors=True)
                    removed.append(entry.name)
            except OSError:
                pass
    return {'removed': removed, 'count': len(removed)}


def auto_purge(db: Session, *, keep_tasks: int | None = None) -> dict:
    """按策略自动清理

    在以下时机调用：
      - 服务启动时
      - 每次分析完成后
    """
    actions = []
    keep_tasks = settings.KEEP_TASKS if keep_tasks is None else keep_tasks

    # 启动/定时清理的第一件事：协调上次异常退出遗留的隔离文件，
    # 并清掉超时未完成的断点续传目录（两者都不依赖任务列表）。
    reconciliation = reconcile_quarantine(db)
    resumes = cleanup_orphan_resumes()

    tasks = db.scalars(
        select(AnalysisTask).order_by(AnalysisTask.created_at.desc())).all()

    # KEEP_UPLOADS=0：已完成任务只清原始抓包，保留重建视频与数据库结果。
    # 与 KEEP_TASKS/KEEP_DAYS 无关——即使任务仍在保留窗口内也执行。
    if not settings.KEEP_UPLOADS:
        for t in tasks:
            cfg = t.configuration or {}
            if t.status != TaskStatus.COMPLETED or cfg.get('upload_purged') \
                    or cfg.get('media_purged'):
                continue
            if not any(cf.stored_path and os.path.isfile(cf.stored_path)
                       for cf in t.files):
                continue
            r = _purge_task_media(db, t.id, drop_task=False, upload_only=True)
            if r['removed']:
                actions.append({'task_id': t.id, 'reason': '不保留原始上传',
                                'upload_purged': True, **r})

    if not tasks:
        return {'actions': actions, 'usage': total_disk_usage(),
                'reconciliation': reconciliation, 'orphan_resumes': resumes['count']}

    # ---- 1. 保留数量 ----
    if keep_tasks > 0:
        for t in tasks[keep_tasks:]:
            if t.files and not (t.configuration or {}).get('media_purged'):
                r = purge_task_media(db, t.id, drop_task=False)
                if r['removed']:
                    actions.append({
                        'task_id': t.id, 'reason': '超出保留数量',
                        **r
                    })
    elif keep_tasks == 0:
        # 不保留：所有已完成任务都清掉媒体
        for t in tasks:
            if t.status == TaskStatus.COMPLETED and \
                    not (t.configuration or {}).get('media_purged'):
                r = purge_task_media(db, t.id, drop_task=False)
                if r['removed']:
                    actions.append({
                        'task_id': t.id, 'reason': '不保留历史',
                        **r
                    })

    # ---- 2. 保留天数 ----
    if settings.KEEP_DAYS > 0:
        cutoff = utcnow() - timedelta(days=settings.KEEP_DAYS)
        expired = db.execute(delete(TaskComparison).where(TaskComparison.created_at < cutoff))
        if expired.rowcount:
            db.commit()
        for t in tasks:
            if t.created_at and t.created_at < cutoff:
                if t.files and not (t.configuration or {}).get('media_purged'):
                    r = purge_task_media(db, t.id, drop_task=False)
                    if r['removed']:
                        actions.append({
                            'task_id': t.id, 'reason': '超出保留天数',
                            **r
                        })

    # ---- 3. 磁盘预算 ----
    usage = total_disk_usage()
    if usage['total_mb'] > settings.DISK_BUDGET_MB:
        # 从最旧的开始删，直到低于 80% 预算
        target = settings.DISK_BUDGET_MB * 0.8
        for t in reversed(tasks):
            if usage['total_mb'] <= target:
                break
            if (t.configuration or {}).get('media_purged'):
                continue
            r = purge_task_media(db, t.id, drop_task=False)
            if r['removed']:
                actions.append({
                    'task_id': t.id, 'reason': '磁盘预算',
                    **r
                })
                usage = total_disk_usage()

    return {'actions': actions, 'usage': total_disk_usage(),
            'reconciliation': reconciliation, 'orphan_resumes': resumes['count']}


def delete_task_completely(db: Session, task_id: int) -> bool:
    """彻底删除一个任务（含数据库记录）"""
    task = db.get(AnalysisTask, task_id)
    if not task:
        return False
    purge_task_media(db, task_id, drop_task=True)
    return True

def vacuum_db(db: Session) -> dict:
    """SQLite 删数据后文件不会自动缩小，需要 VACUUM 回收空间

    只对 SQLite 有效。PostgreSQL 有 autovacuum，不需要。
    """
    from ..core.config import settings as _cfg
    url = _cfg.DATABASE_URL
    if not url.startswith('sqlite'):
        return {'vacuumed': False, 'reason': 'non-sqlite'}

    before = 0
    path = url.replace('sqlite:///', '')
    try:
        if os.path.isfile(path):
            before = os.path.getsize(path)
    except OSError:
        pass

    try:
        db.commit()
        db.execute(__import__('sqlalchemy').text('VACUUM'))
        db.commit()
    except Exception as e:
        return {'vacuumed': False, 'error': str(e)[:200]}

    after = 0
    try:
        if os.path.isfile(path):
            after = os.path.getsize(path)
    except OSError:
        pass

    return {
        'vacuumed': True,
        'before_mb': round(before / 1024 / 1024, 1),
        'after_mb': round(after / 1024 / 1024, 1),
        'freed_mb': round((before - after) / 1024 / 1024, 1),
    }
