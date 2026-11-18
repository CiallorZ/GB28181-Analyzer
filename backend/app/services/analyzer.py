#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分析编排（P0 主链路）

流水线：
  抓包文件
    -> 文件信息（M01-02）
    -> 报文索引（M02）
    -> SIP 消息解析（M03）
    -> SDP 解析（M04）
    -> Dialog / 业务会话重建（M05）
    -> RTP 流抽取与质量分析（M07）
    -> 媒体关联
    -> 诊断（M09）
    -> 入库

所有阶段都会写进度，失败时写明确错误，不吞异常。
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..core.config import settings
from ..models.entities import (
    AnalysisTask, CaptureFile, DiagnosticEvent, Endpoint, MediaMetric,
    MediaStream, PacketIndex, SipDialog, SipMessage, TaskStatus,
    BusinessSession, Device,
)
from ..parsers import capture, rtp_analyzer, session_builder, sip_parser
from . import diagnosis as diag_engine

log = logging.getLogger('gb28181.analyzer')


def _set_progress(db: Session, task: AnalysisTask, stage: str, pct: int):
    task.stage = stage
    task.progress = pct
    db.commit()


# ===============================================================
# 主入口
# ===============================================================
def run_analysis(db: Session, task_id: int):
    """执行完整分析。调用方负责捕获异常并更新任务状态。"""
    task = db.get(AnalysisTask, task_id)
    if not task:
        raise RuntimeError('任务不存在')

    # 清理旧结果（支持重新分析）之前必须先确认源文件还在。
    # 否则源文件被保留策略清掉后重新分析，会先把上一次的完整结果删掉，
    # 再因为文件不存在而失败 —— 用户手上就什么都不剩了。
    files = task.files
    if not files:
        _mark_failed(db, task_id, '任务没有关联抓包文件', '解析失败')
        raise capture.CaptureError('任务没有关联抓包文件')
    missing = [cf.filename for cf in files
               if not cf.stored_path or not os.path.isfile(cf.stored_path)]
    if missing:
        msg = ('源文件已不存在（可能被保留策略清理）：%s'
               % '、'.join(missing))
        _mark_failed(db, task_id, msg, '源文件缺失')
        raise capture.CaptureError(msg)

    task.status = TaskStatus.ANALYZING
    task.started_at = datetime.utcnow()
    task.error_message = None
    db.commit()

    # 注意删除顺序：先删子表再删父表，避免外键约束报错
    stream_ids = [r[0] for r in db.execute(
        select(MediaStream.id).where(MediaStream.task_id == task_id)).all()]
    if stream_ids:
        db.execute(delete(MediaMetric).where(
            MediaMetric.stream_id.in_(stream_ids)))

    for model in (MediaStream, BusinessSession, SipDialog, SipMessage,
                  DiagnosticEvent, Device, Endpoint, PacketIndex):
        db.execute(delete(model).where(model.task_id == task_id))
    db.commit()

    try:
        _run(db, task)
    except capture.CaptureError as e:
        db.rollback()
        _mark_failed(db, task_id, str(e), '解析失败')
        raise
    except Exception as e:
        db.rollback()
        log.exception('任务 #%s 分析异常', task_id)
        _mark_failed(db, task_id, '%s: %s' % (type(e).__name__, e), '分析异常')
        raise

    # _run 期间任务可能已被取消（cancel 只置状态，不强杀线程）。
    # 这里必须重新读状态，不能用内存里的 task 对象无条件写 COMPLETED，
    # 否则用户点了取消却看到"完成"。
    db.expire_all()
    task = db.get(AnalysisTask, task_id)
    if task is None:
        return
    if task.status == TaskStatus.CANCELLED:
        log.info('任务 #%s 分析完成，但已被取消，保留取消状态', task_id)
    else:
        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.utcnow()
        task.progress = 100
        task.stage = '完成'
    db.commit()

    # 按保留策略清理（不阻塞主流程，失败不影响结果）
    try:
        from . import retention
        retention.auto_purge(db)
    except Exception:
        log.exception('保留策略清理失败（不影响分析结果）')


