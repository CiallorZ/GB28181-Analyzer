#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
会话重建（M05 核心）

从 SIP 消息流还原业务会话、Dialog、事务。

设计原则（PRD 反复强调的）：
1. Dialog 由 Call-ID + From-Tag + To-Tag 确定，不是只看 Call-ID
   —— 同一 Call-ID 下的 INVITE 和 BYE 属于同一 Dialog，
      但同一 Call-ID 可能有多个事务
2. 信令状态与媒体状态**分开判定**
   —— SIP 200 OK 不代表媒体通了，更不代表用户看到了画面
3. 指标算不出来就留 None，绝不填 0
4. 区分"观察到的序列号缺口"与"确认丢包"
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .sip_parser import PROVISIONAL_CODES, SipInfo, make_dialog_key


@dataclass
class DialogInfo:
    """一个 SIP Dialog"""
    key: str
    call_id: str
    from_tag: str = ''
    to_tag: str = ''
    method: str = ''

    invite_time: float | None = None
    provisional_time: float | None = None
    answer_time: float | None = None
    ack_time: float | None = None
    bye_time: float | None = None
    end_time: float | None = None

    final_code: int | None = None
    request_count: int = 0
    response_count: int = 0
    retransmissions: int = 0

    messages: list = field(default_factory=list)
    sdp_offer: dict | None = None
    sdp_answer: dict | None = None
    source_ip: str = ''
    destination_ip: str = ''
    device_id: str = ''


@dataclass
class SessionInfo:
    """一次业务会话（一次点播）"""
    device_id: str = ''
    channel_id: str = ''
    session_type: str = 'live'

    initiator_ip: str = ''
    receiver_ip: str = ''
    initiator_id: str = ''
    receiver_id: str = ''

    start_time: float | None = None
    end_time: float | None = None

    dialogs: list = field(default_factory=list)
    media_stream_keys: list = field(default_factory=list)

    # 分层状态（初始都是 unknown，由后续判定）
    signal_status: str = 'unknown'
    media_status: str = 'unknown'
    end_reason: str = 'unknown'

    # 耗时指标（None 表示无法计算）
    invite_latency: float | None = None
    sdp_negotiation_latency: float | None = None
    first_media_latency: float | None = None
    signal_to_first_media: float | None = None
    media_duration: float | None = None
    total_duration: float | None = None
    first_keyframe_latency: float | None = None

    negotiated_ip: str = ''
    negotiated_port: int | None = None
    negotiated_transport: str = ''
    subject_ssrc: str = ''
    sdp_ssrc: str = ''

    call_ids: list = field(default_factory=list)
    notes: list = field(default_factory=list)


# ---------------------------------------------------------------
# 1. 按消息归并 Dialog
# ---------------------------------------------------------------
def build_dialogs(messages: list[SipInfo]) -> list[DialogInfo]:
    """按 Call-ID + Tags 归并 Dialog

    注意：请求方向的 To-Tag 为空，响应才有。
    所以先用 Call-ID 分组，再用首个 response 的 to-tag 补全。
    """
    by_callid: dict[str, list[SipInfo]] = defaultdict(list)
    for m in messages:
        if m.call_id:
            by_callid[m.call_id].append(m)

    dialogs: list[DialogInfo] = []

    for call_id, msgs in by_callid.items():
        msgs.sort(key=lambda x: (x.timestamp, x.packet_number))

        # 找出该 Call-ID 下的 to-tag（响应/后续请求里的）
        to_tag = ''
        for m in msgs:
            if m.to_tag:
                to_tag = m.to_tag
                break

        from_tag = ''
        for m in msgs:
            if m.from_tag:
                from_tag = m.from_tag
                break

        # 与 SipInfo.dialog_key() 保持同一构造：tag 排序后再拼。
        # 否则请求（To-Tag 为空）与响应算出的键不同，SIP 消息永远回填不上 dialog_id。
        d = DialogInfo(key=make_dialog_key(call_id, from_tag, to_tag),
                       call_id=call_id, from_tag=from_tag, to_tag=to_tag)
        d.messages = msgs

        # 统计
        seen_branches: dict[str, int] = {}
        for m in msgs:
            if m.is_request:
                d.request_count += 1
                if not d.method:
                    d.method = m.method
                # 重传：同 branch 同 CSeq 再次出现
                tk = m.transaction_key()
                seen_branches[tk] = seen_branches.get(tk, 0) + 1
                if seen_branches[tk] > 1:
                    d.retransmissions += 1
            else:
                d.response_count += 1

            # 关键时间点
            if m.method == 'INVITE' and m.is_request:
                if d.invite_time is None:
                    d.invite_time = m.timestamp
                    d.source_ip = m.source_ip
                    d.destination_ip = m.destination_ip
                    if m.sdp:
                        d.sdp_offer = m.sdp.to_dict()
                    # 从 To 头取设备 ID
                    d.device_id = _uri_id(m.headers.get('to', ''))
            elif m.method == 'INVITE' and not m.is_request:
                if m.status_code in PROVISIONAL_CODES and d.provisional_time is None:
                    d.provisional_time = m.timestamp
                elif m.status_code and m.status_code not in PROVISIONAL_CODES:
                    if d.answer_time is None:
                        d.answer_time = m.timestamp
                        d.final_code = m.status_code
                        if m.sdp:
                            d.sdp_answer = m.sdp.to_dict()
            elif m.method == 'ACK' and m.is_request:
                if d.ack_time is None:
                    d.ack_time = m.timestamp
            elif m.method == 'BYE' and m.is_request:
                if d.bye_time is None:
                    d.bye_time = m.timestamp

        d.end_time = msgs[-1].timestamp if msgs else None
        dialogs.append(d)

    dialogs.sort(key=lambda d: (d.invite_time or d.messages[0].timestamp
                                if d.messages else 0))
    return dialogs


