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

from collections import defaultdict
from dataclasses import dataclass, field
from ipaddress import ip_address
from statistics import median

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
    'SIP-008': 'BYE 结束异常',
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
    'MED-009': 'RTCP 报告对端丢包偏高',
    'MED-010': '关键帧间隔异常',
    'CAP-001': '抓包不完整',
}

RULE_IMPLEMENTED = frozenset(RULES)


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

    out.extend(_observations(sessions, streams, messages, task_data.get('capture_end')))

    out.sort(key=lambda d: (_severity_rank(d.severity),
                            d.timestamp if d.timestamp is not None else 0))
    return out


def _severity_rank(s: str) -> int:
    return {CRITICAL: 0, WARNING: 1, INFO: 2, UNKNOWN: 3}.get(s, 4)


# ---------------------------------------------------------------
# 一句话结论（纯本地规则，不调用 AI）
# ---------------------------------------------------------------
_EVIDENCE_RANK = {CONFIRMED: 0, SUSPECTED: 1, INSUFFICIENT: 2}

#  headlines 中用于"优先核对/复核"的短焦点，避免把整条 description 塞进来。
_VERDICT_FOCUS = {
    'SIP-001': 'INVITE 是否收到最终响应',
    'SIP-002': 'REGISTER 是否收到响应',
    'SIP-003': 'SIP 失败响应与业务结果',
    'SIP-005': '请求与响应是否同属一个事务',
    'SDP-001': 'SDP 媒体地址配置',
    'SDP-002': 'SDP 与实际媒体地址',
    'MED-001': '媒体链路是否真正建立',
    'MED-002': 'RTP 序号缺口与丢包位置',
    'MED-009': '下游链路与接收端丢包',
    'CAP-001': '抓包范围与过滤条件',
}

_VERDICT_GENERIC_ACTION = {
    'healthy': '保留本次抓包作为基线，无需额外处置',
    'observation': '补充覆盖信令与媒体路径的抓包后再复核',
    'attention': '按诊断证据逐项核对关联报文与端点',
    'blocked': '优先处理已确认阻断项并复测业务',
}


def _verdict_field(obj, key: str, default=None):
    """同时兼容 Diagnostic dataclass、ORM 行与 dict。"""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _verdict_rank(d):
    """严重级别优先，同级按证据强度；rule_id/title 只做稳定排序用。"""
    return (
        _severity_rank(str(_verdict_field(d, 'severity') or '')),
        _EVIDENCE_RANK.get(str(_verdict_field(d, 'evidence_level') or ''), 3),
        str(_verdict_field(d, 'rule_id') or ''),
        str(_verdict_field(d, 'title') or ''),
    )


