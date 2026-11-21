#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
媒体重建（M08-04）

把 RTP 载荷里的 PS 流还原成可播放的 MP4 + 关键帧图片。

三个关键处理（都踩过坑）：
1. **参数集对齐** —— 抓包常从 GOP 中间开始，开头的 P 帧没有参考帧，
   进入解码器会报 "PPS id out of range" 并连带后续画面异常。
   从第一个 SPS/PPS 所在的 PS 包开始解码就能恢复。
2. **容错解码** —— `-err_detect ignore_err` + `-fflags +genpts+discardcorrupt`
   容忍码流瑕疵，不因单帧错误中断整条流。
3. **时钟基准** —— 音视频共用 SSRC 时 PTS 基准可能差几小时，
   所以视频轨单独转码（`-an`），避免被音频时间戳拖爆。
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass

from ..parsers import capture

MAX_SECONDS = 60          # 单条流转码时长上限
FFMPEG_TIMEOUT = 900
MIN_PS_BYTES = 4096       # 小于这个不值得转码

# 预览转码只降不升：2688×1520 -> 1280×724，640×360 保持 640×360。
# 固定 scale=1280:-2 会把低分辨率源放大，既伪造成"高清"，也浪费 CPU。
TRANSCODE_SCALE = "scale='min(1280,iw)':-2"


@dataclass
class RebuildResult:
    ok: bool = False
    mp4_path: str | None = None
    poster_path: str | None = None
    frames: int | None = None
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    codec: str | None = None
    source_codec: str | None = None
    source_width: int | None = None
    source_height: int | None = None
    error: str | None = None
    aligned: bool = False
    ps_bytes: int = 0


# ---------------------------------------------------------------
# 参数集对齐
# ---------------------------------------------------------------
PARAM_SETS = (
    (b'\x40', 'h265_vps'),
    (b'\x42', 'h265_sps'),
    (b'\x44', 'h265_pps'),
    (b'\x67', 'h264_sps'),
    (b'\x68', 'h264_pps'),
)


def align_to_params(data: bytes) -> tuple[bytes, bool]:
    """裁剪到第一个参数集所在的 PS 包

    返回 (裁剪后数据, 是否发生裁剪)
    """
    hits = []
    for nal, _name in PARAM_SETS:
        for sc in (b'\x00\x00\x00\x01', b'\x00\x00\x01'):
            j = data.find(sc + nal)
            if j >= 0:
                hits.append(j)
                break
    if not hits:
        return data, False

    first = min(hits)
    if first < 1024:              # 开头就有参数集，无需裁剪
        return data, False

    # 退到所在 PS 包的包头，保持结构完整
    ba = data.rfind(b'\x00\x00\x01\xba', 0, first)
    start = ba if ba >= 0 else first
    if start <= 0:
        return data, False
    return data[start:], True


# ---------------------------------------------------------------
# 从 RTP 包提取 PS
# ---------------------------------------------------------------
def extract_ps_from_packets(pkts) -> bytes:
    """把 RTP 载荷按顺序拼成 PS 流

    注意：不做去重/重排，保持原始顺序 —— ffmpeg 的 PS 解析器
    对时间戳顺序敏感，重排反而会打乱 PTS。
    """
    out = bytearray()
    for p in pkts:
        if p.payload:
            out += p.payload
    return bytes(out)


# ---------------------------------------------------------------
# ffprobe 取元信息
# ---------------------------------------------------------------
def probe(path: str) -> dict:
    if not capture.FFPROBE:
        return {}
    try:
        r = subprocess.run(
            [capture.FFPROBE, '-v', 'error', '-show_streams', '-show_format',
             '-of', 'json', path],
            capture_output=True, text=True, errors='replace', timeout=120)
        j = json.loads(r.stdout or '{}')
    except Exception:
        return {}

    info = {}
    for st in j.get('streams', []):
        if st.get('codec_type') == 'video':
            info['width'] = st.get('width')
            info['height'] = st.get('height')
            info['codec'] = st.get('codec_name')
            fr = st.get('avg_frame_rate') or st.get('r_frame_rate') or ''
            if '/' in fr:
                try:
                    a, b = fr.split('/')
                    info['fps'] = round(float(a) / float(b), 2) if float(b) else None
                except (ValueError, ZeroDivisionError):
                    pass
            # 时长：优先用视频流自身
            for key in ('duration', 'duration_ts'):
                try:
                    v = float(st.get(key) or 0)
                    if key == 'duration_ts':
                        v = v / 90000.0
                    if 0 < v < 3600:
                        info['duration'] = round(v, 2)
                        break
                except (TypeError, ValueError):
                    continue
    if 'duration' not in info:
        try:
            d = float(j.get('format', {}).get('duration', 0))
            if 0 < d < 3600:
                info['duration'] = round(d, 2)
        except (TypeError, ValueError):
            pass
    return info


