# -*- coding: utf-8 -*-
"""版本号只有一处来源，防止发布时前后端各写各的"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app import __version__
from app.main import app


def test_health_reports_package_version(client):
    r = client.get('/api/v1/health')
    assert r.status_code == 200
    assert r.json()['version'] == __version__
    assert app.version == __version__


def test_version_is_semver():
    assert re.fullmatch(r'\d+\.\d+\.\d+', __version__), __version__


def test_health_exposes_persisted_log_path(client):
    response = client.get('/api/v1/health')
    assert response.status_code == 200
    log_path = response.json()['log_path']
    assert log_path.endswith('analyzer.log')
    assert Path(log_path).is_file()


def test_desktop_version_matches():
    root = Path(__file__).resolve().parents[2]
    nsh = json.loads((root / 'desktop-nsh' / 'nsh.json').read_text(encoding='utf-8'))
    assert nsh['version'] == __version__
    cargo = (root / 'desktop' / 'Cargo.toml').read_text(encoding='utf-8')
    assert 'version = "%s"' % __version__ in cargo
    lock = (root / 'desktop' / 'Cargo.lock').read_text(encoding='utf-8')
    assert 'name = "gb28181-desktop"\nversion = "%s"' % __version__ in lock


def test_frontend_version_matches():
    pkg = Path(__file__).resolve().parents[2] / 'frontend' / 'package.json'
    if not pkg.exists():
        pytest.skip('仅后端目录时跳过前端版本校验')
    assert json.loads(pkg.read_text(encoding='utf-8'))['version'] == __version__
