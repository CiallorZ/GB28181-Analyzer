#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PS / PES / ES 解封装与视频编码分析（M08）

国标 GB28181 的媒体载荷是 MPEG-PS 封装，结构：

    RTP payload
      └─ PS Pack (00 00 01 BA)
           ├─ System Header (00 00 01 BB)
           ├─ PSM (00 00 01 BC)
           └─ PES Packet (00 00 01 E0 = video, 00 00 01 C0/C1 = audio)
                └─ ES (H.264 / H.265 NAL units)

本模块做三件事：
1. 解析 PS 层，取出视频/音频 PES
2. 从 ES 里识别 NAL 类型、参数集、帧类型、关键帧
3. 解析 SPS 拿到分辨率与帧率（不依赖 ffmpeg）

设计原则：
- 所有解析都是"尽力而为"，遇到畸形数据记录到 warnings 而不是崩溃
- 不猜测：解析不出的字段留 None
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field

# ---------------------------------------------------------------
# PS 层常量
# ---------------------------------------------------------------
PS_PACK_START = b'\x00\x00\x01\xba'
PS_SYSTEM_HEADER = b'\x00\x00\x01\xbb'
PS_PSM = b'\x00\x00\x01\xbc'
PES_VIDEO = b'\x00\x00\x01\xe0'
PES_AUDIO = (b'\x00\x00\x01\xc0', b'\x00\x00\x01\xc1',
             b'\x00\x00\x01\xc2', b'\x00\x00\x01\xc3')

MAX_PS_BYTES = 64 * 1024 * 1024       # 单流上限，防止畸形数据撑爆内存


@dataclass
class VideoInfo:
    """视频编码分析结果"""
    codec: str | None = None           # 'H.264' / 'H.265'
    profile: str | None = None
    level: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    bit_depth: int | None = None

    frame_count: int = 0
    keyframe_count: int = 0
    i_frame_count: int = 0
    p_frame_count: int = 0
    b_frame_count: int = 0

    has_vps: bool = False
    has_sps: bool = False
    has_pps: bool = False
    has_idr: bool = False

    first_keyframe_offset: float | None = None   # 相对流起点秒数
    keyframe_intervals: list = field(default_factory=list)
    # 关键帧在 ES 中的字节偏移；由 analyze_ps 结合 RTP 到达时间换算成秒。
    keyframe_offsets: list = field(default_factory=list)
    keyframe_times: list = field(default_factory=list)      # 相对流起点秒数
    keyframe_gop_seconds: list = field(default_factory=list)  # 相邻关键帧间隔
    frame_sizes: list = field(default_factory=list)   # 抽样后的大小分布

    warnings: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'codec': self.codec, 'profile': self.profile, 'level': self.level,
            'width': self.width, 'height': self.height, 'fps': self.fps,
            'bit_depth': self.bit_depth,
            'frame_count': self.frame_count,
            'keyframe_count': self.keyframe_count,
            'i_frame_count': self.i_frame_count,
            'p_frame_count': self.p_frame_count,
            'b_frame_count': self.b_frame_count,
            'has_vps': self.has_vps, 'has_sps': self.has_sps,
            'has_pps': self.has_pps, 'has_idr': self.has_idr,
            'first_keyframe_offset': self.first_keyframe_offset,
            'keyframe_intervals': self.keyframe_intervals[:50],
            'keyframe_times': self.keyframe_times[:50],
            'keyframe_gop_seconds': self.keyframe_gop_seconds[:50],
            'frame_size_stats': _size_stats(self.frame_sizes),
            'warnings': self.warnings,
        }


@dataclass
class AudioInfo:
    codec: str | None = None           # 'G.711A' / 'G.711U' / 'AAC'
    sample_rate: int | None = None
    channels: int | None = None
    pes_count: int = 0


@dataclass
class PsAnalysis:
    has_ps: bool = False
    pack_count: int = 0
    psm_count: int = 0
    video_pes_count: int = 0
    audio_pes_count: int = 0
    video: VideoInfo = field(default_factory=VideoInfo)
    audio: AudioInfo = field(default_factory=AudioInfo)
    pts_list: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'has_ps': self.has_ps,
            'pack_count': self.pack_count,
            'psm_count': self.psm_count,
            'video_pes_count': self.video_pes_count,
            'audio_pes_count': self.audio_pes_count,
            'video': self.video.to_dict() if self.video else None,
            'audio': {
                'codec': self.audio.codec,
                'sample_rate': self.audio.sample_rate,
                'channels': self.audio.channels,
                'pes_count': self.audio.pes_count,
            } if self.audio else None,
            'warnings': self.warnings,
        }


