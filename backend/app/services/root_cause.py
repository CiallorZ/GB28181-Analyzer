#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""根因链分析（纯本地规则，不调用 AI）。

按"抓包范围 -> 信令 -> 协商 -> 媒体路径 -> 媒体质量 -> 编码"的顺序找最可能的
失败环节。chain 中只写会话/媒体流/诊断里实际出现的事实，不推测报文号或地址；
证据不足时只给 suspected / insufficient，不把推断包装成已确认根因。

入参兼容 Diagnostic dataclass、ORM 行与 dict，因此既可用于分析流水线，也可用
于单测中的轻量替身。
"""
from __future__ import annotations

CONFIRMED = 'confirmed'
SUSPECTED = 'suspected'
INSUFFICIENT = 'insufficient'

_NEGOTIATION_RULES = frozenset({'SDP-002', 'SDP-003'})
_QUALITY_RULES = frozenset({'MED-002', 'MED-003', 'MED-009'})
_CODEC_RULES = frozenset({'MED-008'})

_LABELS = {
    'signaling': '信令事务未完成',
    'negotiation': 'SDP 与实际媒体不一致',
    'media_path': '抓包点未捕获媒体',
    'media_quality': '媒体质量异常',
    'codec': '编码不可解码',
    'capture_scope': '抓包范围不足',
    'none': '未发现明确失败环节',
    'unknown': '证据不足，无法判断',
}


def _field(obj, key: str, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _text(value) -> str:
    if value is None:
        return ''
    return value.strip() if isinstance(value, str) else str(value)


def _rule(d) -> str:
    return _text(_field(d, 'rule_id'))


def _title(d, fallback: str = '') -> str:
    return _text(_field(d, 'title')) or fallback


def _evidence(d) -> dict:
    ev = _field(d, 'evidence')
    return ev if isinstance(ev, dict) else {}


def _confirmed(d) -> bool:
    return _text(_field(d, 'evidence_level')) == CONFIRMED


def _is_problem(d) -> bool:
    return _text(_field(d, 'severity')) in ('critical', 'warning')


def _sorted(diagnostics) -> list:
    items = [d for d in (diagnostics or []) if d is not None]
    return sorted(items, key=lambda d: (_rule(d),
                                        _text(_field(d, 'session_id')),
                                        _text(_field(d, 'stream_id')),
                                        _title(d)))


def _matches(d, session) -> bool:
    """诊断未指明会话时视为任务级证据，可以关联任意会话。"""
    sid = _field(d, 'session_id')
    return sid is None or _text(sid) == _text(_field(session, 'id'))


def _clean_steps(steps) -> list[str]:
    out: list[str] = []
    for step in steps:
        text = _text(step)
        if text and text not in out:
            out.append(text)
    return out


def _result(stage: str, confidence: str, steps, rule_ids, next_check: str) -> dict:
    label = _LABELS.get(stage, _LABELS['unknown'])
    if confidence == SUSPECTED and not label.startswith('疑似'):
        label = '疑似' + label
    return {
        'failure_stage': stage,
        'label': label,
        'confidence': confidence,
        'chain': _clean_steps(steps)[:4],
        'evidence_rule_ids': list(dict.fromkeys(r for r in rule_ids if r)),
        'next_check': next_check,
    }


def _signal_step(session) -> str:
    code = _text(_field(session, 'final_code'))
    if code:
        return 'INVITE 收到 %s 响应' % code
    status = _text(_field(session, 'signal_status'))
    if status == 'success':
        return 'INVITE 收到成功响应'
    return '会话信令状态 %s' % status if status else ''


def _sdp_step(session) -> str:
    ip = _text(_field(session, 'negotiated_ip'))
    port = _text(_field(session, 'negotiated_port'))
    if ip and port:
        return 'SDP 协商 %s:%s' % (ip, port)
    return 'SDP 声明 %s' % ip if ip else ''


def _stream_step(stream) -> str:
    ssrc = _text(_field(stream, 'ssrc'))
    count = _field(stream, 'packet_count')
    if ssrc and count is not None:
        return '捕获 RTP 流 SSRC %s，共 %s 包' % (ssrc, _text(count))
    if ssrc:
        return '捕获 RTP 流 SSRC %s' % ssrc
    if count is not None:
        return '捕获 RTP 流，共 %s 包' % _text(count)
    return '捕获 RTP 流'


def _mismatch_steps(d) -> list[str]:
    """只用诊断 evidence 中实际存在的地址/端口/SSRC 描述观察到的差异。"""
    ev = _evidence(d)
    steps = []
    if _rule(d) == 'SDP-003':
        subject = _text(ev.get('subject_ssrc'))
        sdp = _text(ev.get('sdp_ssrc'))
        if subject and sdp:
            steps.append('Subject SSRC %s，SDP SSRC %s' % (subject, sdp))
    elif _rule(d) == 'SDP-002':
        addresses = ev.get('addresses')
        ports = ev.get('ports')
        if isinstance(addresses, (list, tuple)) and addresses:
            values = [_text(v) for v in addresses]
            steps.append('实际捕获地址 %s' % ', '.join(v for v in values if v))
        if isinstance(ports, (list, tuple)) and ports:
            values = [_text(v) for v in ports]
            steps.append('实际捕获端口 %s' % ', '.join(v for v in values if v))
        actual = _text(ev.get('transport'))
        expected = _text(ev.get('negotiated_transport'))
        if actual and expected and actual != expected:
            steps.append('实际传输 %s，协商 %s' % (actual, expected))
    if not steps:
        steps.append(_title(d, 'SDP 与实际媒体不一致'))
    return steps


def _rebuild_ok(stream) -> bool | None:
    """True/False 为明确结论，None 表示没有重建证据（短流未尝试重建）。"""
    explicit = _field(stream, 'rebuilt_ok')
    if isinstance(explicit, bool):
        return explicit
    extra = _field(stream, 'extra')
    if isinstance(extra, dict):
        rebuild = extra.get('rebuild')
        if isinstance(rebuild, dict) and isinstance(rebuild.get('ok'), bool):
            return rebuild['ok']
    path = _field(stream, 'rebuilt_path')
    return True if path else None


def _rebuild_failed(stream) -> bool:
    return _rebuild_ok(stream) is False or bool(_field(stream, 'rebuild_error'))


def build_root_cause(diagnostics, sessions, streams, stats, limits) -> dict:
    """给出单一最可能的失败环节；结果与输入顺序无关，不修改传入数据。"""
    diags = _sorted(diagnostics)
    session_list = [s for s in (sessions or []) if s is not None]
    stream_list = [s for s in (streams or []) if s is not None]
    limit_list = [x for x in (limits or []) if x is not None]
    stats_dict = stats if isinstance(stats, dict) else {}
    zero_packets = stats_dict.get('count') == 0

    # 1. 抓包范围：先看证据前提，避免把"没抓到"说成业务没发生。
    capture_rules = [_rule(d) for d in diags if _rule(d) == 'CAP-001']
    if zero_packets or limit_list or capture_rules:
        steps = []
        if zero_packets:
            steps.append('抓包中没有可分析的报文')
        for lim in limit_list[:2]:
            msg = _text(lim.get('message')) if isinstance(lim, dict) else _text(lim)
            if not msg and isinstance(lim, dict):
                msg = _text(lim.get('code'))
            if msg:
                steps.append('抓包局限：%s' % msg[:60])
        if not steps:
            steps = [_title(d, '抓包不完整') for d in diags if _rule(d) == 'CAP-001']
        no_media = any(_text(_field(s, 'media_status')) == 'no_media'
                       for s in session_list)
        confidence = SUSPECTED if zero_packets or no_media else INSUFFICIENT
        return _result(
            'capture_scope', confidence, steps,
            capture_rules or (['CAP-001'] if limit_list else []),
            '核对抓包点、过滤条件和时间窗，在信令与媒体路径上补抓')

    # 2. 信令：需要失败会话 + 已确认的 SIP 失败诊断。
    for session in session_list:
        if _text(_field(session, 'signal_status')) == 'success':
            continue
        for d in diags:
            if not _rule(d).startswith('SIP-') or not _confirmed(d) or not _matches(d, session):
                continue
            steps = [_signal_step(session), _sdp_step(session),
                     _title(d, 'SIP 失败响应')]
            device = _text(_field(session, 'device_id'))
            if device:
                steps.insert(1, '设备 %s' % device)
            return _result(
                'signaling', CONFIRMED, steps, [_rule(d)],
                '核对失败响应码对应的通道/权限/设备状态，修复后重新点播')

    # 3. 信令成功但无媒体：先区分协商不一致与"抓包点没看到媒体"。
    # 信令不成功却没有确认的 SIP 失败证据时，也不把"没媒体"归到业务成功路径。
    no_media_sessions = [s for s in session_list
                         if _text(_field(s, 'media_status')) == 'no_media'
                         and not any(_text(_field(d, 'session_id')) in (None, _text(_field(s, 'id')))
                                     and _rule(d) == 'SIP-003' and _confirmed(d)
                                     for d in diags)]
    if no_media_sessions:
        for session in no_media_sessions:
            mismatches = [d for d in diags if _rule(d) in _NEGOTIATION_RULES
                          and _confirmed(d) and _matches(d, session)]
            if not mismatches:
                continue
            steps = [_signal_step(session), _sdp_step(session)]
            for d in mismatches[:2]:
                steps.extend(_mismatch_steps(d))
            return _result(
                'negotiation', CONFIRMED, steps,
                [_rule(d) for d in mismatches],
                '核对协商地址/SSRC 与实际媒体端点，确认播放器匹配字段')

        session = no_media_sessions[0]
        steps = [_signal_step(session), _sdp_step(session),
                 '抓包点未捕获匹配 RTP']
        related = [_rule(d) for d in diags
                   if _rule(d) == 'MED-001' and _matches(d, session)]
        return _result(
            'media_path', SUSPECTED, steps, related,
            '在抓包点两侧补抓包，核对协商端口是否放通')

    # 4. 媒体质量：只采用已确认的丢包/抖动诊断。
    if stream_list:
        quality = [d for d in diags
                   if _rule(d) in _QUALITY_RULES and _confirmed(d)]
        if quality:
            by_id = {_text(_field(s, 'id')): s for s in stream_list}
            primary = by_id.get(_text(_field(quality[0], 'stream_id')))
            steps = [_stream_step(primary or stream_list[0])]
            steps.extend(_title(d) for d in quality if _title(d))
            if not any(_title(d) for d in quality):
                steps.extend(_text(_field(d, 'rule_id')) for d in quality)
            return _result(
                'media_quality', CONFIRMED, steps,
                [_rule(d) for d in quality],
                '按诊断证据定位丢包/抖动位置，必要时在接收端补抓包')

        # 5. 编码：重建失败只说明"抓到的码流不可用"，工具环境也可能有影响。
        codec_diags = [d for d in diags if _rule(d) in _CODEC_RULES]
        bad_streams = [s for s in stream_list if _rebuild_failed(s)]
        if codec_diags or bad_streams:
            stream = bad_streams[0] if bad_streams else stream_list[0]
            steps = [_stream_step(stream), '视频重建失败']
            error = _text(_field(stream, 'rebuild_error'))
            if error:
                steps.append(error[:60])
            codec = _text(_field(stream, 'codec'))
            if codec:
                steps.append('编码 %s' % codec)
            steps.extend(_title(d) for d in codec_diags)
            confidence = (CONFIRMED if any(_confirmed(d) for d in codec_diags)
                          else SUSPECTED)
            return _result(
                'codec', confidence, steps,
                [_rule(d) for d in codec_diags],
                '检查重建错误与抓包起点，确认编码格式和参数集是否完整')

    # 6. 没有可判定的问题：只有正向端到端证据才能说"确认无问题"。
    signal_and_media = any(
        _text(_field(s, 'signal_status')) == 'success'
        and _text(_field(s, 'media_status')) == 'received'
        for s in session_list)
    playable = any(_rebuild_ok(s) is True for s in stream_list)
    if not any(_is_problem(d) for d in diags):
        if signal_and_media and playable:
            return _result(
                'none', CONFIRMED,
                ['INVITE 收到成功响应', '抓包点捕获到 RTP 媒体',
                 '视频重建成功'], [],
                '保留本次抓包作为基线，无需额外处置')
        return _result('none', INSUFFICIENT, [], [],
                       '补充覆盖信令与媒体路径的抓包后再复核')

    return _result('unknown', INSUFFICIENT, [], [],
                   '上传完整抓包并重新分析后再判断')