def _uri_id(header: str) -> str:
    import re
    m = re.search(r'sip:([^@;>\s]+)@', header or '')
    if m:
        return m.group(1)
    m = re.search(r'sip:([^@;>\s]+)', header or '')
    return m.group(1) if m else ''


# ---------------------------------------------------------------
# 2. 从 Dialog 归纳业务会话
# ---------------------------------------------------------------
def build_sessions(dialogs: list[DialogInfo],
                   messages: list[SipInfo]) -> list[SessionInfo]:
    """一个 INVITE Dialog = 一次点播业务会话

    非 INVITE 的 Dialog（REGISTER/MESSAGE/SUBSCRIBE 等）不构成点播会话，
    除非能明确关联到某个 INVITE 会话。
    """
    sessions: list[SessionInfo] = []

    for d in dialogs:
        if d.method != 'INVITE':
            continue

        s = SessionInfo()
        s.dialogs.append(d)
        s.call_ids.append(d.call_id)
        s.device_id = d.device_id
        s.channel_id = d.device_id          # 国标点播通常是通道 ID
        s.initiator_ip = d.source_ip
        s.receiver_ip = d.destination_ip
        s.start_time = d.invite_time

        # 从 INVITE 的 From/To 判断发起方 ID
        for m in d.messages:
            if m.method == 'INVITE' and m.is_request:
                s.initiator_id = _uri_id(m.headers.get('from', ''))
                s.receiver_id = _uri_id(m.headers.get('to', ''))
                break

        # 协商参数
        # 关键：国标 TCP 模式下，offer 给的是"我方监听端口"（如 8808），
        # answer 常回 m=video 9 + setup:active，表示"由我主动连你的 8808"。
        # 所以端口要优先用 offer，不能只看 answer，否则永远匹配不到实际连接。
        offer = d.sdp_offer or {}
        answer = d.sdp_answer or {}
        sdp = answer or offer
        if sdp:
            s.negotiated_ip = (answer.get('connection_address')
                               or offer.get('connection_address') or '')
            offer_media = (offer.get('media') or [{}])[0]
            answer_media = (answer.get('media') or [{}])[0]
            offer_port = offer_media.get('port')
            answer_port = answer_media.get('port')

            # answer 端口为 0 或 9 是"被动/主动连接"的占位值，不是真实监听端口
            if answer_port and answer_port > 9:
                s.negotiated_port = answer_port
            elif offer_port and offer_port > 9:
                s.negotiated_port = offer_port
            else:
                s.negotiated_port = answer_port or offer_port

            is_tcp = bool(answer.get('is_tcp') or offer.get('is_tcp'))
            s.negotiated_transport = 'TCP' if is_tcp else 'UDP'
            s.sdp_ssrc = (answer.get('y_ssrc') or offer.get('y_ssrc') or '')

        # Subject 里的 SSRC（格式：设备ID:SSRC,平台ID:SSRC）
        for m in d.messages:
            if m.method == 'INVITE' and m.is_request and m.subject:
                parts = m.subject.split(',')
                if parts:
                    seg = parts[0].split(':')
                    if len(seg) >= 2:
                        s.subject_ssrc = seg[1].strip()
                break

        # ---- 耗时计算（None 安全） ----
        if d.invite_time is not None and d.answer_time is not None:
            s.invite_latency = round(d.answer_time - d.invite_time, 3)
        if d.provisional_time is not None and d.answer_time is not None:
            s.sdp_negotiation_latency = round(d.answer_time - d.provisional_time, 3)

        # ---- 信令状态 ----
        s.signal_status = _judge_signal(d)

        # ---- 结束原因 ----
        if d.bye_time is not None:
            s.end_time = d.bye_time
            # BYE 是否有最终响应
            has_final = any(x.method == 'BYE' and not x.is_request
                            and x.status_code and x.status_code < 300
                            for x in d.messages)
            s.end_reason = 'normal' if has_final else 'abnormal'
            if not has_final:
                s.notes.append('发出 BYE 但未收到最终响应，事务未正常终止')
        elif d.answer_time is not None:
            s.end_reason = 'capture_ended'
            s.notes.append('抓包结束时会话仍在进行（未见 BYE），需确认抓包范围')
            s.end_time = d.end_time
        else:
            s.end_reason = 'unknown'

        if s.start_time is not None and s.end_time is not None:
            s.total_duration = round(s.end_time - s.start_time, 3)

        sessions.append(s)

    sessions.sort(key=lambda x: x.start_time or 0)
    return sessions


