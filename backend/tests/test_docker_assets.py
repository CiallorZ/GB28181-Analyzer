#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""部署文件必须存在且关键口径一致

CI 会构建镜像；这里先做不需要 Docker 的静态校验，本地也能跑。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_docker_assets_exist():
    for name in ('docker-compose.yml', 'backend/Dockerfile',
                 'frontend/Dockerfile', 'frontend/nginx.conf',
                 '.gitattributes'):
        assert (ROOT / name).is_file(), name


def test_compose_has_both_services():
    text = (ROOT / 'docker-compose.yml').read_text(encoding='utf-8')
    assert 'backend:' in text
    assert 'frontend:' in text
    assert './data:/app/data' in text


def test_nginx_proxies_api_and_keeps_sse_unbuffered():
    text = (ROOT / 'frontend/nginx.conf').read_text(encoding='utf-8')
    assert 'location /api/' in text
    assert 'proxy_pass http://backend:8788' in text
    assert 'proxy_buffering off' in text
    assert 'try_files $uri $uri/ /index.html' in text