def build_verdict(diagnostics, sessions, streams, stats, limits) -> dict:
    """从已有诊断生成一个一眼可读的结论。

    严格保守：
    - 只有 critical + confirmed 才判为 blocked；
    - 只有 suspected/insufficient 时 headline 一定带"疑似/需复核"；
    - 有 warning/critical 时绝不输出"无问题"；
    - 存在抓包局限（CAP-001 或 limits）时明确声明结论仅反映抓包点。
    纯规则计算，不使用 AI，也不修改传入数据。
    """
    items = [d for d in (diagnostics or []) if d is not None]
    capture_limited = bool(limits) or any(
        _verdict_field(d, 'rule_id') == 'CAP-001' for d in items)
    empty_capture = isinstance(stats, dict) and stats.get('count') == 0

    problems = [d for d in items
                if _severity_rank(str(_verdict_field(d, 'severity') or ''))
                <= _severity_rank(WARNING)]
    confirmed_problems = [d for d in problems
                          if _verdict_field(d, 'evidence_level') == CONFIRMED]
    hard_blocker = any(
        _verdict_field(d, 'severity') == CRITICAL
        and _verdict_field(d, 'evidence_level') == CONFIRMED
        for d in items)

    if hard_blocker:
        status = 'blocked'
    elif problems:
        status = 'attention'
    elif items or capture_limited or empty_capture:
        status = 'observation'
    else:
        status = 'healthy'

    # 排序：严重级别 -> 证据强度 -> rule_id/title（确定性）。
    leads = sorted(items, key=_verdict_rank)[:3]
    best = min((_EVIDENCE_RANK.get(
        str(_verdict_field(d, 'evidence_level') or ''), 3) for d in leads),
        default=3)
    confidence = {0: CONFIRMED, 1: SUSPECTED, 2: INSUFFICIENT}.get(
        best, INSUFFICIENT)
    lead_rule_ids = [str(_verdict_field(d, 'rule_id'))
                     for d in leads if _verdict_field(d, 'rule_id')]

    top_evidence = str(_verdict_field(leads[0], 'evidence_level') or '') if leads else ''
    needs_caution = (confidence != CONFIRMED
                     or (status != 'healthy' and top_evidence != CONFIRMED))

    lead_rule = lead_rule_ids[0] if lead_rule_ids else ''
    if status == 'healthy':
        headline = '本次抓包未发现可确认的问题'
    elif empty_capture and not problems:
        headline = '抓包中没有可分析的报文，无法判断业务状态'
    elif status == 'observation':
        headline = '仅有观察项或证据不足，暂不能判定根因'
    elif lead_rule == 'MED-001':
        headline = '点播未建立媒体链路：信令成功但抓包点未捕获 RTP'
        if needs_caution:
            headline += '，仍需复核媒体路径'
    else:
        title = str(_verdict_field(leads[0], 'title') or '') if leads else ''
        focus = _VERDICT_FOCUS.get(lead_rule) or RULES.get(lead_rule) or title or '诊断证据'
        if status == 'attention' and needs_caution:
            headline = '存在疑似问题，优先复核 %s' % focus
        elif status == 'blocked' and needs_caution:
            headline = '疑似 %s，需复核后再处置' % focus
        else:
            count = max(len(confirmed_problems), 1)
            headline = '发现 %d 项已确认问题，优先核对 %s' % (count, focus)

    if capture_limited:
        headline += '，结论仅反映抓包点'

    actions: list[str] = []
    for d in leads:
        for rec in (_verdict_field(d, 'recommendations') or []):
            if not isinstance(rec, str):
                continue
            text = rec.strip()
            if text and text not in actions:
                actions.append(text)
                if len(actions) == 3:
                    break
        if len(actions) == 3:
            break
    if not actions:
        if status == 'observation' and capture_limited:
            actions = ['在信令与媒体都经过的节点补抓包后再复核']
        else:
            actions = [_VERDICT_GENERIC_ACTION[status]]

    return {
        'status': status,
        'headline': headline,
        'confidence': confidence,
        'lead_rule_ids': lead_rule_ids,
        'actions': actions,
    }


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

        if s.get('end_reason') == 'abnormal':
            def bye_key(m):
                return m.get('call_id'), m.get('cseq_number'), m.get('via_branch')

            requests = {
                bye_key(m) for m in messages
                if m.get('call_id') in call_ids and m.get('method') == 'BYE'
                and m.get('is_request') and m.get('cseq_number') is not None
                and m.get('via_branch')
            }
            failure = next((
                m for m in messages if m.get('method') == 'BYE'
                and not m.get('is_request') and 300 <= (m.get('status_code') or 0) <= 699
                and bye_key(m) in requests
            ), None)
            code = failure['status_code'] if failure else None
            packets = _packets_of(
                messages, call_ids,
                lambda m: m.get('is_request') and m.get('method') == 'BYE'
                and (failure is None or bye_key(m) == bye_key(failure)),
                limit=3)
            if failure and failure.get('packet_number'):
                packets.append(failure['packet_number'])
            out.append(Diagnostic(
                rule_id='SIP-008',
                severity=WARNING,
                evidence_level=CONFIRMED,
                title='BYE 返回 SIP %d' % code if code else '未观察到 BYE 最终响应',
                description=('抓包中观察到匹配的 BYE 失败响应 SIP %d。' % code
                             if code else '抓包中未观察到匹配的 BYE 最终响应，'
                             '请核对抓包时间范围和响应方向。'),
                session_id=sid, device_id=dev,
                timestamp=s.get('end_time'),
                evidence={'bye_time': s.get('end_time'), 'bye_response_code': code},
                related_packet_ids=packets,
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


def _parse_ssrc(raw: str) -> int | None:
    """把 SSRC 文本归一化成整数

    国标里 SSRC 的写法不统一：
      - 十进制：`0600001869`（前导 0 是定宽填充，不是八进制）→ 600001869
      - 十六进制：`0x23C34D4D` / `23C34D4D`
    比较前必须归一化，否则十进制与十六进制会被误判为"不一致"。
    """
    if not raw:
        return None
    t = raw.strip()
    if t.lower().startswith('0x'):
        try:
            return int(t, 16)
        except ValueError:
            return None
    if t.isdigit():
        try:
            return int(t, 10)
        except ValueError:
            return None
    try:
        return int(t, 16)
    except ValueError:
        return None


def _ssrc_pair_equal(a: str, b: str) -> bool:
    """两个 SSRC 文本是否表示同一个值（兼容十进制/十六进制混写）"""
    va, vb = _parse_ssrc(a), _parse_ssrc(b)
    if va is not None and vb is not None:
        return va == vb
    # 都解析不出来时退回字符串比较，避免漏报
    return a.strip().lower().lstrip('0') == b.strip().lower().lstrip('0')


def _check_sdp(sessions: list) -> list[Diagnostic]:
    out = []
    for s in sessions:
        sid = s.get('id')
        dev = s.get('device_id') or ''

        # SDP-003 SSRC 不一致
        subj = (s.get('subject_ssrc') or '').strip()
        sdp_ssrc = (s.get('sdp_ssrc') or '').strip()
        if subj and sdp_ssrc:
            # 两个字段可能是十进制也可能是十六进制，不能直接字符串比
            if not _ssrc_pair_equal(subj, sdp_ssrc):
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
                    related_packet_ids=list(dict.fromkeys(
                        s[key] for key in ('subject_packet', 'sdp_ssrc_packet') if s.get(key)
                    )),
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
                description=('设备 %s 的 INVITE 已收到成功最终响应，'
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
        # RTCP 接收报告是接收端自己统计的丢包，证据强度高于本端按序号
        # 缺口推断。两者都存在时以 RTCP 为准，并明确写出差异。
        rtcp = st.get('rtcp') or {}
        peer_loss = rtcp.get('fraction_lost_latest')
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
            if peer_loss is not None:
                peer_avg = rtcp.get('fraction_lost_avg')
                desc += (' 对端 RTCP 接收报告最近一次区间丢包率为 %.2f%%'
                         '（累计丢失 %s 包），可作为交叉验证。'
                         % (peer_loss, rtcp.get('cumulative_lost_latest')))
                # 只有"最近一次"和"各区间平均"都接近零，才能说对端几乎不丢包。
                # 单看最近一次会被"最后一个区间恰好没丢"骗过去，从而把持续
                # 存在的对端丢包误判成抓包点问题。
                quiet = peer_loss <= 0.01 and (peer_avg is None or peer_avg <= 0.01)
                if quiet and ev != INSUFFICIENT:
                    # 对端报告几乎不丢包，本端缺口更可能来自抓包点。
                    # 只降不升：TCP 流本来就是 INSUFFICIENT，不能因为这条
                    # 交叉证据反而把等级抬上去。
                    ev = SUSPECTED
                    desc += ' 对端报告的丢包接近零，本端缺口更可能来自抓包点而非链路。'
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
                    'rtcp_fraction_lost': peer_loss,
                    'rtcp_cumulative_lost': rtcp.get('cumulative_lost_latest'),
                    'rtcp_rtt_ms': rtcp.get('rtt_ms_latest'),
                },
                possible_causes=(['抓包点丢包或抓包缓冲区不足'] if is_tcp else
                                 ['网络丢包', '设备发送抖动', '抓包缓冲区不足']),
                recommendations=['对比发送端计数确认是否真丢',
                                 '检查中间网络质量',
                                 '在发送端与接收端同时抓包对比'],
            ))

        # MED-009 对端 RTCP 报告丢包偏高
        # 抓包点在本端时，序号缺口只能证明"本端没收到"；对端 RTCP 报告的
        # 丢包才能区分"链路丢"与"抓包点之后丢"。
        peer_avg = rtcp.get('fraction_lost_avg')
        if peer_avg is not None and peer_avg > 1.0 and not gap_pkts:
            out.append(Diagnostic(
                rule_id='MED-009',
                severity=WARNING if peer_avg < 5 else CRITICAL,
                evidence_level=CONFIRMED,
                title='对端 RTCP 报告丢包，但本端未见序号缺口',
                description=('流 SSRC=%08x 的接收端在 RTCP 中报告平均区间丢包率'
                             ' %.2f%%（共 %d 份报告，累计丢失 %s 包），'
                             '而本抓包点未观察到序号缺口。'
                             '丢包很可能发生在抓包点之后的链路或接收端。'
                             % (st.get('ssrc') or 0, peer_avg,
                                rtcp.get('report_count') or 0,
                                rtcp.get('cumulative_lost_latest'))),
                session_id=sid, stream_id=st_id, device_id=dev,
                timestamp=st.get('start_time'),
                evidence={'fraction_lost_avg': peer_avg,
                          'fraction_lost_latest': rtcp.get('fraction_lost_latest'),
                          'cumulative_lost': rtcp.get('cumulative_lost_latest'),
                          'report_count': rtcp.get('report_count'),
                          'rtt_ms': rtcp.get('rtt_ms_latest'),
                          'local_gap_packets': gap_pkts},
                possible_causes=['抓包点之后的下游链路拥塞',
                                 '接收端处理不过来导致丢包',
                                 '接收端统计口径包含非本流数据'],
                recommendations=['在接收端侧补抓包确认丢包位置',
                                 '核对 RTCP 报告对象 SSRC 是否与媒体流一致',
                                 '检查下游链路带宽与队列配置'],
            ))

        # MED-003 抖动异常
        j = st.get('jitter_avg')
        peer_jitter = rtcp.get('peer_jitter_ms')
        if j is not None and j > 50:      # 50ms
            desc = ('流 SSRC=%08x 平均抖动 %.1fms，峰值 %.1fms，'
                    '可能影响播放流畅度。'
                    % (st.get('ssrc') or 0, j, st.get('jitter_max') or 0))
            if peer_jitter is not None:
                desc += (' 对端 RTCP 报告的抖动为 %.1fms，%s。'
                         % (peer_jitter,
                            '与本端一致' if abs(peer_jitter - j) <= max(5, j * 0.5)
                            else '与本端差异较大，抖动可能发生在抓包点之后'))
            out.append(Diagnostic(
                rule_id='MED-003',
                severity=WARNING if j < 200 else CRITICAL,
                evidence_level=CONFIRMED,
                title='RTP 抖动偏高',
                description=desc,
                session_id=sid, stream_id=st_id, device_id=dev,
                timestamp=st.get('start_time'),
                evidence={'jitter_avg_ms': j, 'jitter_max_ms': st.get('jitter_max'),
                          'rtcp_jitter_ms': peer_jitter},
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

        # MED-010 关键帧间隔异常
        # 关键帧间隔由 PS/ES 分析与 RTP 时间戳换算得到，只覆盖取样窗口。
        # 这里的"首帧"是首个可解码帧的近似位置，不是播放器显示时间。
        ps = st.get('ps') or {}
        video = ps.get('video') or {}
        gops = [g for g in (video.get('keyframe_gop_seconds') or [])
                if isinstance(g, (int, float))]
        if len(gops) >= 2 and st.get('has_video', True):
            avg = sum(gops) / len(gops)
            mx = max(gops)
            # 用中位数判断"波动"：平均值会被单个长间隔拉高，反而掩盖异常。
            typical = median(gops)
            unstable = mx > max(typical * 2, typical + 3)
            too_long = avg > 10
            if too_long or unstable:
                first = video.get('first_keyframe_offset')
                desc = ('流 SSRC=%08x 的关键帧间隔平均 %.2f 秒，最大 %.2f 秒'
                        '（共 %d 个间隔，取样窗口内）。'
                        % (st.get('ssrc') or 0, avg, mx, len(gops)))
                if too_long:
                    desc += ' GOP 偏长，点播起播和随机定位会更慢。'
                if unstable:
                    desc += ' 间隔波动明显，可能出现解码卡顿。'
                if first is not None:
                    desc += ' 首个关键帧约在流起点后 %.2f 秒。' % first
                out.append(Diagnostic(
                    rule_id='MED-010',
                    severity=WARNING,
                    evidence_level=CONFIRMED,
                    title='关键帧间隔异常',
                    description=desc,
                    session_id=sid, stream_id=st_id, device_id=dev,
                    timestamp=st.get('start_time'),
                    evidence={'gop_avg_seconds': round(avg, 3),
                              'gop_max_seconds': round(mx, 3),
                              'gop_samples': gops[:20],
                              'first_keyframe_offset': first,
                              'sampled': bool(st.get('ps_sampled'))},
                    possible_causes=['编码器 GOP 配置过长',
                                     '码率控制策略导致关键帧间隔波动',
                                     '设备侧动态调整 I 帧间隔'],
                    recommendations=['核对编码器 GOP / I 帧间隔配置',
                                     '若关注起播速度，可要求设备缩短 GOP',
                                     '关键帧时间只覆盖取样窗口，长流需结合完整抓包确认'],
                ))

        # 仅在实际重建失败且确实观察到视频时报告。
        # 纯音频/RTCP/非视频载荷没有视频可重建，失败不是"视频无法解码"。
        if st.get('rebuild_error') and st.get('has_video', True):
            out.append(Diagnostic(
                rule_id='MED-008',
                severity=WARNING,
                evidence_level=SUSPECTED,
                title='抓到 RTP 但视频重建失败',
                description=('流 SSRC=%08x 共 %d 个包，视频重建未成功；'
                             '请结合错误证据区分工具环境、超时与码流问题。'
                             % (st.get('ssrc') or 0,
                                st.get('packet_count') or 0)),
                session_id=sid, stream_id=st_id, device_id=dev,
                timestamp=st.get('start_time'),
                evidence={'packet_count': st.get('packet_count'),
                          'rebuild_error': st.get('rebuild_error')},
                possible_causes=['FFmpeg 不可用或重建超时',
                                 '抓包起点在 GOP 中间，缺少 SPS/PPS',
                                 'PS 封装不规范',
                                 '使用了不支持的编码格式'],
                recommendations=['先检查重建错误和 FFmpeg 状态',
                                 '从关键帧位置重新抓包',
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


def _observations(sessions, streams, messages, capture_end):
    owners = defaultdict(set)
    for session in sessions:
        for call in session.get('call_ids') or []:
            owners[call].add(session.get('id'))
    requests, responses = defaultdict(list), defaultdict(list)
    for msg in messages:
        call = msg.get('call_id')
        matches = owners.get(call, set())
        common = dict(session_id=next(iter(matches)) if len(matches) == 1 else None,
                      timestamp=msg.get('timestamp'), related_packet_ids=[msg['packet_number']] if msg.get('packet_number') else [])
        if msg.get('parse_errors'):
            yield Diagnostic(rule_id='SIP-006', severity='warning', evidence_level='confirmed',
                             title='SIP 报文解析异常',
                             description='解析器记录了 SIP 首行或头字段错误，可打开关联报文核查原文。', evidence={'errors':msg['parse_errors']}, **common)
        if msg.get('sdp_errors'):
            yield Diagnostic(rule_id='SDP-004', severity='warning', evidence_level='confirmed',
                             title='SDP 描述无法完整解析',
                             description='SDP 文本未通过字段检查，具体字段和解析结果见证据。', evidence={'errors':msg['sdp_errors']}, **common)
        address = (msg.get('sdp_address') or '').split('/')[0]
        if address and (':' in address or all(c in '.0123456789' for c in address)):
            try:
                ip_address(address)
            except ValueError:
                yield Diagnostic(rule_id='SDP-001', severity='warning', evidence_level='confirmed',
                                 title='SDP 连接地址格式无效',
                             description='连接行中的地址字面量无法解析为 IPv4 或 IPv6 地址。', evidence={'address':address}, **common)
        method = msg.get('cseq_method') or msg.get('method')
        key = (call, msg.get('cseq_number'), method, msg.get('via_branch'))
        if all(v is not None and v != '' for v in key):
            (requests if msg.get('is_request') else responses)[key].append(msg)

    for key in dict.fromkeys((*requests, *responses)):
        req, resp = requests.get(key, []), responses.get(key, [])
        source = req or resp
        first = source[0]
        sid = owners.get(key[0], set())
        common = dict(session_id=next(iter(sid)) if len(sid) == 1 else None,
                      timestamp=first.get('timestamp'), related_packet_ids=[m['packet_number'] for m in source[:5] if m.get('packet_number')])
        evidence = dict(call_id=key[0], cseq=key[1], method=key[2], via_branch=key[3], observations=len(source))
        if not req:
            yield Diagnostic(rule_id='SIP-005', severity='info', evidence_level='insufficient',
                             title='抓包中未找到响应对应的请求',
                             description='在本次观察窗口内，未找到 Call-ID、CSeq、方法和 Via 分支均匹配的请求。', evidence=evidence, **common)
        elif key[2] == 'REGISTER' and not resp and capture_end is not None and first.get('timestamp') is not None:
            window = capture_end - first['timestamp']
            if window >= 32:
                yield Diagnostic(rule_id='SIP-002', severity='warning', evidence_level='suspected',
                                 title='REGISTER 后至少 32 秒未观察到响应',
                             description='观察窗口覆盖了请求后的 32 秒，同一事务内未见响应。', evidence={**evidence, 'window_s':window}, **common)
        if key[2] != 'ACK' and len(req) >= 4:
            directions = defaultdict(list)
            for msg in req:
                endpoints = (msg.get('source_ip'), msg.get('source_port'),
                             msg.get('destination_ip'), msg.get('destination_port'))
                if None not in endpoints and all((endpoints[0], endpoints[2])):
                    directions[endpoints].append(msg)
            for endpoints, copies in directions.items():
                if len(copies) >= 4:
                    yield Diagnostic(
                        rule_id='SIP-004', severity=WARNING, evidence_level=SUSPECTED,
                        title='同一 SIP 事务请求出现至少四次',
                        description='同一方向重复观察到事务键相同的请求，可对照帧号核查重传或重复采集。',
                        session_id=common['session_id'], timestamp=copies[0].get('timestamp'),
                        related_packet_ids=[m['packet_number'] for m in copies[:5] if m.get('packet_number')],
                        evidence={**evidence, 'observations': len(copies), 'endpoints': list(endpoints)},
                    )

    by_id = {s.get('id'): s for s in sessions}
    for session in sessions:
        if session.get('end_reason') == 'abnormal':
            yield Diagnostic(rule_id='SIP-007', severity='warning', evidence_level='suspected',
                             title='会话结束事务未正常完成',
                             description='本次抓包观察到 BYE，未观察到对应的成功结束响应。', session_id=session.get('id'),
                             timestamp=session.get('end_time'), evidence={'end_reason':'abnormal', 'call_ids':session.get('call_ids')})
    for st in streams:
        common = dict(session_id=st.get('session_id'), stream_id=st.get('id'))
        session = by_id.get(st.get('session_id')) or {}
        if st.get('link_mode') == 'exact':
            expected = session.get('negotiated_transport')
            port = session.get('negotiated_port')
            ports = [st.get('source_port'), st.get('destination_port')]
            mismatch = expected and st.get('transport') and expected != st['transport']
            address = session.get('negotiated_ip')
            endpoints = [st.get('source_ip'), st.get('destination_ip')]
            try:
                ip = ip_address(address)
                address_differs = not ip.is_unspecified and all(endpoints) and ip not in [ip_address(v) for v in endpoints]
            except ValueError:
                address_differs = False
            if mismatch or address_differs or (port and not (port == 9 and expected == 'TCP') and all(p is not None for p in ports) and port not in ports):
                yield Diagnostic(rule_id='SDP-002', severity='warning', evidence_level='suspected',
                                 title='已关联媒体流的端点或传输方式与协商值不同',
                             description='SSRC 已精确关联。可对照协商值与捕获的源、目的端点核查差异。',
                                 evidence={'transport':st.get('transport'), 'ports':ports, 'addresses':endpoints,
                                           'negotiated_address':address,
                                           'negotiated_transport':expected, 'negotiated_port':port}, **common)
        # Ignore partial edge buckets. Require a sustained change across complete adjacent buckets.
        samples = (st.get('bitrate_samples') or [])[1:-1]
        for index in range(3, len(samples)-2):
            base = median(v for _, v in samples[index-3:index])
            low = samples[index:index+3]
            if base > 0 and max(v for _, v in low) <= base * 0.3:
                yield Diagnostic(rule_id='MED-006', severity='warning', evidence_level='suspected',
                                 title='连续三个采样窗口码率不超过基线的 30%',
                             description='基线取前三个完整窗口的中位数，证据保留随后三个窗口的实际码率。',
                                 timestamp=low[0][0], evidence={'baseline_kbps':base,'samples_kbps':[v for _,v in low]}, **common)
                break