def _mark_failed(db: Session, task_id: int, message: str, stage: str):
    """把任务置为失败，且不覆盖已取消状态

    注意：rollback() 不会让已加载的对象失效（本项目的 session 设了
    expire_on_commit=False），必须显式 expire_all，否则会从 identity map
    拿到旧状态，把另一个会话刚写的 CANCELLED 覆盖成 FAILED。
    """
    try:
        db.rollback()
        db.expire_all()
        task = db.get(AnalysisTask, task_id)
        if task is None:
            return
        if task.status == TaskStatus.CANCELLED:
            return
        task.status = TaskStatus.FAILED
        task.error_message = message
        task.stage = stage
        db.commit()
    except Exception:
        log.exception('写入任务 #%s 失败状态时出错', task_id)


def _run(db: Session, task: AnalysisTask):
    files = task.files
    if not files:
        raise capture.CaptureError('任务没有关联抓包文件')

    # ---------------- 1. 文件信息 ----------------
    _set_progress(db, task, '读取文件信息', 5)
    cf = files[0]
    info = capture.inspect_file(cf.stored_path)
    cf.file_format = info.file_format
    cf.checksum = info.checksum or cf.checksum
    cf.packet_count = info.packet_count
    cf.capture_start = info.capture_start
    cf.capture_end = info.capture_end
    cf.duration = info.duration
    cf.link_type = info.link_type
    cf.ip_count = info.ip_count
    cf.tcp_count = info.tcp_count
    cf.udp_count = info.udp_count
    cf.warnings = info.warnings
    db.commit()

    path = cf.stored_path

    # ---------------- 2. 报文索引 ----------------
    _set_progress(db, task, '建立报文索引', 15)
    packets = []
    endpoints: dict = {}
    batch = []
    for i, p in enumerate(capture.iter_packets(path)):
        packets.append(p)
        key = (p['src_ip'], p['src_port'])
        ep = endpoints.setdefault(key, {'ip': p['src_ip'], 'port': p['src_port'],
                                        'count': 0, 'bytes': 0})
        ep['count'] += 1
        ep['bytes'] += p['length']

        batch.append(PacketIndex(
            task_id=task.id, file_id=cf.id,
            packet_number=p['number'], timestamp=p['ts'],
            source_ip=p['src_ip'], destination_ip=p['dst_ip'],
            source_port=p['src_port'], destination_port=p['dst_port'],
            transport=p['transport'], protocol=_top_protocol(p['protocols']),
            length=p['length'], summary=_packet_summary(p),
        ))
        if len(batch) >= 2000:
            db.bulk_save_objects(batch)
            db.commit()
            batch.clear()
    if batch:
        db.bulk_save_objects(batch)
        db.commit()

    # 端点入库
    for key, ep in endpoints.items():
        if not ep['ip']:
            continue
        db.add(Endpoint(task_id=task.id, ip=ep['ip'], port=ep['port'],
                        role='unknown', packet_count=ep['count'],
                        byte_count=ep['bytes']))
    db.commit()

    # ---------------- 3. SIP 消息 ----------------
    _set_progress(db, task, '解析 SIP 信令', 30)
    sip_msgs = _load_sip(db, task, path, packets)

    # ---------------- 4. 会话重建 ----------------
    _set_progress(db, task, '重建点播会话', 45)
    dialogs = session_builder.build_dialogs([m['info'] for m in sip_msgs])
    sessions = session_builder.build_sessions(dialogs, [m['info'] for m in sip_msgs])

    # 入库 Dialog
    dialog_map = {}
    for d in dialogs:
        row = SipDialog(
            task_id=task.id, call_id=d.call_id,
            from_tag=d.from_tag, to_tag=d.to_tag, method=d.method,
            start_time=d.messages[0].timestamp if d.messages else 0,
            end_time=d.end_time,
            final_code=d.final_code,
            invite_time=d.invite_time, answer_time=d.answer_time,
            bye_time=d.bye_time,
            request_count=d.request_count,
            response_count=d.response_count,
            retransmission_count=d.retransmissions,
        )
        db.add(row)
        db.flush()
        dialog_map[d.key] = row.id
    db.commit()

    # 回填 SIP 消息的 dialog_id
    for m in sip_msgs:
        key = m['info'].dialog_key()
        did = dialog_map.get(key)
        if did:
            db.execute(
                SipMessage.__table__.update()
                .where(SipMessage.id == m['row'].id)
                .values(dialog_id=did)
            )
    db.commit()

    # 入库业务会话
    session_rows = []
    for s in sessions:
        row = BusinessSession(
            task_id=task.id,
            device_id=s.device_id, channel_id=s.channel_id,
            session_type=s.session_type,
            initiator_ip=s.initiator_ip, receiver_ip=s.receiver_ip,
            initiator_id=s.initiator_id, receiver_id=s.receiver_id,
            start_time=s.start_time, end_time=s.end_time,
            signal_status=s.signal_status,
            media_status=s.media_status,
            end_reason=s.end_reason,
            invite_latency=s.invite_latency,
            sdp_negotiation_latency=s.sdp_negotiation_latency,
            first_media_latency=s.first_media_latency,
            signal_to_first_media=s.signal_to_first_media,
            total_duration=s.total_duration,
            negotiated_ip=s.negotiated_ip,
            negotiated_port=s.negotiated_port,
            negotiated_transport=s.negotiated_transport,
            subject_ssrc=s.subject_ssrc, sdp_ssrc=s.sdp_ssrc,
            call_ids=s.call_ids,
            extra={'notes': s.notes},
        )
        db.add(row)
        db.flush()
        session_rows.append((s, row.id))
    db.commit()

    # 回填 session_id
    for m in sip_msgs:
        if not m['info'].call_id:
            continue
        for s, sid in session_rows:
            if m['info'].call_id in s.call_ids:
                db.execute(
                    SipMessage.__table__.update()
                    .where(SipMessage.id == m['row'].id)
                    .values(session_id=sid)
                )
                break
    db.commit()

    # ---------------- 5. RTP 分析 ----------------
    _set_progress(db, task, '分析 RTP 媒体流', 60)
    streams_raw = _analyze_rtp(db, task, path)

    # 关联媒体到会话
    stream_dicts = [{'id': r.id, 'ssrc': r.ssrc, 'src_port': r.source_port,
                     'dst_port': r.destination_port,
                     'start_time': r.start_time, 'end_time': r.end_time,
                     'has_video': r.has_video, 'frame_count': r.frame_count,
                     'transport': r.transport}
                    for r in streams_raw]
    session_builder.link_media(sessions, stream_dicts)

    # 回写关联结果
    # 注意：link_media 里用 id(stream_dict) 记录归属，
    # 但 stream_dicts 是临时构造的 dict，与 streams_raw 的 ORM 对象 id 不同，
    # 所以这里必须按 stream_dicts 的下标反查 ORM 对象。
    idx_of_dict = {id(d): i for i, d in enumerate(stream_dicts)}

    for s, sid in session_rows:
        row = db.get(BusinessSession, sid)
        row.media_status = s.media_status
        row.first_media_latency = s.first_media_latency
        row.signal_to_first_media = s.signal_to_first_media
        row.media_duration = s.media_duration
        row.media_stream_count = len(s.media_stream_keys)

        for skey in s.media_stream_keys:
            i = idx_of_dict.get(skey)
            if i is None or i >= len(streams_raw):
                continue
            streams_raw[i].session_id = sid
    db.commit()

    # ---------------- 6. 设备目录 ----------------
    _set_progress(db, task, '整理设备目录', 75)
    _load_devices(db, task, sip_msgs)

    # ---------------- 7. 诊断 ----------------
    _set_progress(db, task, '执行诊断', 85)
    limits = session_builder.detect_capture_limits(sessions, 
                                                   [m['info'] for m in sip_msgs],
                                                   packets)
    task_payload = {
        'sessions': [_session_dict(s, sid) for s, sid in session_rows],
        'streams': [_stream_dict(r) for r in streams_raw],
        'messages': [],
        'limits': limits,
    }
    diagnostics = diag_engine.diagnose(task_payload)

    for d in diagnostics:
        db.add(DiagnosticEvent(
            task_id=task.id, session_id=d.session_id, stream_id=d.stream_id,
            rule_id=d.rule_id, severity=d.severity,
            evidence_level=d.evidence_level,
            timestamp=d.timestamp, title=d.title, description=d.description,
            evidence=d.evidence, possible_causes=d.possible_causes,
            recommendations=d.recommendations,
            related_packet_ids=d.related_packet_ids,
            device_id=d.device_id,
        ))
    db.commit()

    # 统计回写会话
    for s, sid in session_rows:
        evs = [d for d in diagnostics if d.session_id == sid]
        row = db.get(BusinessSession, sid)
        row.diagnostic_count = len(evs)
        row.critical_count = sum(1 for d in evs if d.severity == 'critical')
        row.warning_count = sum(1 for d in evs if d.severity == 'warning')
    db.commit()

    # ---------------- 8. 汇总 ----------------
    _set_progress(db, task, '生成汇总', 95)
    task.summary = _build_summary(task, session_rows, streams_raw, diagnostics,
                                 packets, limits)
    db.commit()


