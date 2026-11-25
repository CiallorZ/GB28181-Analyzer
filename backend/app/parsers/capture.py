#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
抓包文件底层读取（M01-02 / M02）

用 tshark 做报文抽取，但**不信任它的解析结果**——
SIP/SDP/RTP/PS 全部由本项目自研解析器处理，tshark 只负责：
1. 读文件、识别格式
2. 按过滤条件输出指定字段

原则：
- 流式读取，不把整个 pcap 载入内存
- 所有命令列表传参，不用 shell=True
- 每个外部进程都有超时，异常带上下文
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime

from ..core import analysis_control, toolchain

# ---------------------------------------------------------------
# 工具定位
# ---------------------------------------------------------------
def refresh_tools() -> None:
    """Re-read manual paths, environment and PATH without restarting the app."""
    global TSHARK, CAPINFOS, FFMPEG, FFPROBE, DUMPCAP
    TSHARK = toolchain.find_tool('tshark')
    CAPINFOS = toolchain.find_tool('capinfos')
    FFMPEG = toolchain.find_tool('ffmpeg')
    FFPROBE = toolchain.find_tool('ffprobe')
    DUMPCAP = toolchain.find_tool('dumpcap')


TSHARK = None
CAPINFOS = None
FFMPEG = None
FFPROBE = None
DUMPCAP = None
refresh_tools()

TSHARK_TIMEOUT = 1800        # 单次 tshark 超时（秒）
FFMPEG_TIMEOUT = 900
MAX_PACKET_FOR_DETAIL = 5000  # 明细表最多入库多少条（其余仅保留索引）


class CaptureError(RuntimeError):
    """抓包读取失败，消息面向用户可读"""


# ---------------------------------------------------------------
# 文件信息（M01-02）
# ---------------------------------------------------------------
@dataclass
class FileInfo:
    filename: str = ''
    file_size: int = 0
    file_format: str = ''
    checksum: str = ''
    packet_count: int | None = None
    capture_start: datetime | None = None
    capture_end: datetime | None = None
    duration: float | None = None
    link_type: str = ''
    ip_count: int | None = None
    tcp_count: int | None = None
    udp_count: int | None = None
    warnings: list = field(default_factory=list)


def _run(cmd: list[str], timeout: int, what: str) -> subprocess.CompletedProcess:
    try:
        return analysis_control.run(cmd, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), capture_output=True, text=True,
                              errors='replace', timeout=timeout)
    except subprocess.TimeoutExpired:
        raise CaptureError('%s 超时（%d 秒）' % (what, timeout))
    except FileNotFoundError:
        raise CaptureError('找不到程序：%s' % cmd[0])
    except Exception as e:
        raise CaptureError('%s 失败：%s' % (what, e))


def file_checksum(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def inspect_file(path: str) -> FileInfo:
    """提取抓包文件元信息（M01-02）"""
    if not TSHARK:
        raise CaptureError('未找到 tshark，请安装 Wireshark 或将 tshark 加入 PATH')

    info = FileInfo(
        filename=os.path.basename(path),
        file_size=os.path.getsize(path),
        checksum=file_checksum(path),
    )

    # 格式：读文件头魔数
    with open(path, 'rb') as f:
        magic = f.read(4)
    if magic == b'\xd4\xc3\xb2\xa1' or magic == b'\xa1\xb2\xc3\xd4':
        info.file_format = 'pcap'
    elif magic == b'\x0a\x0d\x0d\x0a':
        info.file_format = 'pcapng'
    else:
        info.file_format = 'unknown'
        info.warnings.append('文件头不是标准 pcap/pcapng 魔数，可能不是抓包文件')

    # capinfos 拿整体信息
    capinfos = CAPINFOS
    if not capinfos and TSHARK:
        for name in ('capinfos', 'capinfos.exe'):
            cand = os.path.join(os.path.dirname(TSHARK), name)
            if os.path.isfile(cand):
                capinfos = cand
                break
    if capinfos and os.path.isfile(capinfos):
        # -T -M 输出：第一行是表头，第二行是数据，都用 tab 分隔
        r = _run([capinfos, '-T', '-M', path], 120, 'capinfos')
        if r.returncode == 0:
            kv = _parse_capinfos(r.stdout)
            info.packet_count = _to_int(kv.get('Number of packets'))
            info.duration = _to_float(kv.get('Capture duration (seconds)'))
            info.link_type = kv.get('File encapsulation', '')
            info.capture_start = _parse_time(kv.get('Start time'))
            info.capture_end = _parse_time(kv.get('End time'))
            # capinfos 自己给的校验和可用于交叉核对
            sha = kv.get('SHA256', '')
            if sha and sha != info.checksum:
                info.warnings.append('文件校验和与 capinfos 计算不一致')
        else:
            info.warnings.append('capinfos 读取失败，文件可能损坏')

    # IP / TCP / UDP 计数在报文索引阶段顺带计算，避免重复全量扫描。
    # 这里再跑一次轻量协议分层检查；它只输出协议汇总，不导出每条报文，
    # 用来在完全无法解析时尽早返回可读错误，而不是让索引阶段静默得到空表。
    r = _run([TSHARK, '-r', path, '-q', '-z', 'io,phs'], 300, '协议分层统计')
    if r.returncode != 0:
        raise CaptureError('无法解析该抓包文件：%s' % ((r.stderr or '')[:300]))
    if 'ip' not in (r.stdout or '').lower():
        info.warnings.append('未发现 IP 层流量')

    # 抓包完整性判断
    if info.packet_count is not None and info.packet_count == 0:
        info.warnings.append('文件内没有任何报文')
    if info.duration is not None and info.duration <= 0:
        info.warnings.append('抓包时间跨度异常（可能只有一个报文或时间戳损坏）')

    return info


def _parse_capinfos(stdout: str) -> dict:
    """解析 capinfos -T -M 的 tab 表格：首行表头，次行数据"""
    lines = [ln for ln in stdout.splitlines() if ln.strip()]
    if len(lines) < 2:
        return {}
    header = [h.strip() for h in lines[0].split('\t')]
    values = [v.strip() for v in lines[1].split('\t')]
    return {k: v for k, v in zip(header, values) if k}


def _to_int(s) -> int | None:
    try:
        return int(str(s).strip())
    except (TypeError, ValueError):
        return None


def _to_float(s) -> float | None:
    try:
        return float(str(s).strip())
    except (TypeError, ValueError):
        return None


def _parse_time(s) -> datetime | None:
    if not s:
        return None
    s = str(s).strip()
    for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S',
                '%b %d, %Y %H:%M:%S.%f', '%b %d, %Y %H:%M:%S'):
        try:
            # capinfos 输出不带时区，这里按抓包机本地时间原样保留
            return datetime.strptime(s, fmt)  # noqa: DTZ007
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------
# 报文索引（M02）
# ---------------------------------------------------------------
PACKET_FIELDS = [
    'frame.number', 'frame.time_relative', 'frame.len',
    'ip.src', 'ip.dst', 'ipv6.src', 'ipv6.dst',
    'tcp.srcport', 'tcp.dstport', 'udp.srcport', 'udp.dstport',
    'frame.protocols',
]