# ---------------------------------------------------------------
# 工具
# ---------------------------------------------------------------
def _size_stats(sizes: list) -> dict | None:
    if not sizes:
        return None
    s = sorted(sizes)
    n = len(s)
    return {
        'min': s[0], 'max': s[-1],
        'avg': round(sum(s) / n, 1),
        'median': s[n // 2],
        'count': n,
    }


def _read_ue(buf: bytes, pos: int) -> tuple[int, int]:
    """读 Exp-Golomb 无符号指数哥伦布码，返回 (值, 新位置)"""
    zeros = 0
    while pos < len(buf) * 8:
        bit = (buf[pos // 8] >> (7 - pos % 8)) & 1
        if bit:
            break
        zeros += 1
        pos += 1
    if zeros > 32:
        raise ValueError('Exp-Golomb 过长')
    pos += 1
    val = 1
    for _ in range(zeros):
        bit = (buf[pos // 8] >> (7 - pos % 8)) & 1
        val = (val << 1) | bit
        pos += 1
    return val - 1, pos


def _read_bits(buf: bytes, pos: int, n: int) -> tuple[int, int]:
    val = 0
    for _ in range(n):
        if pos >= len(buf) * 8:
            raise ValueError('越界')
        bit = (buf[pos // 8] >> (7 - pos % 8)) & 1
        val = (val << 1) | bit
        pos += 1
    return val, pos


def _remove_emulation(data: bytes) -> bytes:
    """去掉防竞争字节 00 00 03 -> 00 00"""
    out = bytearray()
    i = 0
    n = len(data)
    while i < n:
        if i + 2 < n and data[i] == 0 and data[i + 1] == 0 and data[i + 2] == 3:
            out += b'\x00\x00'
            i += 3
        else:
            out.append(data[i])
            i += 1
    return bytes(out)


# ---------------------------------------------------------------
# SPS 解析：拿分辨率与帧率
# ---------------------------------------------------------------
H264_PROFILES = {
    66: 'Baseline', 77: 'Main', 88: 'Extended',
    100: 'High', 110: 'High 10', 122: 'High 4:2:2', 244: 'High 4:4:4',
}

H265_PROFILES = {
    1: 'Main', 2: 'Main 10', 3: 'Main Still Picture',
}


def parse_h264_sps(nal: bytes) -> dict:
    """解析 H.264 SPS，返回 width/height/fps/profile"""
    if len(nal) < 4:
        return {}
    try:
        data = _remove_emulation(nal[1:])     # 跳过 NAL header
        pos = 0
        profile_idc, pos = _read_bits(data, pos, 8)
        _constraint, pos = _read_bits(data, pos, 8)
        level_idc, pos = _read_bits(data, pos, 8)
        sps_id, pos = _read_ue(data, pos)

        chroma_format = 1
        bit_depth_luma = 8
        if profile_idc in (100, 110, 122, 244, 44, 83, 86, 118, 128, 138, 139, 134):
            chroma_format, pos = _read_ue(data, pos)
            if chroma_format == 3:
                pos += 1
            bit_depth_luma, pos = _read_ue(data, pos)
            bit_depth_luma += 8
            bit_depth_chroma, pos = _read_ue(data, pos)
            _qpprime, pos = _read_bits(data, pos, 1)
            if _qpprime:
                for _ in range(8 if chroma_format != 3 else 12):
                    _, pos = _read_ue(data, pos)

        log2_max_frame_num, pos = _read_ue(data, pos)
        log2_max_frame_num += 4
        poc_type, pos = _read_ue(data, pos)
        if poc_type == 0:
            _, pos = _read_ue(data, pos)
        elif poc_type == 1:
            _, pos = _read_bits(data, pos, 1)
            _, pos = _read_ue(data, pos)
            _, pos = _read_ue(data, pos)
            n, pos = _read_ue(data, pos)
            for _ in range(n):
                _, pos = _read_ue(data, pos)

        _, pos = _read_ue(data, pos)          # max_num_ref_frames
        _, pos = _read_bits(data, pos, 1)     # gaps_in_frame_num
        pic_width_mbs, pos = _read_ue(data, pos)
        pic_height_map_units, pos = _read_ue(data, pos)
        frame_mbs_only, pos = _read_bits(data, pos, 1)
        if not frame_mbs_only:
            _, pos = _read_bits(data, pos, 1)

        width = (pic_width_mbs + 1) * 16
        height = (2 - frame_mbs_only) * (pic_height_map_units + 1) * 16

        # 裁剪窗口
        _, pos = _read_bits(data, pos, 1)     # direct_8x8
        cropping, pos = _read_bits(data, pos, 1)
        if cropping:
            l, pos = _read_ue(data, pos)
            r, pos = _read_ue(data, pos)
            t, pos = _read_ue(data, pos)
            b, pos = _read_ue(data, pos)
            sub_w = 1 if chroma_format == 0 else 2
            sub_h = (2 if chroma_format == 1 else 1) * (2 - frame_mbs_only)
            width -= (l + r) * sub_w
            height -= (t + b) * sub_h

        return {
            'width': width, 'height': height,
            'profile': H264_PROFILES.get(profile_idc, 'Profile %d' % profile_idc),
            'level': '%.1f' % (level_idc / 10.0),
            'bit_depth': bit_depth_luma,
            'sps_id': sps_id,
            'log2_max_frame_num': log2_max_frame_num,
        }
    except Exception:
        return {}


def parse_h265_sps(nal: bytes) -> dict:
    """解析 H.265 SPS"""
    if len(nal) < 5:
        return {}
    try:
        data = _remove_emulation(nal[2:])     # 跳过 2 字节 NAL header
        pos = 0
        _, pos = _read_bits(data, pos, 4)     # sps_video_parameter_set_id
        max_sub_layers_minus1, pos = _read_bits(data, pos, 3)
        _, pos = _read_bits(data, pos, 1)     # temporal_id_nesting

        # profile_tier_level
        _, pos = _read_bits(data, pos, 2)     # general_profile_space
        _, pos = _read_bits(data, pos, 1)     # general_tier_flag
        profile_idc, pos = _read_bits(data, pos, 5)
        _, pos = _read_bits(data, pos, 32)    # compatibility flags
        _, pos = _read_bits(data, pos, 4)     # constraint flags
        _, pos = _read_bits(data, pos, 44)    # 剩余 constraint
        _, pos = _read_bits(data, pos, 8)     # general_level_idc

        for _ in range(max_sub_layers_minus1):
            _, pos = _read_bits(data, pos, 2)
            _, pos = _read_bits(data, pos, 1)
        if max_sub_layers_minus1 > 0:
            for _ in range(max_sub_layers_minus1, 8):
                _, pos = _read_bits(data, pos, 2)

        sps_id, pos = _read_ue(data, pos)
        chroma_format, pos = _read_ue(data, pos)
        separate_colour_plane = 0
        if chroma_format == 3:
            separate_colour_plane, pos = _read_bits(data, pos, 1)

        width, pos = _read_ue(data, pos)
        height, pos = _read_ue(data, pos)

        conf_win, pos = _read_bits(data, pos, 1)
        if conf_win:
            l, pos = _read_ue(data, pos)
            r, pos = _read_ue(data, pos)
            t, pos = _read_ue(data, pos)
            b, pos = _read_ue(data, pos)
            # HEVC conformance window 使用 SubWidthC/SubHeightC。4:2:0
            # 的常见 1080p 会编码为 1088 并裁掉底部 4 个色度单位。
            if separate_colour_plane or chroma_format == 0:
                sub_w, sub_h = 1, 1
            elif chroma_format == 1:
                sub_w, sub_h = 2, 2
            elif chroma_format == 2:
                sub_w, sub_h = 2, 1
            else:
                sub_w, sub_h = 1, 1
            width -= (l + r) * sub_w
            height -= (t + b) * sub_h

        bit_depth_luma_minus8, pos = _read_ue(data, pos)
        bit_depth_chroma_minus8, pos = _read_ue(data, pos)
        bit_depth = bit_depth_luma_minus8 + 8
        return {
            'width': width, 'height': height,
            'profile': H265_PROFILES.get(profile_idc, 'Profile %d' % profile_idc),
            'bit_depth': bit_depth,
            'bit_depth_chroma': bit_depth_chroma_minus8 + 8,
            'chroma_format': chroma_format,
            'sps_id': sps_id,
        }
    except Exception:
        return {}


# ---------------------------------------------------------------
# NAL 类型判定
# ---------------------------------------------------------------
def _iter_nal_spans(data: bytes):
    """按起始码切分 NAL，产出 (nal_bytes, 起始码偏移)

    偏移是相对整段 ES 的字节位置。关键帧时间要靠它映射回具体的 RTP 包，
    所以不能用"累计 len(nal)+4"近似——起始码有 3 字节也有 4 字节，
    长流上逐 NAL 的误差会累积到错位一个包。
    """
    from . import native_scan
    if native_scan.scan is not None and isinstance(data, bytes):
        previous = None
        for off, prefix in native_scan.iter_markers(data, native_scan.scan):
            if previous is not None:
                start, begin = previous
                if off > begin:
                    yield data[begin:off], start
            previous = off, off + prefix
        if previous is not None and previous[1] < len(data):
            yield data[previous[1]:], previous[0]
        return

    i = 0
    n = len(data)
    starts = []
    while i < n - 3:
        if data[i] == 0 and data[i + 1] == 0:
            if data[i + 2] == 1:
                starts.append((i, 3))
                i += 3
                continue
            if i + 3 < n and data[i + 2] == 0 and data[i + 3] == 1:
                starts.append((i, 4))
                i += 4
                continue
        i += 1

    for idx, (off, sc_len) in enumerate(starts):
        begin = off + sc_len
        end = starts[idx + 1][0] if idx + 1 < len(starts) else n
        if end > begin:
            yield data[begin:end], off


def _iter_nal(data: bytes):
    """按起始码切分 NAL，产出 nal_bytes"""
    for nal, _off in _iter_nal_spans(data):
        yield nal


def _h264_slice_head(nal: bytes):
    """读取 H.264 slice header 的头两个字段：first_mb_in_slice / slice_type"""
    if len(nal) < 2:
        return None
    data = _remove_emulation(nal[1:])
    try:
        first_mb, pos = _read_ue(data, 0)
        slice_type, pos = _read_ue(data, pos)
        return first_mb, slice_type
    except Exception:
        return None


def _h265_first_slice(nal: bytes) -> bool:
    """H.265 slice_segment_header 的第一个 bit 就是 first_slice_segment_in_pic_flag"""
    if len(nal) < 3:
        return False
    data = _remove_emulation(nal[2:])
    return bool(data and (data[0] & 0x80))


def analyze_es(es: bytes, start_time: float = 0.0) -> VideoInfo:
    """分析 ES 数据，识别编码与帧结构

    es: 拼接后的视频 ES 数据（多个 PES 的 payload 相连）

    帧数以 **访问单元（AU / 编码图像）** 为单位，而不是 NAL 数量：
    一帧通常由 SPS/PPS/SEI + 多个 slice NAL 组成，按 NAL 计数会把帧数
    放大若干倍，帧率、I/P/B 比例随之全部失真。
    """
    info = VideoInfo()
    if not es:
        info.warnings.append('没有视频 ES 数据')
        return info

    # ---- 第一遍：判定编码、参数集 ----
    h264_score = 0
    h265_score = 0
    sps_parsed = None

    for nal in _iter_nal(es):
        if not nal:
            continue
        b0 = nal[0]
        h264_type = b0 & 0x1F
        h265_type = (b0 >> 1) & 0x3F

        # H.264 特征：SPS(7) PPS(8) IDR(5) 非IDR(1)
        if h264_type in (1, 5, 7, 8) and b0 & 0x80 == 0:
            h264_score += 1
        # H.265 特征：VPS(32) SPS(33) PPS(34) IDR(19/20)
        if h265_type in (19, 20, 32, 33, 34):
            h265_score += 1

        if h264_type == 7 and len(nal) > 4:
            sps = parse_h264_sps(nal)
            if sps.get('width') and not sps_parsed:
                sps_parsed = sps
                info.has_sps = True
        elif h264_type == 8:
            info.has_pps = True

        if h265_type == 32:
            info.has_vps = True
        elif h265_type == 33 and len(nal) > 5:
            sps = parse_h265_sps(nal)
            if sps.get('width') and not sps_parsed:
                sps_parsed = sps
                info.has_sps = True
        elif h265_type == 34:
            info.has_pps = True

    # 判定编码
    if h265_score > h264_score:
        info.codec = 'H.265'
    elif h264_score > 0:
        info.codec = 'H.264'
    elif h265_score > 0:
        info.codec = 'H.265'
    else:
        info.warnings.append('无法识别 NAL 类型，可能不是标准 H.264/H.265')

    if sps_parsed:
        info.width = sps_parsed.get('width')
        info.height = sps_parsed.get('height')
        info.profile = sps_parsed.get('profile')
        info.level = sps_parsed.get('level')
        info.bit_depth = sps_parsed.get('bit_depth')
    else:
        if info.codec:
            info.warnings.append(
                '未找到可解析的 SPS：抓包可能起始于 GOP 中间，缺少参数集')

    # ---- 第二遍：按访问单元计帧 ----
    if not info.codec:
        return info

    keyframe_positions = []
    au_bytes = 0          # 当前 AU 已累计字节
    prefix_bytes = 0      # AU 之前、属于下一帧的参数集/SEI 字节
    prefix_start = 0      # 上述前缀在 ES 中的起始偏移
    au_kind = None        # 'I' / 'P' / 'B'
    au_start = 0
    have_au = False

    def _flush():
        if not have_au:
            return
        info.frame_count += 1
        if len(info.frame_sizes) < 3000:
            info.frame_sizes.append(au_bytes)
        if au_kind == 'I':
            info.i_frame_count += 1
            info.keyframe_count += 1
            keyframe_positions.append(au_start)
        elif au_kind == 'B':
            info.b_frame_count += 1
        else:
            info.p_frame_count += 1

    for nal, nal_start in _iter_nal_spans(es):
        if not nal:
            continue
        size = len(nal) + 4
        b0 = nal[0]
        new_pic = False
        kind = None

        if info.codec == 'H.264':
            t = b0 & 0x1F
            is_vcl = 1 <= t <= 5
            if is_vcl:
                head = _h264_slice_head(nal)
                if head is not None and head[0] == 0:
                    new_pic = True
                    if t == 5:
                        kind = 'I'
                    else:
                        st = head[1] % 5
                        kind = 'I' if st == 2 else ('B' if st == 1 else 'P')
                if t == 5:
                    info.has_idr = True
        else:
            t = (b0 >> 1) & 0x3F
            is_vcl = t <= 31
            if is_vcl and _h265_first_slice(nal):
                new_pic = True
                kind = 'I' if 16 <= t <= 23 else 'P'
                if t in (19, 20):
                    info.has_idr = True

        if new_pic:
            _flush()
            au_bytes = prefix_bytes + size
            # AU 从它的前缀（SPS/PPS/SEI）开始；没有前缀就从本 NAL 开始。
            au_start = prefix_start if prefix_bytes else nal_start
            prefix_bytes = 0
            au_kind = kind
            have_au = True
        elif is_vcl and have_au:
            au_bytes += size
        else:
            # AUD/SPS/PPS/SEI 属于"下一帧"的前缀，不能算进当前帧
            if prefix_bytes == 0:
                prefix_start = nal_start
            prefix_bytes += size

    _flush()

    # 关键帧间隔（按字节位置换算成时间不可靠，这里只给间隔的字节跨度）
    info.keyframe_offsets = keyframe_positions[:200]
    if len(keyframe_positions) >= 2:
        spans = [keyframe_positions[i + 1] - keyframe_positions[i]
                 for i in range(len(keyframe_positions) - 1)]
        info.keyframe_intervals = spans[:50]

    return info


def estimate_fps(es_len: int, duration: float, frame_count: int) -> float | None:
    """用帧数/时长估算帧率

    只有两者都可信时才给结果，否则返回 None（不猜）
    """
    if not duration or duration <= 0 or not frame_count:
        return None
    fps = frame_count / duration
    if 1 <= fps <= 120:
        return round(fps, 2)
    return None


# ---------------------------------------------------------------
# PS 解封装主入口
# ---------------------------------------------------------------
def analyze_ps(payloads: list, timestamps: list | None = None,
               rtp_timestamps: list | None = None,
               clock_rate: int | None = None) -> PsAnalysis:
    """对一条流的多个 RTP payload 做 PS 解封装

    payloads: [bytes, ...]  每个 RTP 包的载荷
    timestamps: 对应的到达时间（可选，用于定位首个关键帧）
    rtp_timestamps: 对应的 RTP 时间戳（可选，比到达时间更稳）
    clock_rate: RTP 时钟频率（可选，默认 90 kHz）

    keyframe_times 以秒为单位、相对流起点。优先用 RTP 时间戳换算：
    到达时间会被网络抖动和抓包点排队影响，RTP 时间戳才是编码器时基。
    两者都没有时留空，不猜。
    """
    out = PsAnalysis()
    if not payloads:
        out.warnings.append('没有 RTP 载荷')
        return out

    total = 0
    video_es = bytearray()
    audio_es = bytearray()
    keyframe_time = None
    # ES 字节位置 → 该段最后一个 RTP 包的 (到达时间, RTP 时间戳)。
    # 关键帧的字节偏移落在这段区间内时，用它定位到具体 RTP 包。
    es_marks: list = []

    for idx, pay in enumerate(payloads):
        if not pay:
            continue
        total += len(pay)
        if total > MAX_PS_BYTES:
            out.warnings.append('PS 数据超过 %d MB，已截断' % (MAX_PS_BYTES // 1024 // 1024))
            break

        if PS_PACK_START in pay:
            out.has_ps = True
            out.pack_count += pay.count(PS_PACK_START)
        if PS_PSM in pay:
            out.psm_count += pay.count(PS_PSM)

        has_v = PES_VIDEO in pay
        has_a = any(m in pay for m in PES_AUDIO)
        if has_v:
            out.video_pes_count += pay.count(PES_VIDEO)
        if has_a:
            for m in PES_AUDIO:
                out.audio_pes_count += pay.count(m)

        if has_v:
            # 取 video PES 之后的部分作为 ES
            pos = pay.find(PES_VIDEO)
            while pos >= 0:
                seg_start = pos + 4
                nxt = pay.find(PES_VIDEO, seg_start)
                seg = _pes_payload(pay[seg_start:nxt if nxt > 0 else len(pay)])
                if seg:
                    if keyframe_time is None and timestamps and idx < len(timestamps):
                        if (b'\x00\x00\x01\x65' in seg or b'\x00\x00\x00\x01\x65' in seg
                                or b'\x00\x00\x01\x26' in seg
                                or b'\x00\x00\x00\x01\x26' in seg):
                            keyframe_time = timestamps[idx]
                    video_es += seg
                    es_marks.append((
                        len(video_es),
                        timestamps[idx] if timestamps and idx < len(timestamps) else None,
                        (rtp_timestamps[idx]
                         if rtp_timestamps and idx < len(rtp_timestamps) else None),
                    ))
                if nxt < 0:
                    break
                pos = nxt

        if has_a:
            for marker in PES_AUDIO:
                pos = pay.find(marker)
                if pos < 0:
                    continue
                audio_es += _pes_payload(pay[pos + 4:])
                break

    # 视频分析
    if video_es:
        out.video = analyze_es(bytes(video_es))
        if keyframe_time is not None:
            # keyframe_time 是绝对到达时间；这里要的是"相对流起点"，
            # 否则上层算出的首关键帧耗时会混进抓包时间轴的偏移。
            origin = timestamps[0] if timestamps else 0.0
            out.video.first_keyframe_offset = round(keyframe_time - origin, 3)
        _fill_keyframe_times(
            out.video, es_marks, clock_rate,
            origin_arrival=timestamps[0] if timestamps else None,
            origin_rtp=rtp_timestamps[0] if rtp_timestamps else None)
    else:
        out.video.warnings.append('未提取到视频 ES（可能是纯音频流或非 PS 封装）')

    # 音频分析
    if audio_es:
        out.audio.pes_count = out.audio_pes_count
        out.audio.codec = _guess_audio_codec(bytes(audio_es[:4096]))

    if not out.has_ps:
        out.warnings.append('载荷中未发现 PS 包头，可能不是 MPEG-PS 封装')

    return out


def _wrap_delta(value: int, base: int) -> int:
    """32 位 RTP 时间戳的有符号差值，跨回绕仍得到正的前进量"""
    delta = (value - base) & 0xFFFFFFFF
    return delta - (1 << 32) if delta & 0x80000000 else delta


def _fill_keyframe_times(video: VideoInfo, es_marks: list,
                         clock_rate: int | None,
                         origin_arrival: float | None = None,
                         origin_rtp: int | None = None) -> None:
    """把关键帧的 ES 字节偏移换算成相对流起点的秒数

    优先用 RTP 时间戳（编码器时基），缺失时退回到达时间；
    两者都缺就留空。时钟率未知时按 90 kHz —— 国标 PS 流的事实标准。

    基准是取样窗口的第一个 RTP 包（origin_*），不是首个关键帧：
    "首关键帧耗时"要和"首媒体耗时"用同一根时间轴才能相加。
    这里只给"相对流起点"的时间，不声称是播放器显示时间。
    """
    offsets = video.keyframe_offsets
    if not offsets or not es_marks:
        return
    rate = clock_rate if clock_rate and clock_rate > 0 else 90000
    # es_marks 按 PES 段结束位置递增，用二分定位每个关键帧落在哪一段，
    # 避免逐个关键帧线性扫描（长流上关键帧与 PES 段都不少）。
    ends = [m[0] for m in es_marks]
    marks = []
    for off in offsets:
        idx = bisect.bisect_right(ends, off)
        if idx >= len(es_marks):
            # 关键帧落在最后一个 PES 段之后（或恰好压在段边界上），
            # 无法定位到具体包。整条序列作废：跳过中间某个关键帧会让
            # 相邻间隔跨过它，算出的 GOP 直接翻倍，MED-010 随之误报。
            return
        marks.append(es_marks[idx])
    if not marks:
        return

    # 同一序列必须只用一种时基：混用 RTP 时间戳与到达时间会让差值毫无意义。
    # 只有全部关键帧都能定位到 RTP 时间戳时才用 RTP，否则整体退回到达时间。
    if all(m[2] is not None for m in marks):
        base = origin_rtp if origin_rtp is not None else es_marks[0][2]
        if base is None:
            base = marks[0][2]
        seconds = [_wrap_delta(m[2], base) / rate for m in marks]
    elif all(m[1] is not None for m in marks):
        base = origin_arrival if origin_arrival is not None else es_marks[0][1]
        if base is None:
            base = marks[0][1]
        seconds = [m[1] - base for m in marks]
    else:
        return

    # 时间戳回绕或乱序可能算出负值；关键帧时间轴不应倒退，丢弃这类点。
    if any(s < 0 for s in seconds):
        return

    video.keyframe_times = [round(s, 3) for s in seconds[:50]]
    video.keyframe_gop_seconds = [
        round(seconds[i + 1] - seconds[i], 3)
        for i in range(len(seconds) - 1)
    ][:50]
    # RTP 时间戳比字节扫描得到的到达时间更准，允许覆盖先前的结果。
    video.first_keyframe_offset = round(seconds[0], 3)


def _pes_payload(seg: bytes) -> bytes:
    """剥掉 PES 头，返回 ES 载荷

    seg 从 PES_packet_length 开始（调用方已经吃掉 00 00 01 Ex）：
      [0:2] packet_length  [2] '10'+flags  [3] flags2  [4] header_data_length
    旧实现把 seg[0] 当标志字节，整体错位 2 字节：长度字段和 PES 头会混进
    ES，导致 NAL 尺寸偏大、极少数情况下出现伪起始码。这里按 MPEG-2 布局取。
    """
    if len(seg) < 5:
        return b''
    if (seg[2] & 0xC0) != 0x80:        # 不是 MPEG-2 PES 头（MPEG-1 流不处理）
        return seg
    hdr_len = seg[4]
    return seg[5 + hdr_len:]


def _guess_audio_codec(data: bytes) -> str | None:
    """粗判音频编码

    国标常见：G.711A（PCMA）、G.711U（PCMU）、AAC
    G.711 是无帧头的裸 PCM，无法从数据本身确定，只能靠 SDP 的 rtpmap。
    这里只在能识别 ADTS 头时返回 AAC，否则返回 None（不猜）。
    """
    if len(data) > 2 and data[0] == 0xFF and (data[1] & 0xF0) == 0xF0:
        return 'AAC (ADTS)'
    return None
