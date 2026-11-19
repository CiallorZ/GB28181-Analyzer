#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端回归：真实抓包 -> 完整流水线 -> 入库

需要 tshark（CI 的 ubuntu-latest 自带 tshark? 否 —— 所以无 tshark 时跳过）。
样本会先复制到临时目录：流水线跑完会触发保留策略清理，
直接拿 fixtures 里的文件当 stored_path 会被删掉。
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.models.entities import (
    AnalysisTask, BusinessSession, CaptureFile, DiagnosticEvent, MediaMetric, MediaStream,
    PacketIndex, SipDialog, SipMessage, TaskStatus,
)
from app.parsers import capture
from app.services import analyzer

FIXTURES = Path(__file__).resolve().parent / 'fixtures'

pytestmark = pytest.mark.skipif(
    not capture.TSHARK, reason='需要 tshark')


def _make_task(db, tmp_path, name='sip-udp-basic.pcap'):
    src = FIXTURES / name
    dst = tmp_path / name
    shutil.copyfile(src, dst)
    task = AnalysisTask(name=name, configuration={})
    db.add(task)
    db.flush()
    db.add(CaptureFile(task_id=task.id, filename=name,
                       stored_path=str(dst), file_size=dst.stat().st_size))
    db.commit()
    db.refresh(task)
    return task, dst


def test_udp_basic_end_to_end(db, tmp_path):
    task, dst = _make_task(db, tmp_path)

    analyzer.run_analysis(db, task.id)

    db.expire_all()
    t = db.get(AnalysisTask, task.id)
    assert t.status == TaskStatus.COMPLETED, t.error_message
    assert t.stage == '完成'
    assert t.progress == 100

    s = t.summary or {}
    assert s['packet_count'] == 126
    assert s['session_count'] == 1
    assert s['sessions_with_media'] == 1

    sess = db.scalar(select(BusinessSession).where(
        BusinessSession.task_id == task.id))
    assert sess is not None
    assert sess.signal_status == 'success'
    assert sess.media_status == 'received'
    assert sess.subject_ssrc == '00001234'
    # 200 OK 的 answer 用的是非标准 a=y= 写法
    assert sess.sdp_ssrc == '00005678'
    assert sess.first_media_latency is not None
    assert abs(sess.first_media_latency - 0.24) < 0.05

    st = db.scalar(select(MediaStream).where(MediaStream.task_id == task.id))
    assert st is not None
    assert st.transport == 'UDP'
    assert st.packet_count == 120
    assert st.seq_gap_count == 0          # 连续序号不应报缺口
    assert st.session_id == sess.id

    # Dialog 也要回填会话，否则"一个会话包含哪些 Dialog"无从查询
    dialog = db.scalar(select(SipDialog).where(SipDialog.task_id == task.id))
    assert dialog is not None
    assert dialog.session_id == sess.id

    # 报文索引要能按 SSRC/会话过滤（M12）
    rtp_rows = db.scalars(
        select(PacketIndex).where(PacketIndex.task_id == task.id,
                                  PacketIndex.ssrc.is_not(None))).all()
    assert len(rtp_rows) >= 100
    assert {r.ssrc for r in rtp_rows} == {st.ssrc}
    assert {r.session_id for r in rtp_rows} == {sess.id}

    # 标准 y= 行（offer）也要能落库
    invite = db.scalar(
        select(SipMessage).where(SipMessage.task_id == task.id,
                                 SipMessage.method == 'INVITE',
                                 SipMessage.content_type == 'application/sdp')
        .order_by(SipMessage.timestamp))
    assert invite.sdp['y_ssrc'] == '00001234'
    assert invite.sdp['f_field'] == 'v/2/5/25/1/4000a/1/1a'
    answer = db.scalar(select(SipMessage).where(
        SipMessage.task_id == task.id, SipMessage.method == 'INVITE',
        SipMessage.status_code == 200))
    mismatch = db.scalar(select(DiagnosticEvent).where(
        DiagnosticEvent.task_id == task.id, DiagnosticEvent.rule_id == 'SDP-003'))
    assert mismatch.related_packet_ids == [invite.packet_id, answer.packet_id]

    # 分析本身不应动源文件（保留策略在 conftest 里已关掉）
    assert dst.exists()


def test_reanalysis_replaces_results(db, tmp_path):
    task, _dst = _make_task(db, tmp_path)
    analyzer.run_analysis(db, task.id)
    first = db.scalar(select(MediaStream).where(
        MediaStream.task_id == task.id))
    first_metrics = db.scalar(
        select(func.count()).select_from(MediaMetric)
        .where(MediaMetric.stream_id == first.id))

    analyzer.run_analysis(db, task.id)
    db.expire_all()

    streams = db.scalars(select(MediaStream).where(
        MediaStream.task_id == task.id)).all()
    assert len(streams) == 1, '重新分析应替换而非追加结果'
    assert streams[0].packet_count == 120

    # SQLite 会复用 rowid，所以不能靠 id 判断；
    # 真正要确认的是指标行没有累积成两份
    metrics = db.scalar(
        select(func.count()).select_from(MediaMetric)
        .where(MediaMetric.stream_id == streams[0].id))
    assert metrics == first_metrics, '指标行被重复写入'


def test_tcp_rfc4571_end_to_end(db, tmp_path):
    task, _dst = _make_task(db, tmp_path, 'tcp-rfc4571-media.pcap')
    analyzer.run_analysis(db, task.id)

    db.expire_all()
    t = db.get(AnalysisTask, task.id)
    assert t.status == TaskStatus.COMPLETED, t.error_message

    st = db.scalar(select(MediaStream).where(MediaStream.task_id == task.id))
    assert st is not None
    assert st.transport == 'TCP'
    assert st.packet_count >= 100
    assert st.seq_gap_count == 0


def test_tcp_sip_ports_and_empty_packets(db, tmp_path):
    """TCP 5060 的 SIP：端口不能为空，握手的空包不能入库"""
    task, _dst = _make_task(db, tmp_path, 'sip-tcp-register.pcap')
    analyzer.run_analysis(db, task.id)

    db.expire_all()
    msgs = db.scalars(select(SipMessage).where(
        SipMessage.task_id == task.id)
        .order_by(SipMessage.timestamp)).all()
    assert len(msgs) == 2, [(m.method, m.status_code) for m in msgs]
    for m in msgs:
        assert m.source_port == 5060
        assert m.destination_port == 5060
    assert msgs[0].method == 'REGISTER'
    assert msgs[1].status_code == 200
