#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一的时间口径

`datetime.utcnow()` 在 Python 3.12+ 已弃用，且返回 naive datetime 容易被
误当成本地时间。项目数据库列是 SQLite `DateTime`（不带时区），因此这里
统一返回 **naive UTC**：语义是 UTC，但不带 tzinfo，避免读写比较时混用。
"""
from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    """当前 UTC 时间（naive，供数据库 DateTime 列直接存储）"""
    return datetime.now(timezone.utc).replace(tzinfo=None)
