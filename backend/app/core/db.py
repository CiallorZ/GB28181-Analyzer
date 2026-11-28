#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据库会话管理"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from sqlalchemy import (Boolean, Float, Integer, String, Text, create_engine,
                        event, inspect, text)
from sqlalchemy.orm import sessionmaker

from ..models.entities import Base
from .config import settings

connect_args = {}
if settings.DATABASE_URL.startswith('sqlite'):
    # SQLite 允许多线程访问，配合 WAL 提升并发写入
    connect_args = {'check_same_thread': False, 'timeout': 30}

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
    echo=False,
)

if settings.DATABASE_URL.startswith('sqlite'):
    @event.listens_for(engine, 'connect')
    def _sqlite_pragma(dbapi_conn, _rec):
        cur = dbapi_conn.cursor()
        cur.execute('PRAGMA journal_mode=WAL')
        cur.execute('PRAGMA synchronous=NORMAL')
        cur.execute('PRAGMA foreign_keys=ON')
        cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False,
                            autocommit=False, expire_on_commit=False)


def ensure_columns() -> list[str]:
    """Add simple scalar columns declared on models but missing on disk.

    The project keeps its single-file deployment model. This is not a full
    migration tool: it never drops or rewrites data, and skips required
    columns and JSON/date types where a safe default cannot be inferred.
    """
    if not settings.DATABASE_URL.startswith('sqlite'):
        return []
    changed = []
    with engine.begin() as connection:
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())
        for table in Base.metadata.sorted_tables:
            if table.name not in tables:
                continue
            existing = {column['name'] for column in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                default = None
                nullable = column.nullable
                if column.default is not None and not column.default.is_callable:
                    default = column.default.arg
                if not isinstance(column.type, (Boolean, Integer, Float, String, Text)):
                    # Only fill simple scalar columns; never guess JSON or dates.
                    continue
                if not nullable and default is None:
                    # Never guess a value for a required field.
                    continue
                sql = 'ALTER TABLE "%s" ADD COLUMN "%s" %s' % (
                    table.name, column.name,
                    column.type.compile(dialect=engine.dialect),
                )
                if not nullable:
                    sql += ' NOT NULL'
                if default is not None:
                    literal = column.type.literal_processor(engine.dialect)(default)
                    sql += ' DEFAULT %s' % literal
                connection.execute(text(sql))
                changed.append('%s.%s' % (table.name, column.name))
    return changed


def init_db():
    """Create missing tables, then add safe additive columns."""
    Base.metadata.create_all(engine)
    ensure_columns()


def backup_sqlite(path: Path, backup_dir: Path, marker: Path,
                  version: str, keep: int = 5) -> Path | None:
    """在应用版本变化前，用 SQLite 在线备份 API 复制现有数据库。"""
    path = Path(path)
    backup_dir = Path(backup_dir)
    marker = Path(marker)
    if not path.is_file():
        marker.write_text(version, encoding='utf-8')
        return None
    if marker.is_file() and marker.read_text(encoding='utf-8').strip() == version:
        return None

    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    safe_version = ''.join(ch for ch in version if ch.isalnum() or ch in '.-_')
    target = backup_dir / f'analyzer-{safe_version}-{stamp}.db'
    with sqlite3.connect(path) as source, sqlite3.connect(target) as destination:
        source.backup(destination)
    marker.write_text(version, encoding='utf-8')
    for old in sorted(backup_dir.glob('analyzer-*.db'), reverse=True)[keep:]:
        try:
            old.unlink()
        except OSError:
            pass
    return target


def backup_before_upgrade() -> Path | None:
    if not settings.DATABASE_URL.startswith('sqlite:///'):
        return None
    from .. import __version__
    from .config import settings as current
    db_path = Path(current.DATABASE_URL.removeprefix('sqlite:///'))
    return backup_sqlite(
        db_path, current.BACKUP_DIR, current.DATA_DIR / 'db-version.txt',
        __version__,
    )


@contextmanager
def session_scope():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db():
    """FastAPI 依赖"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