def iter_packets(path: str, display_filter: str | None = None,
                 limit: int | None = None):
    """流式产出报文索引，避免一次性载入内存

    yield dict:
      number, ts, src_ip, dst_ip, src_port, dst_port, transport, length, protocols
    """
    if not TSHARK:
        raise CaptureError('未找到 tshark')

    cmd = [TSHARK, '-r', path, '-T', 'fields',
           '-E', 'separator=\x1f', '-E', 'occurrence=f']
    if display_filter:
        cmd += ['-Y', display_filter]
    for f in PACKET_FIELDS:
        cmd += ['-e', f]

    proc = subprocess.Popen(cmd, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, errors='replace', bufsize=1 << 20)
    count = 0
    try:
        with analysis_control.track(proc):
            for line in proc.stdout:
                parts = line.rstrip('\r\n').split('\x1f')
                while len(parts) < len(PACKET_FIELDS):
                    parts.append('')
                (num, ts, ln, ip_src, ip_dst, v6_src, v6_dst,
                 t_sport, t_dport, u_sport, u_dport, protos) = parts[:12]

                if not num:
                    continue
                transport = ''
                if t_sport or t_dport:
                    transport = 'TCP'
                elif u_sport or u_dport:
                    transport = 'UDP'

                def _int(v):
                    try:
                        return int(v)
                    except (TypeError, ValueError):
                        return None

                yield {
                    'number': _int(num),
                    'ts': float(ts) if ts else None,
                    'src_ip': ip_src or v6_src or None,
                    'dst_ip': ip_dst or v6_dst or None,
                    'src_port': _int(t_sport) or _int(u_sport),
                    'dst_port': _int(t_dport) or _int(u_dport),
                    'transport': transport,
                    'length': _int(ln) or 0,
                    'protocols': protos or '',
                }
                count += 1
                if limit and count >= limit:
                    break
    finally:
        try:
            if proc.poll() is None:
                proc.kill()
        except Exception:
            pass
        try:
            err = proc.stderr.read() if proc.stderr else ''
            proc.wait(timeout=10)
        except Exception:
            err = ''
        if proc.returncode not in (0, None) and err:
            raise CaptureError('tshark 读取报文失败：%s' % err.strip()[:400])


# ---------------------------------------------------------------
# 域值抽取（供 SIP / RTP / TCP 流使用）
# ---------------------------------------------------------------
def extract_fields(path: str, fields: list[str], display_filter: str | None = None,
                   separator: str = '\x1f') -> list[list[str]]:
    """按字段抽取，返回二维列表。用于 SIP 头、RTP 头等结构化数据"""
    if not TSHARK:
        raise CaptureError('未找到 tshark')
    cmd = [TSHARK, '-r', path, '-T', 'fields',
           '-E', 'separator=' + separator, '-E', 'occurrence=f']
    if display_filter:
        cmd += ['-Y', display_filter]
    for f in fields:
        cmd += ['-e', f]
    r = _run(cmd, TSHARK_TIMEOUT, '抽取字段')
    if r.returncode != 0:
        return []
    rows = []
    for line in r.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split(separator)
        while len(parts) < len(fields):
            parts.append('')
        rows.append(parts[:len(fields)])
    return rows


