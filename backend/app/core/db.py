#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据库会话管理"""
from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine, event
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


def init_db():
    """建表。生产环境应改用迁移脚本（migrations/）。"""
    Base.metadata.create_all(engine)


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