def _judge_signal(d: DialogInfo) -> str:
    """判定信令层状态

    成功：有 2xx 最终响应 + ACK
    失败：有 3xx-6xx 最终响应
    不完整：只有 INVITE 没响应，或只有临时响应
    """
    if d.final_code is None:
        if d.provisional_time is not None:
            return 'incomplete'
        return 'incomplete' if d.invite_time is not None else 'unknown'
    if 200 <= d.final_code < 300:
        return 'success'
    return 'failed'


# ---------------------------------------------------------------
# 3. 关联媒体流到会话
# ---------------------------------------------------------------
def link_media(sessions: list[SessionInfo], streams: list[dict]) -> None:
    """把 RTP 流关联到业务会话

    匹配优先级（从严到宽，避免误关联）：
    1. SSRC 完全一致（SDP y= 或 Subject 中的 SSRC）
    2. 传输五元组匹配协商的 IP:端口
    3. 时间窗重叠 + 同方向
    """
    # 一条流只能归属一个会话：先全局算分，再按分数贪心分配
    # 否则 4 条流可能被 7 个会话重复认领
    claims: list = []      # (score, session_idx, stream_idx)

    for si, s in enumerate(sessions):
        for ti, st in enumerate(streams):
            score = _match_score(s, st)
            if score >= 40:
                claims.append((score, si, ti))

    claims.sort(key=lambda x: -x[0])
    assigned_streams = set()
    per_session: dict = {}
    for score, si, ti in claims:
        if ti in assigned_streams:
            continue
        if si in per_session and len(per_session[si]) >= 8:
            continue
        assigned_streams.add(ti)
        per_session.setdefault(si, []).append(ti)

    for si, s in enumerate(sessions):
        idxs = per_session.get(si, [])
        matched = [(1, streams[ti]) for ti in idxs]

        # ---- 媒体状态 ----
        # 判据只到"抓到并解析出 RTP"这一层。
        # P0 未实现视频解码，不能因为没解出画面就判 undecodable，
        # 那是 P1 的能力边界，需在报告中如实说明。
        if not matched:
            s.media_status = 'no_media'
        else:
            s.media_status = 'received'

        s.media_stream_keys = [id(st) for _sc, st in matched]

        # ---- 首媒体包耗时 ----
        # 关键约束：媒体首包必须落在会话生命周期内。
        # 若首包晚于 BYE，说明是"BYE 后残留媒体"或"另一轮会话的媒体"，
        # 不能算作本会话的首媒体耗时，否则会得出"首媒体耗时 > 会话时长"的荒谬结果。
        if matched and s.start_time is not None:
            d = s.dialogs[0] if s.dialogs else None
            session_end = s.end_time
            if session_end is None and d is not None:
                session_end = d.end_time

            first_ts = min((st.get('start_time') or 0) for _sc, st in matched)

            in_window = True
            if session_end is not None and first_ts > session_end:
                in_window = False
                s.notes.append(
                    '媒体首包（%.3fs）晚于会话结束（%.3fs），'
                    '可能是 BYE 后的残留媒体或另一轮会话的流，'
                    '不计入首媒体耗时' % (first_ts, session_end))

            if in_window and first_ts >= s.start_time:
                s.first_media_latency = round(first_ts - s.start_time, 3)
                anchor = (d.ack_time or d.answer_time) if d else None
                if anchor is not None and first_ts >= anchor:
                    s.signal_to_first_media = round(first_ts - anchor, 3)
                ends = [st.get('end_time') or 0 for _sc, st in matched]
                s.media_duration = round(max(ends) - first_ts, 3) if ends else None
            else:
                # 媒体在会话窗口外，仍记录流但不给耗时指标
                s.media_duration = None

    return