# ===============================================================
# 子步骤
# ===============================================================
def _load_sip(db: Session, task: AnalysisTask, path: str, packets: list) -> list[dict]:
    """抽取并解析所有 SIP 消息，返回 [{info, row}]"""
    rows_raw = capture.extract_fields(path, [
        'frame.number', 'frame.time_relative',
        'ip.src', 'udp.srcport', 'ip.dst', 'udp.dstport',
        'sip.CSeq', 'sip.Status-Code',
        'sip.Request-Line', 'sip.Status-Line',
        'sip.msg_hdr', 'sip.msg_body',
    ], 'sip || tcp.port==5060')

    out = []
    rows = []          # 待批量插入的 ORM 对象
    for r in rows_raw:
        try:
            meta = {
                'packet_number': int(r[0]) if r[0] else 0,
                'timestamp': float(r[1]) if r[1] else 0.0,
                'src_ip': r[2], 'src_port': int(r[3]) if r[3] else None,
                'dst_ip': r[4], 'dst_port': int(r[5]) if r[5] else None,
                'request_line': r[8], 'status_line': r[9],
            }
        except (ValueError, IndexError):
            continue

        info = sip_parser.build_message(
            r[10], sip_parser.body_from_hex(r[11]), meta)
        if not info:
            continue

        row = SipMessage(
            task_id=task.id,
            packet_id=info.packet_number,
            timestamp=info.timestamp,
            is_request=info.is_request,
            method=info.method or None,
            status_code=info.status_code,
            call_id=info.call_id or None,
            from_tag=info.from_tag or None,
            to_tag=info.to_tag or None,
            cseq_number=info.cseq_number,
            cseq_method=info.cseq_method or None,
            via_branch=info.via_branch or None,
            source_ip=info.source_ip, source_port=info.source_port,
            destination_ip=info.destination_ip,
            destination_port=info.destination_port,
            request_uri=info.request_uri or None,
            user_agent=info.user_agent or None,
            contact=info.contact or None,
            content_type=info.content_type or None,
            headers=info.headers,
            body=info.body[:20000] if info.body else None,
            sdp=info.sdp.to_dict() if info.sdp else None,
            gb_command=info.gb_command or None,
            device_id=info.device_id or None,
        )
        db.add(row)
        rows.append(row)
        out.append({'info': info, 'row': row})

    # 批量提交一次，避免逐条 flush 的往返开销
    db.flush()
    db.commit()

    # 回填 packet 的 call_id —— 用批量 UPDATE 而不是逐条
    # 做法：按 call_id 分组，每组一次 UPDATE ... WHERE packet_number IN (...)
    by_cid: dict = {}
    for m in out:
        cid = m['info'].call_id
        if cid:
            by_cid.setdefault(cid, []).append(m['info'].packet_number)

    if by_cid:
        from sqlalchemy import update as _update
        for cid, nums in by_cid.items():
            # 分批，避免 SQL 参数过多
            for i in range(0, len(nums), 500):
                chunk = nums[i:i + 500]
                db.execute(
                    _update(PacketIndex.__table__)
                    .where(PacketIndex.task_id == task.id)
                    .where(PacketIndex.packet_number.in_(chunk))
                    .values(call_id=cid)
                )
        db.commit()

    return out


