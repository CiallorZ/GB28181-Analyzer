#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
诊断规则引擎（M09）

严格遵循 PRD：
- 每条诊断必须能追溯到报文或计算数据
- 必须区分 confirmed / suspected / insufficient
- 不能把"没抓到"说成"没发生"
- 规则 ID 稳定可引用
"""
from __future__ import annotations

from dataclasses import dataclass, field

# 严重级别
CRITICAL = 'critical'
WARNING = 'warning'
INFO = 'info'
UNKNOWN = 'unknown'

# 证据等级
CONFIRMED = 'confirmed'
SUSPECTED = 'suspected'
INSUFFICIENT = 'insufficient'


@dataclass
class Diagnostic:
    rule_id: str
    severity: str
    evidence_level: str
    title: str
    description: str = ''

    session_id: int | None = None
    stream_id: int | None = None
    device_id: str = ''
    timestamp: float | None = None

    evidence: dict = field(default_factory=dict)
    possible_causes: list = field(default_factory=list)
    recommendations: list = field(default_factory=list)
    related_packet_ids: list = field(default_factory=list)


# ---------------------------------------------------------------
# 规则定义（便于后续配置化）
# ---------------------------------------------------------------
RULES = {
    'SIP-001': 'INVITE 超时无响应',
    'SIP-002': 'REGISTER 超时无响应',
    'SIP-003': 'SIP 失败响应',
    'SIP-004': 'SIP 异常重传',
    'SIP-005': '请求与响应无法关联',
    'SIP-006': 'SIP 消息结构异常',
    'SIP-007': '会话非正常结束',
    'SIP-008': 'BYE 未收到最终响应',
    'SDP-001': 'SDP 媒体地址异常',
    'SDP-002': 'SDP 协商与实际媒体不匹配',
    'SDP-003': 'SSRC 不一致',
    'SDP-004': 'SDP 结构异常',
    'MED-001': '信令成功但未发现 RTP',
    'MED-002': 'RTP 序号缺口',
    'MED-003': 'RTP 抖动异常',
    'MED-004': '媒体长时间静默',
    'MED-005': 'RTP 时间戳异常',
    'MED-006': '媒体码率异常下降',
    'MED-007': 'BYE 后仍有媒体传输',
    'MED-008': '抓到 RTP 但无法解码',
    'CAP-001': '抓包不完整',
}

# 已接入检测逻辑的规则。清单里其余条目是规划中的规则，
# 界面与文档必须明确区分，避免用户以为"没报错 = 没问题"。
# 新增规则时同步更新；tests/test_rule_catalog.py 会对照源码校验。
RULE_IMPLEMENTED = frozenset({
    'SIP-001', 'SIP-003', 'SIP-008',
    'SDP-003',
    'MED-001', 'MED-002', 'MED-003', 'MED-004', 'MED-005',
    'MED-007', 'MED-008',
    'CAP-001',
})


def rule_catalog() -> list[dict]:
    """规则清单（带实现状态），供 /api/rules 与前端展示"""
    return [{'id': k, 'name': v, 'implemented': k in RULE_IMPLEMENTED}
            for k, v in RULES.items()]


# ---------------------------------------------------------------
# 各规则的检测逻辑
# ---------------------------------------------------------------
def severity_order_clause(column):
    """SQL 层的严重级别排序：critical > warning > info > unknown

    SQLite/PostgreSQL 都会按枚举名称（CRITICAL/INFO/WARNING）的字母序排序，
    直接 order_by(severity) 会把 WARNING 排到 INFO 后面；诊断列表必须在
    SQL 里排好序再分页，否则第一页可能看不到 critical。
    """
    from sqlalchemy import case

    from ..models.entities import DiagnosticSeverity

    return case(
        (column == DiagnosticSeverity.CRITICAL, 0),
        (column == DiagnosticSeverity.WARNING, 1),
        (column == DiagnosticSeverity.INFO, 2),
        else_=9,
    )


def diagnose(task_data: dict) -> list[Diagnostic]:
    """对一次分析任务做全量诊断

    task_data 结构：
      sessions : [SessionInfo-like dict]
      streams  : [StreamStat-like dict]
      messages : [SipInfo-like dict]
      packets  : [packet dict]
      limits   : [capture limitation dict]
    """
    out: list[Diagnostic] = []
    sessions = task_data.get('sessions') or []
    streams = task_data.get('streams') or []
    messages = task_data.get('messages') or []

    # 建索引：会话 ID -> 其媒体流
    stream_by_session = {}
    for s in streams:
        sid = s.get('session_id')
        if sid is not None:
            stream_by_session.setdefault(sid, []).append(s)

    # ---- 信令层规则 ----
    out += _check_signal(sessions, messages)

    # ---- SDP 层规则 ----
    out += _check_sdp(sessions)

    # ---- 媒体层规则 ----
    out += _check_media(sessions, streams, stream_by_session)
    out += _check_bye_media(sessions, streams)

    # ---- 抓包局限 ----
    out += _check_capture_limits(task_data)

    out.sort(key=lambda d: (_severity_rank(d.severity),
                            d.timestamp if d.timestamp is not None else 0))
    return out


def _severity_rank(s: str) -> int:
    return {CRITICAL: 0, WARNING: 1, INFO: 2, UNKNOWN: 3}.get(s, 4)


def _packets_of(messages: list, call_ids: list, predicate, limit: int = 5
                ) -> list[int]:
    """取满足条件的报文号，用于 related_packet_ids"""
    wanted = set(c for c in call_ids if c)
    ids = []
    for m in messages:
        if m.get('call_id') not in wanted:
            continue
        if predicate(m) and m.get('packet_number'):
            ids.append(m['packet_number'])
            if len(ids) >= limit:
                break
    return ids


def _check_signal(sessions: list, messages: list) -> list[Diagnostic]:
    out = []
    for s in sessions:
        sid = s.get('id')
        dev = s.get('device_id') or ''
        signal_status = s.get('signal_status')
        call_ids = s.get('call_ids') or []

        # SIP-001 INVITE 无最终响应
        if signal_status == 'incomplete':
            out.append(Diagnostic(
                rule_id='SIP-001',
                severity=CRITICAL,
                evidence_level=SUSPECTED,
                title='INVITE 未收到最终响应',
                description=('设备 %s 的 INVITE 请求没有收到 2xx/3xx-6xx 最终响应，'
                             '只观察到临时响应或完全没有响应。'
                             '可能原因：下级未处理、信令路径不通、或抓包未覆盖响应方向。'
                             % (dev or '未知')),
                session_id=sid, device_id=dev,
                timestamp=s.get('start_time'),
                evidence={'signal_status': signal_status,
                          'call_ids': call_ids[:3]},
                related_packet_ids=_packets_of(
                    messages, call_ids,
                    lambda m: m.get('is_request') and m.get('method') == 'INVITE',
                    limit=3),
                possible_causes=['对端未响应 INVITE',
                                 '信令经过的节点不通',
                                 '抓包点只捕获了单向信令'],
                recommendations=['在对端侧同时抓包，确认 INVITE 是否到达',
                                 '检查 SIP 端口连通性',
                                 '确认对端平台是否在线'],
            ))

        # SIP-003 失败响应
        if signal_status == 'failed':
            code = s.get('final_code')
            out.append(Diagnostic(
                rule_id='SIP-003',
                severity=CRITICAL,
                evidence_level=CONFIRMED,
                title='点播被拒绝（SIP %s）' % (code or '错误响应'),
                description=('设备 %s 的 INVITE 返回 %s，点播未建立。'
                             % (dev or '未知', code or '非 2xx 响应')),
                session_id=sid, device_id=dev,
                timestamp=s.get('start_time'),
                evidence={'final_code': code},
                related_packet_ids=_packets_of(
                    messages, call_ids,
                    lambda m: (
                        not m.get('is_request') and m.get('status_code')
                        and (m['status_code'] == code if code
                             else m['status_code'] >= 300)),
                    limit=3),
                possible_causes=['设备不在目录中或通道不存在',
                                 '权限/鉴权拒绝',
                                 '设备离线',
                                 '资源不足'],
                recommendations=['核对该设备/通道是否在下级目录中',
                                 '检查上级点播的通道 ID 是否正确',
                                 '查看对端返回的错误原因短语'],
            ))

        # SIP-008 BYE 无最终响应
        if s.get('end_reason') == 'abnormal':
            out.append(Diagnostic(
                rule_id='SIP-008',
                severity=WARNING,
                evidence_level=CONFIRMED,
                title='BYE 未收到最终响应',
                description=('会话 %s 发出 BYE 后未收到 2xx 响应，'
                             'SIP 事务未正常终止，发送方会持续重传直到超时。'
                             % (dev or '未知')),
                session_id=sid, device_id=dev,
                timestamp=s.get('end_time'),
                evidence={'bye_time': s.get('end_time')},
                related_packet_ids=_packets_of(
                    messages, call_ids,
                    lambda m: m.get('is_request') and m.get('method') == 'BYE',
                    limit=3),
                possible_causes=['对端 SIP 栈事务处理不完整',
                                 'BYE 的响应方向未被抓包'],
                recommendations=['要求对端修复 BYE 事务响应',
                                 '检查是否只是抓包未覆盖响应方向'],
            ))
    return out


def _check_bye_media(sessions: list, streams: list) -> list[Diagnostic]:
    """MED-007：BYE 之后仍有媒体传输

    这是资源未释放的信号：会话已结束但设备仍在推流，
    会持续占用带宽与端口，长期可能导致端口耗尽。
    """
    out = []
    for s in sessions:
        sid = s.get('id')
        end = s.get('end_time')
        # 只要有明确的 BYE 时间点就检查，不限定 end_reason
        # （abnormal 只代表 BYE 没收到响应，BYE 本身仍已发出）
        if end is None:
            continue
        # 找该会话关联的流中，起始时间晚于 BYE 的
        for st in streams:
            if st.get('session_id') != sid:
                continue
            st_start = st.get('start_time')
            if st_start is None or st_start <= end + 0.5:
                continue
            out.append(Diagnostic(
                rule_id='MED-007',
                severity=WARNING,
                evidence_level=SUSPECTED,
                title='BYE 后仍有媒体传输',
                description=('会话 %s 在 %.3fs 已发出 BYE，'
                             '但流 SSRC=%08x 从 %.3fs 才开始传输（晚 %.3f 秒）。'
                             '两种可能：设备未按信令停止推流，'
                             '或该流实际属于另一次点播（关联需人工确认）。'
                             % (s.get('device_id') or '未知', end,
                                st.get('ssrc') or 0, st_start,
                                st_start - end)),
                session_id=sid, stream_id=st.get('id'),
                device_id=s.get('device_id') or '',
                timestamp=st_start,
                evidence={'bye_time': end, 'media_start': st_start,
                          'delay': round(st_start - end, 3),
                          'ssrc': '%08x' % (st.get('ssrc') or 0),
                          'packet_count': st.get('packet_count'),
                          'note': '仅凭时间关系无法区分"残留推流"与"另一轮会话"'},
                possible_causes=[
                    '设备未正确处理 BYE，停止推流有延迟',
                    '端口未及时释放，残留连接继续传输',
                    '该媒体流实际属于另一轮会话（关联可能误判）',
                    '抓包点存在缓冲，导致媒体包时间戳偏后',
                ],
                recommendations=[
                    '确认该 SSRC 是否在其他会话中出现',
                    '核对设备侧会话释放日志',
                    '在设备侧同时抓包对比时间关系',
                ],
            ))
    return out


def _check_sdp(sessions: list) -> list[Diagnostic]:
    out = []
    for s in sessions:
        sid = s.get('id')
        dev = s.get('device_id') or ''

        # SDP-003 SSRC 不一致
        subj = (s.get('subject_ssrc') or '').strip()
        sdp_ssrc = (s.get('sdp_ssrc') or '').strip()
        if subj and sdp_ssrc:
            a = subj.lstrip('0').lower()
            b = sdp_ssrc.lstrip('0').lower()
            if a != b:
                out.append(Diagnostic(
                    rule_id='SDP-003',
                    severity=WARNING,
                    evidence_level=CONFIRMED,
                    title='SSRC 不一致',
                    description=('设备 %s 的 Subject 中 SSRC 为 %s，'
                                 '而 SDP 的 y= 字段为 %s。'
                                 '两者不一致时，按 Subject 匹配 PS 流的播放器可能无法定位码流。'
                                 % (dev or '未知', subj, sdp_ssrc)),
                    session_id=sid, device_id=dev,
                    timestamp=s.get('start_time'),
                    evidence={'subject_ssrc': subj, 'sdp_ssrc': sdp_ssrc},
                    possible_causes=['设备厂商未统一 SSRC 生成规则',
                                     'Subject 与 SDP 由不同模块填充'],
                    recommendations=['要求厂商在 Subject 与 SDP y= 中填同一 SSRC',
                                     '或确认播放器以哪个字段为准'],
                ))

        # SDP-002 协商端口与实际媒体不匹配
        if s.get('media_status') == 'no_media' and s.get('signal_status') == 'success':
            out.append(Diagnostic(
                rule_id='MED-001',
                severity=CRITICAL,
                evidence_level=SUSPECTED,
                title='信令成功但未发现 RTP 媒体',
                description=('设备 %s 的 INVITE 已收到 200 OK 并完成 ACK，'
                             '但抓包中没有任何对应的 RTP 包。'
                             'SDP 协商的是 %s:%s（%s）。'
                             % (dev or '未知',
                                s.get('negotiated_ip') or '?',
                                s.get('negotiated_port') or '?',
                                s.get('negotiated_transport') or '?')),
                session_id=sid, device_id=dev,
                timestamp=s.get('start_time'),
                evidence={
                    'negotiated_ip': s.get('negotiated_ip'),
                    'negotiated_port': s.get('negotiated_port'),
                    'transport': s.get('negotiated_transport'),
                    'first_media_latency': s.get('first_media_latency'),
                },
                possible_causes=[
                    '媒体端口（如 TCP 8808）未被 NAT/防火墙放通',
                    '被点播的通道不存在，对端盲回 200 OK',
                    '媒体流不经过当前抓包点',
                    '设备主动连接受阻（setup=active 时由设备回连）',
                ],
                recommendations=[
                    '确认协商端口在抓包点两侧都可连通',
                    '核对被点播通道是否真实存在于下级目录',
                    '在媒体路径上补抓包',
                ],
            ))
    return out


def _check_media(sessions: list, streams: list, by_session: dict) -> list[Diagnostic]:
    out = []
    for st in streams:
        sid = st.get('session_id')
        dev = ''
        for s in sessions:
            if s.get('id') == sid:
                dev = s.get('device_id') or ''
                break
        st_id = st.get('id') or id(st)

        # MED-002 序号缺口
        gap_pkts = st.get('seq_gap_packets') or 0
        total = st.get('packet_count') or 0
        if gap_pkts > 0 and total > 0:
            ratio = gap_pkts / (total + gap_pkts)
            # TCP 承载时降低等级
            is_tcp = st.get('transport') == 'TCP'
            if is_tcp:
                sev, ev = INFO, INSUFFICIENT
                desc = ('流 SSRC=%08x 存在 %d 个序号缺口（共 %d 包）。'
                        'TCP 承载时缺口通常来自抓包不完整，不能直接判定为网络丢包。'
                        % (st.get('ssrc') or 0, gap_pkts, total))
            else:
                sev = CRITICAL if ratio > 0.02 else WARNING
                ev = CONFIRMED if ratio > 0.01 else SUSPECTED
                desc = ('流 SSRC=%08x 观察到 %d 个序号缺口，涉及 %d 个缺失包'
                        '（占比 %.2f%%，总包 %d）。'
                        % (st.get('ssrc') or 0, st.get('seq_gap_count') or 0,
                           gap_pkts, ratio * 100, total))
            out.append(Diagnostic(
                rule_id='MED-002',
                severity=sev, evidence_level=ev,
                title='RTP 序号缺口',
                description=desc,
                session_id=sid, stream_id=st_id, device_id=dev,
                timestamp=st.get('start_time'),
                related_packet_ids=[
                    e['packet'] for e in (st.get('seq_gap_events') or [])
                    if e.get('packet')][:10],
                evidence={
                    'ssrc': '%08x' % (st.get('ssrc') or 0),
                    'gap_count': st.get('seq_gap_count'),
                    'gap_packets': gap_pkts,
                    'packet_count': total,
                    'transport': st.get('transport'),
                    'loss_confidence': st.get('loss_confidence'),
                    'first_gaps': (st.get('seq_gap_events') or [])[:5],
                },
                possible_causes=(['抓包点丢包或抓包缓冲区不足'] if is_tcp else
                                 ['网络丢包', '设备发送抖动', '抓包缓冲区不足']),
                recommendations=['对比发送端计数确认是否真丢',
                                 '检查中间网络质量',
                                 '在发送端与接收端同时抓包对比'],
            ))

        # MED-003 抖动异常
        j = st.get('jitter_avg')
        if j is not None and j > 50:      # 50ms
            out.append(Diagnostic(
                rule_id='MED-003',
                severity=WARNING if j < 200 else CRITICAL,
                evidence_level=CONFIRMED,
                title='RTP 抖动偏高',
                description=('流 SSRC=%08x 平均抖动 %.1fms，峰值 %.1fms，'
                             '可能影响播放流畅度。'
                             % (st.get('ssrc') or 0, j, st.get('jitter_max') or 0)),
                session_id=sid, stream_id=st_id, device_id=dev,
                timestamp=st.get('start_time'),
                evidence={'jitter_avg_ms': j, 'jitter_max_ms': st.get('jitter_max')},
                possible_causes=['网络拥塞', '链路带宽不足', '设备输出不稳定'],
                recommendations=['检查链路带宽与 QoS 配置',
                                 '观察抖动是否与丢包同时出现'],
            ))

        # MED-004 长时间静默
        gap = st.get('max_gap')
        if gap is not None and gap > 3:
            out.append(Diagnostic(
                rule_id='MED-004',
                severity=WARNING,
                evidence_level=CONFIRMED,
                title='媒体长时间静默',
                description=('流 SSRC=%08x 出现最长 %.2f 秒无媒体包的间隔，'
                             '共 %d 次超过 0.5 秒的中断。'
                             % (st.get('ssrc') or 0, gap,
                                st.get('interruption_count') or 0)),
                session_id=sid, stream_id=st_id, device_id=dev,
                timestamp=st.get('start_time'),
                evidence={'max_gap_seconds': gap,
                          'interruption_count': st.get('interruption_count')},
                possible_causes=['网络中断', '设备停止推流', '抓包点切换'],
                recommendations=['确认静默期间链路是否中断',
                                 '核对设备侧是否在此时段重启'],
            ))

        # MED-005 时间戳异常
        ts_anom = st.get('ts_anomalies') or []
        if ts_anom:
            kinds = {}
            for a in ts_anom:
                kinds[a['type']] = kinds.get(a['type'], 0) + 1
            # 回绕本身正常，只有倒退/跳变才报
            real = {k: v for k, v in kinds.items() if k != 'wrap'}
            if real:
                out.append(Diagnostic(
                    rule_id='MED-005',
                    severity=WARNING,
                    evidence_level=CONFIRMED,
                    title='RTP 时间戳异常',
                    description=('流 SSRC=%08x 检测到时间戳异常：%s。'
                                 '时间戳不连续会导致播放器时间轴错乱。'
                                 % (st.get('ssrc') or 0,
                                    '，'.join('%s %d 次' % (k, v)
                                             for k, v in real.items()))),
                    session_id=sid, stream_id=st_id, device_id=dev,
                    timestamp=st.get('start_time'),
                    evidence={'anomalies': ts_anom[:10], 'kinds': real},
                    possible_causes=['设备时基错误',
                                     '音视频共用同一 SSRC 但时间戳基准不同',
                                     '封装模块实现缺陷'],
                    recommendations=['要求设备厂商检查 RTP 时间戳生成逻辑',
                                     '确认音视频是否共用 SSRC'],
                ))

        # MED-008 抓到 RTP 但解不出画面
        # 注意：P0 版本只做 RTP 层统计，未实现 PS/ES 解封装与视频解码，
        # 此时 has_video 恒为 False 属于能力边界，不是故障。
        # 只有明确尝试过重建且失败（rebuild_error 非空）才报此规则。
        if st.get('rebuild_error'):
            out.append(Diagnostic(
                rule_id='MED-008',
                severity=WARNING,
                evidence_level=SUSPECTED,
                title='抓到 RTP 但视频重建失败',
                description=('流 SSRC=%08x 共 %d 个包，重建出的码流无法被解码器接受；'
                             '具体错误见下方证据。'
                             % (st.get('ssrc') or 0,
                                st.get('packet_count') or 0)),
                session_id=sid, stream_id=st_id, device_id=dev,
                timestamp=st.get('start_time'),
                evidence={'packet_count': st.get('packet_count'),
                          'rebuild_error': st.get('rebuild_error')},
                possible_causes=['抓包起点在 GOP 中间，缺少 SPS/PPS',
                                 'PS 封装不规范',
                                 '使用了不支持的编码格式'],
                recommendations=['从关键帧位置重新抓包',
                                 '检查 PS 封装的参数集是否完整'],
            ))
    return out


def _check_capture_limits(task_data: dict) -> list[Diagnostic]:
    out = []
    for lim in (task_data.get('limits') or []):
        out.append(Diagnostic(
            rule_id='CAP-001',
            severity=UNKNOWN if lim.get('level') == 'info' else WARNING,
            evidence_level=INSUFFICIENT,
            title=lim.get('message', '抓包局限')[:80],
            description=lim.get('message', ''),
            evidence={'code': lim.get('code')},
            possible_causes=['抓包点选择、抓包时长或过滤条件导致'],
            recommendations=['在信令与媒体都经过的节点补抓包'],
        ))
    return out