# ---------------------------------------------------------------
# RTP 抽取（自研，不依赖 tshark 的 rtp 解码器）
# ---------------------------------------------------------------
def dump_tcp_segments(path: str) -> dict:
    """导出 TCP 负载段，按「stream + 方向」聚合

    返回 {key: {segs: {seq: bytes}, meta: {...}, t0, t1}}
    key 形如 ``"3:10.0.0.1:5060->10.0.0.2:5060"``。

    一个 tcp.stream 天然是双向的，两个方向各有独立的 seq 空间。
    混在一起按 seq 排序时，反向数据会被判成"空洞"，reassemble_tcp
    会补出几百 KB 的零字节，RFC4571 随之错位。这里按方向拆开，
    并顺手记录该方向负载段的起止时间，调用方不必再跑一次 tshark。
    """
    if not TSHARK:
        raise CaptureError('未找到 tshark')
    rows = extract_fields(path, [
        'tcp.stream', 'tcp.seq_raw', 'tcp.time_relative',
        'ip.src', 'tcp.srcport', 'ip.dst', 'tcp.dstport', 'tcp.payload'
    ], 'tcp.len>0')
    streams: dict = {}
    for r in rows:
        sid, seq_s, ts_s, sip, sport, dip, dport, hexpay = (r + [''] * 8)[:8]
        if not hexpay or not seq_s:
            continue
        try:
            seq = int(seq_s)
            data = bytes.fromhex(re.sub(r'[^0-9a-fA-F]', '', hexpay))
            ts = float(ts_s) if ts_s else 0.0
        except (ValueError, TypeError):
            continue
        if not data:
            continue
        key = '%s:%s:%s->%s:%s' % (sid, sip, sport, dip, dport)
        entry = streams.setdefault(key, {
            'segs': {}, 'meta': {}, 't0': None, 't1': None
        })
        entry['segs'][seq] = data
        entry['t0'] = ts if entry['t0'] is None else min(entry['t0'], ts)
        entry['t1'] = ts if entry['t1'] is None else max(entry['t1'], ts)
        if not entry['meta']:
            entry['meta'] = {
                'ts': ts,
                'stream_id': sid,
                'src_ip': sip, 'src_port': int(sport) if sport else None,
                'dst_ip': dip, 'dst_port': int(dport) if dport else None,
            }
    return streams


def extract_udp_rtp(path: str) -> list:
    """抽取 UDP 承载的 RTP（一个数据报就是一个 RTP 包）"""
    if not TSHARK:
        raise CaptureError('未找到 tshark')
    rows = extract_fields(path, [
        'frame.number', 'frame.time_relative',
        'ip.src', 'udp.srcport', 'ip.dst', 'udp.dstport', 'udp.payload'
    ], 'udp.length>20')
    out = []
    for r in rows:
        try:
            payload = bytes.fromhex(re.sub(r'[^0-9a-fA-F]', '', r[6]))
        except (ValueError, TypeError):
            continue
        if len(payload) < 12 or (payload[0] >> 6) != 2:
            continue
        out.append({
            'frame': int(r[0]) if r[0] else 0,
            'ts': float(r[1]) if r[1] else 0.0,
            'src_ip': r[2], 'src_port': int(r[3]) if r[3] else None,
            'dst_ip': r[4], 'dst_port': int(r[5]) if r[5] else None,
            'payload': payload,
        })
    return out


def extract_raw_packet(path: str, number: int) -> bytes | None:
    """按报文号取原始字节（M12 十六进制视图）"""
    if not TSHARK:
        raise CaptureError('未找到 tshark')
    # -x 输出完整帧；不再先跑一次 fields 查询（结果未使用，纯浪费）
    r2 = _run([TSHARK, '-r', path, '-Y', 'frame.number==%d' % number,
               '-x'], 120, '读取报文十六进制')
    if r2.returncode != 0:
        return None
    # -x 输出形如：
    # 0000  00 11 22 ...   ....
    chunks = []
    for line in r2.stdout.splitlines():
        m = line.strip()
        if not m or ':' in m.split(' ')[0] if m else True:
            continue
        # 跳过非数据行
        parts = m.split()
        if not parts or len(parts[0]) != 4:
            continue
        try:
            int(parts[0], 16)
        except ValueError:
            continue
        hexbytes = []
        for p in parts[1:]:
            if len(p) == 2:
                try:
                    int(p, 16)
                    hexbytes.append(p)
                except ValueError:
                    break
            else:
                break
        if hexbytes:
            chunks.append(''.join(hexbytes))
    if not chunks:
        return None
    try:
        return bytes.fromhex(''.join(chunks))
    except ValueError:
        return None