def _analyze_rtp(db: Session, task: AnalysisTask, path: str) -> list[MediaStream]:
    """抽取 RTP 并做质量分析

    UDP：一个数据报 = 一个 RTP 包，直接用
    TCP：RFC4571 封装（2字节长度 + RTP），需要自研重组与对齐扫描

    **不依赖 tshark 的 rtp 解码器** —— 实测它对国标常见的
    TCP 承载 RTP 需要手工 -d 参数，且只能识别部分包。
    """
    streams: list[MediaStream] = []
    pending = []          # 待重建的流：先收集，最后并行重建

    # ---- UDP 承载 ----
    try:
        udp_pkts = capture.extract_udp_rtp(path)
    except capture.CaptureError:
        udp_pkts = []

    if udp_pkts:
        # 逐包构造 RtpPacket
        parsed = []
        for p in udp_pkts:
            payload = p['payload']
            parsed.append(({
                'src_ip': p['src_ip'], 'src_port': p['src_port'],
                'dst_ip': p['dst_ip'], 'dst_port': p['dst_port'],
            }, rtp_analyzer.RtpPacket(
                seq=int.from_bytes(payload[2:4], 'big'),
                timestamp=int.from_bytes(payload[4:8], 'big'),
                ssrc=int.from_bytes(payload[8:12], 'big'),
                payload_type=payload[1] & 0x7f,
                marker=bool((payload[1] >> 7) & 1),
                arrival=p['ts'],
                size=len(payload),
                payload=payload[12:],
            )))

        groups: dict = {}
        for meta, pkt in parsed:
            key = (pkt.ssrc, meta['src_ip'], meta['src_port'],
                   meta['dst_ip'], meta['dst_port'])
            groups.setdefault(key, []).append((meta, pkt))

        for key, items in groups.items():
            pkts = [p for _m, p in items]
            if len(pkts) < 2:
                continue
            meta = items[0][0]
            st = rtp_analyzer.analyze_stream(pkts, transport='UDP')
            ps = _run_ps_analysis(pkts, st)
            tag = 'udp%d' % len(pending)
            pending.append((tag, pkts, st, key, 'UDP', meta, ps))

    # ---- TCP 承载（RFC4571 自研）----
    try:
        tcp_streams = capture.dump_tcp_segments(path)
    except capture.CaptureError:
        tcp_streams = {}

    for sid, entry in tcp_streams.items():
        segs = entry.get('segs') or {}
        meta = entry.get('meta') or {}
        if len(segs) < 3:
            continue
        buf = rtp_analyzer.reassemble_tcp(segs)
        if len(buf) < 100:
            continue
        got = rtp_analyzer.parse_rfc4571(buf)
        if not got:
            continue
        _offset, pkts = got
        if len(pkts) < 3:
            continue

        # RFC4571 里没有逐包时间，用 TCP 段的到达时间近似：
        # 按包序号等比分配到该流的抓包时间窗内
        t0 = meta.get('ts') or 0.0
        # 取所有段的相对时间范围
        spread = _tcp_time_spread(path, sid)
        for i, p in enumerate(pkts):
            if spread and len(pkts) > 1:
                p.arrival = spread[0] + (spread[1] - spread[0]) * i / (len(pkts) - 1)
            else:
                p.arrival = t0 + i * 0.001

        key = (pkts[0].ssrc, meta.get('src_ip'), meta.get('src_port'),
               meta.get('dst_ip'), meta.get('dst_port'))
        st = rtp_analyzer.analyze_stream(pkts, transport='TCP')
        ps = _run_ps_analysis(pkts, st)
        tag = 'tcp%d' % len(pending)
        pending.append((tag, pkts, st, key, 'TCP', meta, ps))

    # ---- 并行重建所有流（利用多核，显著缩短总耗时）----
    if pending:
        try:
            from ..services import rebuild as rb_mod
            out_dir = os.path.join(settings.DATA_DIR, 'rebuilt', str(task.id))
            rb_tasks = [(tag, pkts, st.duration)
                        for tag, pkts, st, _k, _tr, _m, _ps in pending]
            rb_map = rb_mod.rebuild_streams_parallel(rb_tasks, out_dir,
                                                     max_workers=3)
        except Exception:
            log.exception('并行重建媒体流失败（不影响统计结果）')
            rb_map = {}

        for tag, pkts, st, key, transport, meta, ps in pending:
            row = _save_stream(db, task, st, key, transport, meta, ps,
                               rb_map.get(tag))
            streams.append(row)

    db.commit()
    return streams


