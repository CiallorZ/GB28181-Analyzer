#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""源编码/源分辨率不能被转码产物覆盖（P0-9）"""
from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from app.parsers import capture
from app.services import analyzer, rebuild


def _video(**kw):
    base = dict(codec=None, width=None, height=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_source_media_prefers_ps_over_rebuild():
    ps = SimpleNamespace(video=_video(codec='H.265', width=2688, height=1520))
    rb = SimpleNamespace(codec='h264', width=1280, height=724)
    assert analyzer._source_media(ps, rb) == {
        'codec': 'H.265', 'width': 2688, 'height': 1520}


def test_source_media_falls_back_to_rebuild():
    ps = SimpleNamespace(video=_video())
    rb = SimpleNamespace(codec='h264', width=1280, height=724)
    assert analyzer._source_media(ps, rb) == {
        'codec': 'H.264', 'width': 1280, 'height': 724}


def test_source_media_without_any_hint():
    assert analyzer._source_media(None, None) == {
        'codec': None, 'width': None, 'height': None}


@pytest.mark.skipif(not (capture.FFMPEG and capture.FFPROBE),
                    reason='需要 ffmpeg/ffprobe')
@pytest.mark.parametrize('src_w,src_h,out_w,out_h', [
    (640, 360, 640, 360),        # 小分辨率不放大
    (1920, 1080, 1280, 720),     # 大分辨率缩到 1280 宽
])
def test_transcode_never_upscales(tmp_path, src_w, src_h, out_w, out_h):
    src = tmp_path / 'src.mp4'
    out = tmp_path / 'out.mp4'
    subprocess.run([
        capture.FFMPEG, '-hide_banner', '-loglevel', 'error',
        '-f', 'lavfi', '-i',
        'color=c=black:s=%dx%d:d=0.3' % (src_w, src_h),
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-y', str(src),
    ], check=True, timeout=60)

    ok, err = rebuild.transcode(str(src), str(out))
    assert ok, err
    info = rebuild.probe(str(out))
    assert (info.get('width'), info.get('height')) == (out_w, out_h)
