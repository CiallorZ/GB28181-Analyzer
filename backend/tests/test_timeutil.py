#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UTC 时间口径：naive UTC，避免 utcnow 弃用与本地时区误读"""
from __future__ import annotations

from datetime import datetime, timezone

from app.core.timeutil import utcnow


def test_utcnow_is_naive_utc():
    t = utcnow()
    assert t.tzinfo is None
    delta = datetime.now(timezone.utc).replace(tzinfo=None) - t
    assert abs(delta.total_seconds()) < 5