def _run_ps_analysis(pkts, st):
    """对一条流做 PS/ES 解封装与编码分析（M08）

    只在载荷看起来像 PS 时才做，避免对纯音频流浪费时间。
    """
    try:
        from ..parsers import ps_parser
        payloads = [p.payload for p in pkts if p.payload]
        if not payloads:
            return None
        # 快速判断：任一包里出现 PS pack 起始码就认为需要解析
        looks_ps = any(ps_parser.PS_PACK_START in p[:64] or
                       ps_parser.PES_VIDEO in p[:64]
                       for p in payloads[:20])
        if not looks_ps:
            return None
        times = [p.arrival - (pkts[0].arrival if pkts else 0) for p in pkts]
        return ps_parser.analyze_ps(payloads, times)
    except Exception:
        # PS 分析失败不能影响主流程
        log.exception('PS/ES 分析失败（不影响主流程）')
        return None


def _run_rebuild(pkts, task, tag, st):
    """把流重建为可播放 MP4（M08-04）

    只对看起来有视频载荷的流做，避免浪费时间。
    重建失败不阻塞主流程，错误信息记录到流上。
    """
    try:
        from ..services import rebuild
        if not pkts or len(pkts) < 5:
            return None
        out_dir = os.path.join(settings.DATA_DIR, 'rebuilt', str(task.id))
        return rebuild.rebuild_stream(pkts, out_dir, tag,
                                      duration_hint=st.duration)
    except Exception:
        log.exception('媒体流 %s 重建失败（不影响主流程）', tag)
        return None