def count_frames(path: str) -> int | None:
    """用 -f null 数帧，顺带拿到真实解码帧数"""
    if not capture.FFMPEG:
        return None
    try:
        r = subprocess.run(
            [capture.FFMPEG, '-hide_banner', '-i', path, '-an',
             '-map', '0:v:0', '-f', 'null', '-'],
            capture_output=True, text=True, errors='replace',
            timeout=FFMPEG_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None
    for line in (r.stderr or '').splitlines():
        if line.startswith('frame='):
            try:
                return int(line.split('frame=')[1].split()[0])
            except (IndexError, ValueError):
                pass
    return None


# ---------------------------------------------------------------
# 转码
# ---------------------------------------------------------------
def transcode(ps_path: str, mp4_path: str, poster_path: str | None = None
              ) -> tuple[bool, str | None]:
    if not capture.FFMPEG:
        return False, '未找到 ffmpeg，无法转码'

    cmd = [
        capture.FFMPEG, '-hide_banner', '-loglevel', 'error',
        # 容忍码流瑕疵，不因单帧错误中断
        '-err_detect', 'ignore_err',
        # 参考帧缺失时丢弃坏帧，而不是输出花屏
        '-fflags', '+genpts+discardcorrupt',
        '-i', ps_path,
        '-an',                          # 只要视频轨
        '-c:v', 'libx264',
        '-preset', 'veryfast',          # 比 medium 快约 2 倍，画质差异可忽略
        '-crf', '24',
        '-vf', TRANSCODE_SCALE,
        '-pix_fmt', 'yuv420p',          # 浏览器兼容
        '-movflags', '+faststart',
        '-t', str(MAX_SECONDS),
        '-y', mp4_path,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           errors='replace', timeout=FFMPEG_TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, '转码超时（%d 秒）' % FFMPEG_TIMEOUT

    if not (os.path.exists(mp4_path) and os.path.getsize(mp4_path) > 1024):
        err = (r.stderr or '').strip()[:400]
        return False, '转码失败：%s' % (err or '输出为空')

    # 封面：优先取第 1 秒，短视频退回第一帧
    if poster_path:
        for ss in ('1', '0'):
            try:
                subprocess.run(
                    [capture.FFMPEG, '-hide_banner', '-loglevel', 'error',
                     '-ss', ss, '-i', mp4_path, '-frames:v', '1',
                     '-q:v', '4', '-y', poster_path],
                    capture_output=True, timeout=90)
            except subprocess.TimeoutExpired:
                pass
            if os.path.exists(poster_path) and os.path.getsize(poster_path) > 512:
                break
        else:
            try:
                subprocess.run(
                    [capture.FFMPEG, '-hide_banner', '-loglevel', 'error',
                     '-i', mp4_path, '-frames:v', '1', '-q:v', '4',
                     '-y', poster_path],
                    capture_output=True, timeout=90)
            except subprocess.TimeoutExpired:
                pass

    return True, None


# ---------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------
def rebuild_stream(pkts, out_dir: str, tag: str,
                   duration_hint: float | None = None) -> RebuildResult:
    """把一条 RTP 流重建为 MP4 + 封面

    pkts: [RtpPacket]，需已按到达顺序排列
    out_dir: 输出目录
    tag: 文件名前缀（如 tcp0 / udp1）
    """
    res = RebuildResult()

    if not pkts:
        res.error = '该流没有 RTP 包'
        return res

    ps = extract_ps_from_packets(pkts)
    res.ps_bytes = len(ps)
    if len(ps) < MIN_PS_BYTES:
        res.error = 'PS 数据不足（%d 字节），无法解码' % len(ps)
        return res

    # 参数集对齐
    aligned, was_aligned = align_to_params(ps)
    res.aligned = was_aligned
    if was_aligned:
        ps = aligned

    os.makedirs(out_dir, exist_ok=True)
    ps_path = os.path.join(out_dir, '%s.ps' % tag)
    mp4_path = os.path.join(out_dir, '%s.mp4' % tag)
    poster_path = os.path.join(out_dir, '%s.jpg' % tag)

    with open(ps_path, 'wb') as f:
        f.write(ps)

    source = probe(ps_path)
    res.source_codec = source.get('codec')
    res.source_width = source.get('width')
    res.source_height = source.get('height')

    ok, err = transcode(ps_path, mp4_path, poster_path)
    if not ok:
        res.error = err
        # 保留 .ps 供人工排查，但不作为交付产物
        return res

    res.ok = True
    res.mp4_path = mp4_path
    res.poster_path = poster_path if (os.path.exists(poster_path)
                                      and os.path.getsize(poster_path) > 512) else None

    info = probe(mp4_path)
    res.width = info.get('width')
    res.height = info.get('height')
    res.fps = info.get('fps')
    res.duration = info.get('duration') or duration_hint
    res.codec = info.get('codec')
    res.frames = count_frames(mp4_path)

    # 清理中间 .ps（体积大且无保留价值）
    try:
        os.remove(ps_path)
    except OSError:
        pass

    return res

# ---------------------------------------------------------------
# 并行重建（多流同时转码，利用多核）
# ---------------------------------------------------------------
def rebuild_streams_parallel(tasks: list, out_dir: str,
                             max_workers: int = 3) -> dict:
    """并行重建多条流

    tasks: [(tag, pkts, duration_hint), ...]
    返回 {tag: RebuildResult}

    ffmpeg 单实例只用 1-2 核，多流并行能把总耗时压到接近 1/N。
    默认 3 并发，避免 IO 与内存压力过大。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    if not tasks:
        return {}

    os.makedirs(out_dir, exist_ok=True)
    results = {}
    workers = min(max_workers, len(tasks))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        for tag, pkts, dur in tasks:
            fut = pool.submit(rebuild_stream, pkts, out_dir, tag, dur)
            futures[fut] = tag
        for fut in as_completed(futures):
            tag = futures[fut]
            try:
                results[tag] = fut.result()
            except Exception as e:
                r = RebuildResult()
                r.error = '重建异常：%s' % e
                results[tag] = r
    return results
