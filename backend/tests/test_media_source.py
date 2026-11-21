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


def test_source_probe_overrides_misidentified_elementary_stream():
    ps = SimpleNamespace(video=_video(codec='H.264', width=16, height=16))
    rb = SimpleNamespace(codec='h264', width=320, height=240,
                         source_codec='mpeg2video', source_width=320, source_height=240)
    assert analyzer._source_media(ps, rb) == {
        'codec': 'MPEG2VIDEO', 'width': 320, 'height': 240}


def test_source_media_does_not_infer_source_from_transcoded_preview():
    ps = SimpleNamespace(video=_video())
    rb = SimpleNamespace(codec='h264', width=1280, height=724)
    assert analyzer._source_media(ps, rb) == {
        'codec': None, 'width': None, 'height': None}


def test_conflicting_source_codec_does_not_borrow_sps_dimensions():
    ps = SimpleNamespace(video=_video(codec='H.264', width=16, height=16))
    rb = SimpleNamespace(codec='h264', width=320, height=240,
                         source_codec='mpeg2video', source_width=None, source_height=None)
    assert analyzer._source_media(ps, rb) == {
        'codec': 'MPEG2VIDEO', 'width': None, 'height': None}


def test_source_media_without_any_hint():
    assert analyzer._source_media(None, None) == {
        'codec': None, 'width': None, 'height': None}


def test_failed_transcode_does_not_reuse_or_overwrite_old_preview(tmp_path, monkeypatch):
    output = tmp_path / 'preview.mp4'
    poster = tmp_path / 'poster.jpg'
    output.write_bytes(b'old-preview' * 200)
    poster.write_bytes(b'old-poster')
    monkeypatch.setattr(capture, 'FFMPEG', 'ffmpeg')

    def fail_with_partial_output(cmd, **_kwargs):
        from pathlib import Path
        Path(cmd[-1]).write_bytes(b'partial-output' * 200)
        return SimpleNamespace(returncode=1, stderr='invalid input')

    monkeypatch.setattr(rebuild.subprocess, 'run', fail_with_partial_output)
    ok, error = rebuild.transcode('source.ps', str(output), str(poster))
    assert not ok and 'invalid input' in error
    assert output.read_bytes() == b'old-preview' * 200
    assert poster.read_bytes() == b'old-poster'
    assert sorted(p.name for p in tmp_path.iterdir()) == ['poster.jpg', 'preview.mp4']


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
