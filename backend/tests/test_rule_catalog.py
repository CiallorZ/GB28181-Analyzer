#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""规则清单必须诚实反映实现状态

历史上 `/api/rules` 把 21 条规则全部列出来，但只有 12 条有检测逻辑。
用户看到"规则清单"会默认这些规则都在跑，从而把"没报错"误读成"没问题"。
"""
from __future__ import annotations

import re
from pathlib import Path

from app.services import diagnosis


def test_catalog_marks_every_rule():
    catalog = diagnosis.rule_catalog()
    assert len(catalog) == len(diagnosis.RULES) == 21
    assert {r['id'] for r in catalog} == set(diagnosis.RULES)
    assert all(isinstance(r['implemented'], bool) for r in catalog)
    assert sum(1 for r in catalog if r['implemented']) == len(
        diagnosis.RULE_IMPLEMENTED)


def test_implemented_set_matches_source():
    """防止清单与实际检测逻辑漂移：源码里出现的 rule_id 才算已接入"""
    src = Path(diagnosis.__file__).read_text(encoding='utf-8')
    used = set(re.findall(r"rule_id='([A-Z]+-\d+)'", src))
    assert used == set(diagnosis.RULE_IMPLEMENTED)
    assert used <= set(diagnosis.RULES)


def test_rules_endpoint_exposes_status(client):
    r = client.get('/api/v1/rules')
    assert r.status_code == 200
    data = r.json()
    assert data['total'] == 21
    assert data['implemented'] == len(diagnosis.RULE_IMPLEMENTED)
    assert any(x['implemented'] for x in data['rules'])
    assert all(x['implemented'] for x in data['rules'])