def _match_score(s: SessionInfo, st: dict) -> int:
    """给"会话-媒体流"配对打分

    从严到宽：
      1. SSRC 完全一致（最强）
      2. 端口匹配（TCP 被动模式下 dst_port = 协商端口）
      3. 传输方式一致
      4. 时间窗重叠
    """
    score = 0
    raw_ssrc = st.get('ssrc')
    ssrc_hex = '%08x' % (raw_ssrc or 0)

    # 1) SSRC 精确匹配 —— 唯一强判据，权重必须远超其他项
    #    否则多会话共享同一端口（国标 TCP 常见）时所有候选同分，
    #    贪心分配会把所有流都塞给第一个会话。
    #
    #    注意：SSRC 缺失（0 / None）时**不能参与匹配**。
    #    lstrip('0') 后 h 变成空串，而任何字符串都 endswith('')，
    #    会让「没有 SSRC 的流」拿到满分，比真实匹配还高。
    for want in (s.sdp_ssrc, s.subject_ssrc):
        if not want or not raw_ssrc:
            continue
        w = want.lower().lstrip('0')
        h = ssrc_hex.lower().lstrip('0')
        if not w or not h:
            continue
        # 兼容三种写法：完整 8 位 / 去前导 0 / 互为后缀
        if h == w or h.endswith(w) or w.endswith(h):
            score += 10000
            break

    # 2) 端口匹配 —— 弱判据（多会话常共享 8808）
    if s.negotiated_port:
        if st.get('dst_port') == s.negotiated_port:
            score += 60
        elif st.get('src_port') == s.negotiated_port:
            score += 40

    # 3) 传输方式
    if (st.get('transport') or '').upper() == \
            (s.negotiated_transport or '').upper():
        score += 15

    # 4) 时间窗
    st_start = st.get('start_time') or 0
    st_end = st.get('end_time') or 0
    if s.start_time is not None:
        s_end = s.end_time if s.end_time is not None else s.start_time + 3600
        if st_start <= s_end + 5 and st_end >= s.start_time - 5:
            score += 30

    return score


# ---------------------------------------------------------------
# 4. 抓包局限性检测（PRD 6.3）
# ---------------------------------------------------------------
def detect_capture_limits(sessions: list[SessionInfo],
                          messages: list[SipInfo],
                          packets: list[dict]) -> list[dict]:
    """识别抓包本身的局限，避免把"没抓到"当成"没发生" """
    warns = []

    if not packets:
        warns.append({
            'code': 'no_packets',
            'level': 'critical',
            'message': '抓包中没有可分析的报文',
        })
        return warns

    times = [p['ts'] for p in packets if p.get('ts')]
    cap_start = min(times) if times else 0
    cap_end = max(times) if times else 0

    for s in sessions:
        # 抓包起点落在会话中间
        if s.start_time is not None and s.start_time <= cap_start + 0.001:
            d = s.dialogs[0] if s.dialogs else None
            if d and d.invite_time is None:
                warns.append({
                    'code': 'session_cut_start',
                    'level': 'warning',
                    'message': '会话 %s 在抓包开始前已建立，未捕获 INVITE'
                               % (s.device_id or s.call_ids[0][:16]),
                })
        # 抓包结束时会话未结束
        if s.end_reason == 'capture_ended':
            warns.append({
                'code': 'session_cut_end',
                'level': 'warning',
                'message': '会话 %s 在抓包结束时仍未结束，媒体统计可能不完整'
                           % (s.device_id or ''),
            })
        # 只抓到信令没抓到媒体
        if s.signal_status == 'success' and s.media_status == 'no_media':
            warns.append({
                'code': 'no_media_captured',
                'level': 'warning',
                'message': '会话 %s 信令成功但未捕获到媒体流：'
                           '可能是媒体未经过抓包点，或媒体端口未建立连接'
                           % (s.device_id or ''),
            })

    # 只抓到媒体没抓到信令
    if not any(s.dialogs for s in sessions) and packets:
        has_rtp = any('rtp' in (p.get('protocols') or '').lower() for p in packets)
        if has_rtp:
            warns.append({
                'code': 'no_signal',
                'level': 'info',
                'message': '抓到媒体流量但没有 SIP 信令：'
                           '抓包点可能位于信令路径之外',
            })

    return warns