def _tcp_time_spread(path: str, stream_id: str):
    """取某个 TCP 流的首末包相对时间，用于给 RFC4571 包分配到达时间"""
    try:
        rows = capture.extract_fields(path, ['frame.time_relative'],
                                      'tcp.stream==%s' % stream_id)
        vals = [float(r[0]) for r in rows if r and r[0]]
        if len(vals) >= 2:
            return (min(vals), max(vals))
    except Exception as e:
        # 拿不到时间范围时上层会用等间隔估算，属于降级而非失败
        # 但要留痕，否则排查时间戳问题时看不出这里降级过
        log.debug('TCP 流 %s 时间范围获取失败（%s），将用等间隔估算', stream_id, e)
    return None


def _save_stream(db: Session, task: AnalysisTask, st, key, transport,
                 meta: dict | None = None, ps=None, rb=None) -> MediaStream:
    ssrc, sip_, sport, dip, dport = key
    meta = meta or {}

    def _int(v):
        try:
            return int(v) if v else None
        except (TypeError, ValueError):
            return None

    row = MediaStream(
        task_id=task.id,
        ssrc=st.ssrc, payload_type=st.payload_type, transport=transport,
        source_ip=sip_ or meta.get('src_ip'),
        source_port=_int(sport if sport else meta.get('src_port')),
        destination_ip=dip or meta.get('dst_ip'),
        destination_port=_int(dport if dport else meta.get('dst_port')),
        start_time=st.start_time, end_time=st.end_time,
        packet_count=st.packet_count, byte_count=st.byte_count,
        payload_bytes=st.payload_bytes, duration=st.duration,
        avg_bitrate=st.avg_bitrate, peak_bitrate=st.peak_bitrate,
        seq_start=st.seq_start, seq_end=st.seq_end,
        seq_gap_count=st.seq_gap_count, seq_gap_packets=st.seq_gap_packets,
        out_of_order_count=st.out_of_order_count,
        duplicate_count=st.duplicate_count,
        clock_rate=st.clock_rate,
        jitter_avg=st.jitter_avg, jitter_max=st.jitter_max,
        max_gap=st.max_gap, interruption_count=st.interruption_count,
        # 重建成功后以 ffprobe 结果为准（比 SPS 解析可靠）
        has_video=bool(rb and rb.ok) or bool(ps and ps.video and ps.video.frame_count),
        has_audio=bool(ps and ps.audio and ps.audio.pes_count),
        codec=((rb.codec.upper() if rb and rb.codec else None)
               or (ps.video.codec if ps and ps.video else None)),
        width=((rb.width if rb and rb.width else None)
               or (ps.video.width if ps and ps.video else None)),
        height=((rb.height if rb and rb.height else None)
                or (ps.video.height if ps and ps.video else None)),
        fps=(rb.fps if rb else None),
        frame_count=((rb.frames if rb and rb.frames else None)
                     or (ps.video.frame_count if ps and ps.video else None)),
        keyframe_count=(ps.video.keyframe_count if ps and ps.video else None),
        rebuilt_path=(rb.mp4_path if rb and rb.ok else None),
        rebuild_error=(rb.error if rb and not rb.ok else None),
        extra={'notes': st.notes,
               'loss_confidence': st.loss_confidence,
               'ts_anomalies': st.ts_anomalies[:10],
               'seq_gap_events': st.seq_gap_events[:50],
               'ps': ps.to_dict() if ps else None,
               'rebuild': {
                   'ok': bool(rb and rb.ok),
                   'aligned': bool(rb and rb.aligned),
                   'poster': bool(rb and rb.poster_path),
                   'duration': rb.duration if rb else None,
                   'ps_bytes': rb.ps_bytes if rb else 0,
                   'error': rb.error if rb else None,
               } if rb else None},
    )
    db.add(row)
    db.flush()

    # 指标时间序列（抽样入库，避免库膨胀）
    for b in st.bitrate_series:
        db.add(MediaMetric(stream_id=row.id, timestamp=st.start_time + b['t'],
                           bitrate=b['kbps'], packet_count=b['packets']))
    # 抖动序列
    step = max(1, len(st.jitter_series) // 120)
    for j in st.jitter_series[::step]:
        db.add(MediaMetric(stream_id=row.id,
                           timestamp=st.start_time + j['t'],
                           jitter=j['j']))
    db.commit()
    return row


def _load_devices(db: Session, task: AnalysisTask, sip_msgs: list[dict]):
    """从 Catalog 推送与 DeviceInfo 响应中提取设备"""
    devices: dict = {}
    for m in sip_msgs:
        info = m['info']
        for it in (info.xml_items or []):
            did = it.get('DeviceID')
            if not did:
                continue
            d = devices.setdefault(did, {'id': did})
            for key, field in (('Name', 'name'), ('Event', 'event'),
                               ('Status', 'status'),
                               ('ParentID', 'parent_id'),
                               ('Manufacturer', 'manufacturer'),
                               ('Model', 'model'),
                               ('IPAddress', 'ip_address')):
                if it.get(key) and not d.get(field):
                    d[field] = it[key]
            for key, field in (('Longitude', 'longitude'),
                               ('Latitude', 'latitude')):
                if it.get(key) and field not in d:
                    try:
                        d[field] = float(it[key])
                    except (TypeError, ValueError):
                        pass

    for did, d in devices.items():
        db.add(Device(
            task_id=task.id, device_id=did,
            name=d.get('name') or '',
            parent_id=d.get('parent_id'),
            status=d.get('status'),
            manufacturer=d.get('manufacturer'),
            model=d.get('model'),
            ip_address=d.get('ip_address'),
            longitude=d.get('longitude'),
            latitude=d.get('latitude'),
            is_channel=('Channel' in (d.get('name') or '')) or
                       ('通道' in (d.get('name') or '')),
            raw={'event': d.get('event')},
        ))
    db.commit()


def _session_dict(s, sid) -> dict:
    return {
        'id': sid,
        'device_id': s.device_id,
        'channel_id': s.channel_id,
        'signal_status': s.signal_status,
        'media_status': s.media_status,
        'end_reason': s.end_reason,
        'start_time': s.start_time,
        'end_time': s.end_time,
        'negotiated_ip': s.negotiated_ip,
        'negotiated_port': s.negotiated_port,
        'negotiated_transport': s.negotiated_transport,
        'subject_ssrc': s.subject_ssrc,
        'sdp_ssrc': s.sdp_ssrc,
        'first_media_latency': s.first_media_latency,
        'call_ids': s.call_ids,
    }


def _stream_dict(r: MediaStream) -> dict:
    return {
        'id': r.id,
        'session_id': r.session_id,
        'ssrc': r.ssrc,
        'transport': r.transport,
        'start_time': r.start_time,
        'end_time': r.end_time,
        'packet_count': r.packet_count,
        'seq_gap_count': r.seq_gap_count,
        'seq_gap_packets': r.seq_gap_packets,
        'seq_gap_events': (r.extra or {}).get('seq_gap_events'),
        'jitter_avg': r.jitter_avg,
        'jitter_max': r.jitter_max,
        'max_gap': r.max_gap,
        'interruption_count': r.interruption_count,
        'has_video': r.has_video,
        'loss_confidence': (r.extra or {}).get('loss_confidence'),
        'ts_anomalies': (r.extra or {}).get('ts_anomalies'),
        'rebuild_error': r.rebuild_error,
    }


def _top_protocol(protocols: str) -> str:
    if not protocols:
        return 'unknown'
    parts = protocols.split(':')
    for key in ('sip', 'rtp', 'rtcp', 'http', 'tcp', 'udp'):
        if key in parts:
            return key.upper() if key in ('sip', 'rtp', 'rtcp', 'tcp', 'udp') else key
    return parts[-1]


def _packet_summary(p: dict) -> str:
    src = '%s:%s' % (p.get('src_ip') or '-', p.get('src_port') or '-')
    dst = '%s:%s' % (p.get('dst_ip') or '-', p.get('dst_port') or '-')
    return '%s -> %s  %s' % (src, dst, _top_protocol(p.get('protocols') or ''))


def _build_summary(task, session_rows, streams, diagnostics, packets,
                   limits) -> dict:
    sessions = [s for s, _sid in session_rows]
    total_sessions = len(sessions)
    signal_ok = sum(1 for s in sessions if s.signal_status == 'success')
    with_media = sum(1 for s in sessions if s.media_status == 'received')

    latencies = [s.first_media_latency for s in sessions
                 if s.first_media_latency is not None]
    jitters = [r.jitter_avg for r in streams if r.jitter_avg is not None]

    sev_count = {'critical': 0, 'warning': 0, 'info': 0, 'unknown': 0}
    for d in diagnostics:
        sev_count[d.severity] = sev_count.get(d.severity, 0) + 1

    return {
        'packet_count': len(packets),
        'session_count': total_sessions,
        'signal_success': signal_ok,
        'signal_success_rate': (round(signal_ok / total_sessions * 100, 1)
                                if total_sessions else None),
        'sessions_with_media': with_media,
        'media_rate': (round(with_media / total_sessions * 100, 1)
                       if total_sessions else None),
        'total_streams': len(streams),
        'avg_first_media_latency': (round(sum(latencies) / len(latencies), 3)
                                    if latencies else None),
        'avg_jitter_ms': (round(sum(jitters) / len(jitters), 2)
                          if jitters else None),
        'diagnostics': sev_count,
        'capture_warnings': len(limits),
        'analysis_scope': {
            'note': '本结果仅反映抓包点观察到的流量，'
                    '不代表端到端网络状况或客户端实际播放结果',
            'packet_count': len(packets),
        },
    }
