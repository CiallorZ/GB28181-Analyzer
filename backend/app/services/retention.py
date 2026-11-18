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
"""
from __future__ import annotations

import os
import shutil
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import settings
from ..models.entities import AnalysisTask, TaskStatus


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
    task = db.get(AnalysisTask, task_id)
    if not task:
        return {'removed': 0, 'freed_mb': 0}

    freed = 0
    removed = 0

    # 1. 上传的原始抓包
    for cf in task.files:
        try:
            if cf.stored_path and os.path.isfile(cf.stored_path):
                freed += os.path.getsize(cf.stored_path)
                os.remove(cf.stored_path)
                removed += 1
        except OSError:
            pass

    # 2. 重建产物目录
    d = os.path.join(settings.REBUILD_DIR, str(task_id))
    if os.path.isdir(d):
        for name in os.listdir(d):
            p = os.path.join(d, name)
            try:
                if os.path.isfile(p):
                    freed += os.path.getsize(p)
                    removed += 1
            except OSError:
                pass
        try:
            shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass

    if drop_task:
        db.delete(task)
    else:
        # 媒体清了，报文索引也就没意义（无法再打开原始报文）
        # 一并删掉，能省下数据库里最大的一块空间
        from sqlalchemy import delete as _del
        from ..models.entities import PacketIndex
        rows = db.execute(
            _del(PacketIndex).where(PacketIndex.task_id == task_id)
        ).rowcount or 0

        task.configuration = {
            **(task.configuration or {}),
            'media_purged': True,
            'media_purged_at': datetime.utcnow().isoformat(),
            'index_purged': True,
        }
        removed += 1

    db.commit()
    return {
        'removed': removed,
        'freed_mb': round(freed / 1024 / 1024, 2),
        'task_id': task_id,
        'dropped': drop_task,
    }


def auto_purge(db: Session) -> dict:
    """按策略自动清理

    在以下时机调用：
      - 服务启动时
      - 每次分析完成后
    """
    actions = []

    tasks = db.scalars(
        select(AnalysisTask).order_by(AnalysisTask.created_at.desc())).all()
    if not tasks:
        return {'actions': [], 'usage': total_disk_usage()}

    # ---- 1. 保留数量 ----
    if settings.KEEP_TASKS > 0:
        for t in tasks[settings.KEEP_TASKS:]:
            if t.files and not (t.configuration or {}).get('media_purged'):
                r = purge_task_media(db, t.id, drop_task=False)
                if r['removed']:
                    actions.append({
                        'task_id': t.id, 'reason': '超出保留数量',
                        **r
                    })
    elif settings.KEEP_TASKS == 0:
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
        cutoff = datetime.utcnow() - timedelta(days=settings.KEEP_DAYS)
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

    return {'actions': actions, 'usage': total_disk_usage()}


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
