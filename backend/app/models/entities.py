#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据模型定义（SQLAlchemy 2.0）

设计遵循 PRD 第五章，并补充 Agent 要求的关系实体：
  AnalysisTask -> CaptureFile
               -> PacketIndex
               -> SipMessage
               -> BusinessSession  (业务会话，一次点播)
                    -> SipDialog   (可能多个)
                    -> MediaStream (可能多路)
                         -> MediaMetric (时间序列指标)
                    -> DiagnosticEvent
               -> DiagnosticEvent (任务级)

关键原则：
1. 不用 Call-ID 或 SSRC 强制一对一 —— 一次业务会话可关联多个 Dialog / 多条流
2. 所有"计算不出来"的指标存 NULL，不存 0
3. 证据可追溯到 packet_id / sip_message_id / media_stream_id
"""
from __future__ import annotations

import enum
from datetime import datetime

from ..core.timeutil import utcnow

from sqlalchemy import (
    JSON, Boolean, DateTime, Enum, Float, ForeignKey, Index, Integer,
    BigInteger, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ============================================================
# 枚举
# ============================================================
class TaskStatus(str, enum.Enum):
    PENDING = 'pending'        # 待分析
    ANALYZING = 'analyzing'    # 分析中
    COMPLETED = 'completed'    # 分析完成
    FAILED = 'failed'          # 分析失败
    CANCELLED = 'cancelled'    # 已取消


class SignalStatus(str, enum.Enum):
    """信令层状态 —— 独立于媒体层"""
    SUCCESS = 'success'        # 信令建立成功
    FAILED = 'failed'          # 信令建立失败
    INCOMPLETE = 'incomplete'  # 抓到部分信令（可能是抓包不完整）
    UNKNOWN = 'unknown'


class MediaStatus(str, enum.Enum):
    """媒体层状态 —— 独立于信令层"""
    RECEIVED = 'received'      # 发现 RTP 并解出数据
    NO_MEDIA = 'no_media'      # 信令成功但没抓到 RTP
    UNDECODABLE = 'undecodable'  # 抓到 RTP 但解不出画面
    UNKNOWN = 'unknown'


class SessionEndReason(str, enum.Enum):
    NORMAL = 'normal'          # 正常 BYE
    ABNORMAL = 'abnormal'      # 异常结束
    CAPTURE_ENDED = 'capture_ended'  # 抓包结束时仍未结束
    UNKNOWN = 'unknown'


class DiagnosticSeverity(str, enum.Enum):
    CRITICAL = 'critical'
    WARNING = 'warning'
    INFO = 'info'
    UNKNOWN = 'unknown'


class EvidenceLevel(str, enum.Enum):
    """证据等级 —— PRD 1.3.3 要求区分已确认/疑似/证据不足"""
    CONFIRMED = 'confirmed'      # 已确认（报文直接证明）
    SUSPECTED = 'suspected'      # 疑似（间接推断）
    INSUFFICIENT = 'insufficient'  # 证据不足


# ============================================================
# M01 分析任务 / 抓包文件
# ============================================================
class AnalysisTask(Base):
    __tablename__ = 'analysis_task'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default='未命名任务')
    status: Mapped[str] = mapped_column(
        Enum(TaskStatus), default=TaskStatus.PENDING, index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    stage: Mapped[str] = mapped_column(String(100), default='')

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_message: Mapped[str | None] = mapped_column(Text)

    # 分析参数（列如是否解码视频、是否生成报告）
    configuration: Mapped[dict] = mapped_column(JSON, default=dict)
    # 分析结果摘要（供列表页快速展示）
    summary: Mapped[dict] = mapped_column(JSON, default=dict)

    files: Mapped[list[CaptureFile]] = relationship(
        back_populates='task', cascade='all, delete-orphan')
    sessions: Mapped[list[BusinessSession]] = relationship(
        back_populates='task', cascade='all, delete-orphan')
    diagnostics: Mapped[list[DiagnosticEvent]] = relationship(
        back_populates='task', cascade='all, delete-orphan',
        foreign_keys='DiagnosticEvent.task_id')


class CaptureFile(Base):
    """PRD M01-02 文件信息"""
    __tablename__ = 'capture_file'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey('analysis_task.id', ondelete='CASCADE'), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(512))
    file_size: Mapped[int] = mapped_column(BigInteger, default=0)
    file_format: Mapped[str] = mapped_column(String(20), default='')
    checksum: Mapped[str] = mapped_column(String(64), default='')

    # 抓包元信息
    packet_count: Mapped[int | None] = mapped_column(Integer)
    capture_start: Mapped[datetime | None] = mapped_column(DateTime)
    capture_end: Mapped[datetime | None] = mapped_column(DateTime)
    duration: Mapped[float | None] = mapped_column(Float)
    link_type: Mapped[str] = mapped_column(String(60), default='')

    ip_count: Mapped[int | None] = mapped_column(Integer)
    tcp_count: Mapped[int | None] = mapped_column(Integer)
    udp_count: Mapped[int | None] = mapped_column(Integer)

    # 解析警告（截断、加密、不完整等）
    warnings: Mapped[list] = mapped_column(JSON, default=list)

    task: Mapped[AnalysisTask] = relationship(back_populates='files')


# ============================================================
# M02 报文索引
# ============================================================
class PacketIndex(Base):
    """报文索引 —— 支撑 M12 报文查看器

    只存"定位和筛选"所需字段 + 原始字节偏移，
    协议树在查看时按需从原始文件重解析，避免数据库膨胀。
    """
    __tablename__ = 'packet_index'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey('analysis_task.id', ondelete='CASCADE'), index=True)
    file_id: Mapped[int] = mapped_column(
        ForeignKey('capture_file.id', ondelete='CASCADE'))

    packet_number: Mapped[int] = mapped_column(Integer, index=True)
    timestamp: Mapped[float | None] = mapped_column(Float, index=True)
    source_ip: Mapped[str | None] = mapped_column(String(64), index=True)
    destination_ip: Mapped[str | None] = mapped_column(String(64), index=True)
    source_port: Mapped[int | None] = mapped_column(Integer)
    destination_port: Mapped[int | None] = mapped_column(Integer)
    transport: Mapped[str | None] = mapped_column(String(10))
    protocol: Mapped[str] = mapped_column(String(20), default='')
    length: Mapped[int] = mapped_column(Integer, default=0)

    # 关联线索（便于按 Call-ID / SSRC 过滤）
    call_id: Mapped[str | None] = mapped_column(String(200), index=True)
    ssrc: Mapped[int | None] = mapped_column(BigInteger, index=True)
    session_id: Mapped[int | None] = mapped_column(Integer, index=True)

    # 定位原始字节
    file_offset: Mapped[int] = mapped_column(BigInteger, default=0)
    raw_length: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str] = mapped_column(String(300), default='')

    __table_args__ = (
        Index('ix_packet_task_number', 'task_id', 'packet_number'),
    )


# ============================================================
# M03 SIP 消息
# ============================================================
class SipMessage(Base):
    __tablename__ = 'sip_message'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey('analysis_task.id', ondelete='CASCADE'), index=True)
    packet_id: Mapped[int | None] = mapped_column(Integer, index=True)

    timestamp: Mapped[float] = mapped_column(Float, index=True)
    is_request: Mapped[bool] = mapped_column(Boolean, default=True)
    method: Mapped[str | None] = mapped_column(String(20), index=True)
    status_code: Mapped[int | None] = mapped_column(Integer, index=True)

    call_id: Mapped[str | None] = mapped_column(String(200), index=True)
    from_tag: Mapped[str | None] = mapped_column(String(100))
    to_tag: Mapped[str | None] = mapped_column(String(100))
    cseq_number: Mapped[int | None] = mapped_column(Integer)
    cseq_method: Mapped[str | None] = mapped_column(String(20))
    via_branch: Mapped[str | None] = mapped_column(String(200))

    source_ip: Mapped[str | None] = mapped_column(String(64))
    source_port: Mapped[int | None] = mapped_column(Integer)
    destination_ip: Mapped[str | None] = mapped_column(String(64))
    destination_port: Mapped[int | None] = mapped_column(Integer)

    request_uri: Mapped[str | None] = mapped_column(String(400))
    user_agent: Mapped[str | None] = mapped_column(String(200))
    contact: Mapped[str | None] = mapped_column(String(400))
    content_type: Mapped[str | None] = mapped_column(String(100))

    headers: Mapped[dict] = mapped_column(JSON, default=dict)
    body: Mapped[str | None] = mapped_column(Text)
    sdp: Mapped[dict | None] = mapped_column(JSON)      # 解析后的 SDP

    # 国标业务类型（由 XML 正文识别）
    gb_command: Mapped[str | None] = mapped_column(String(40), index=True)
    device_id: Mapped[str | None] = mapped_column(String(40), index=True)

    dialog_id: Mapped[int | None] = mapped_column(
        ForeignKey('sip_dialog.id', ondelete='SET NULL'), index=True)
    session_id: Mapped[int | None] = mapped_column(Integer, index=True)

    __table_args__ = (
        Index('ix_sip_task_time', 'task_id', 'timestamp'),
    )


class SipDialog(Base):
    """SIP Dialog —— PRD 要求不用 Call-ID 强绑会话"""
    __tablename__ = 'sip_dialog'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey('analysis_task.id', ondelete='CASCADE'), index=True)
    call_id: Mapped[str] = mapped_column(String(200), index=True)
    from_tag: Mapped[str | None] = mapped_column(String(100))
    to_tag: Mapped[str | None] = mapped_column(String(100))

    method: Mapped[str | None] = mapped_column(String(20))
    start_time: Mapped[float] = mapped_column(Float)
    end_time: Mapped[float | None] = mapped_column(Float)
    final_code: Mapped[int | None] = mapped_column(Integer)
    invite_time: Mapped[float | None] = mapped_column(Float)
    answer_time: Mapped[float | None] = mapped_column(Float)
    bye_time: Mapped[float | None] = mapped_column(Float)

    request_count: Mapped[int] = mapped_column(Integer, default=0)
    response_count: Mapped[int] = mapped_column(Integer, default=0)
    retransmission_count: Mapped[int] = mapped_column(Integer, default=0)

    session_id: Mapped[int | None] = mapped_column(
        ForeignKey('business_session.id', ondelete='SET NULL'), index=True)


# ============================================================
# M05 业务会话
# ============================================================
class BusinessSession(Base):
    """业务会话 —— 一次完整的视频点播业务

    一个会话可关联多个 SipDialog 和多条 MediaStream。
    信令状态与媒体状态分开记录（PRD 1.3.4 核心要求）。
    """
    __tablename__ = 'business_session'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey('analysis_task.id', ondelete='CASCADE'), index=True)

    device_id: Mapped[str | None] = mapped_column(String(40), index=True)
    channel_id: Mapped[str | None] = mapped_column(String(40), index=True)
    session_type: Mapped[str] = mapped_column(String(30), default='live')  # live/playback

    initiator_ip: Mapped[str | None] = mapped_column(String(64))
    receiver_ip: Mapped[str | None] = mapped_column(String(64))
    initiator_id: Mapped[str | None] = mapped_column(String(40))
    receiver_id: Mapped[str | None] = mapped_column(String(40))

    start_time: Mapped[float | None] = mapped_column(Float, index=True)
    end_time: Mapped[float | None] = mapped_column(Float)

    # 分层的状态
    signal_status: Mapped[str] = mapped_column(
        Enum(SignalStatus), default=SignalStatus.UNKNOWN, index=True)
    media_status: Mapped[str] = mapped_column(
        Enum(MediaStatus), default=MediaStatus.UNKNOWN, index=True)
    end_reason: Mapped[str] = mapped_column(
        Enum(SessionEndReason), default=SessionEndReason.UNKNOWN)

    # M05-03 耗时指标（算不出来就留空，不填 0）
    invite_latency: Mapped[float | None] = mapped_column(Float)
    sdp_negotiation_latency: Mapped[float | None] = mapped_column(Float)
    first_media_latency: Mapped[float | None] = mapped_column(Float)
    signal_to_first_media: Mapped[float | None] = mapped_column(Float)
    media_duration: Mapped[float | None] = mapped_column(Float)
    total_duration: Mapped[float | None] = mapped_column(Float)
    first_keyframe_latency: Mapped[float | None] = mapped_column(Float)

    # 协商参数（来自 SDP）
    negotiated_ip: Mapped[str | None] = mapped_column(String(64))
    negotiated_port: Mapped[int | None] = mapped_column(Integer)
    negotiated_transport: Mapped[str | None] = mapped_column(String(20))
    subject_ssrc: Mapped[str | None] = mapped_column(String(20))
    sdp_ssrc: Mapped[str | None] = mapped_column(String(20))

    # 统计
    media_stream_count: Mapped[int] = mapped_column(Integer, default=0)
    diagnostic_count: Mapped[int] = mapped_column(Integer, default=0)
    critical_count: Mapped[int] = mapped_column(Integer, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, default=0)

    # 元数据
    call_ids: Mapped[list] = mapped_column(JSON, default=list)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)

    task: Mapped[AnalysisTask] = relationship(back_populates='sessions')
    streams: Mapped[list[MediaStream]] = relationship(
        back_populates='session', cascade='all, delete-orphan')
    dialogs: Mapped[list[SipDialog]] = relationship(
        primaryjoin='SipDialog.session_id == BusinessSession.id',
        viewonly=True)


# ============================================================
# M07 媒体流与指标
# ============================================================
class MediaStream(Base):
    __tablename__ = 'media_stream'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey('analysis_task.id', ondelete='CASCADE'), index=True)
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey('business_session.id', ondelete='SET NULL'), index=True)

    ssrc: Mapped[int | None] = mapped_column(BigInteger, index=True)
    payload_type: Mapped[int | None] = mapped_column(Integer)
    transport: Mapped[str] = mapped_column(String(10), default='UDP')

    source_ip: Mapped[str | None] = mapped_column(String(64))
    source_port: Mapped[int | None] = mapped_column(Integer)
    destination_ip: Mapped[str | None] = mapped_column(String(64))
    destination_port: Mapped[int | None] = mapped_column(Integer)

    start_time: Mapped[float] = mapped_column(Float, index=True)
    end_time: Mapped[float] = mapped_column(Float)

    # 基础统计
    packet_count: Mapped[int] = mapped_column(Integer, default=0)
    byte_count: Mapped[int] = mapped_column(BigInteger, default=0)
    payload_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    duration: Mapped[float | None] = mapped_column(Float)
    avg_bitrate: Mapped[float | None] = mapped_column(Float)
    peak_bitrate: Mapped[float | None] = mapped_column(Float)

    # 序列号分析（区分"观察到的缺口"与"确认丢包"）
    seq_start: Mapped[int | None] = mapped_column(Integer)
    seq_end: Mapped[int | None] = mapped_column(Integer)
    seq_gap_count: Mapped[int] = mapped_column(Integer, default=0)
    seq_gap_packets: Mapped[int] = mapped_column(Integer, default=0)
    out_of_order_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)

    # 抖动（RFC 3550）
    clock_rate: Mapped[int | None] = mapped_column(Integer)
    jitter_avg: Mapped[float | None] = mapped_column(Float)
    jitter_max: Mapped[float | None] = mapped_column(Float)

    # 中断分析
    max_gap: Mapped[float | None] = mapped_column(Float)
    interruption_count: Mapped[int] = mapped_column(Integer, default=0)

    # 编码信息（M08，P1 实现，P0 记录识别结果）
    codec: Mapped[str | None] = mapped_column(String(20))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    fps: Mapped[float | None] = mapped_column(Float)
    frame_count: Mapped[int | None] = mapped_column(Integer)
    keyframe_count: Mapped[int | None] = mapped_column(Integer)
    has_video: Mapped[bool] = mapped_column(Boolean, default=False)
    has_audio: Mapped[bool] = mapped_column(Boolean, default=False)

    # 重建产物
    rebuilt_path: Mapped[str | None] = mapped_column(String(512))
    rebuild_error: Mapped[str | None] = mapped_column(Text)

    extra: Mapped[dict] = mapped_column(JSON, default=dict)

    session: Mapped[BusinessSession | None] = relationship(back_populates='streams')
    metrics: Mapped[list[MediaMetric]] = relationship(
        back_populates='stream', cascade='all, delete-orphan')


class MediaMetric(Base):
    """时间序列指标 —— 支撑 M07-04 六张趋势图"""
    __tablename__ = 'media_metric'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stream_id: Mapped[int] = mapped_column(
        ForeignKey('media_stream.id', ondelete='CASCADE'), index=True)

    timestamp: Mapped[float] = mapped_column(Float)
    bitrate: Mapped[float | None] = mapped_column(Float)
    packet_count: Mapped[int] = mapped_column(Integer, default=0)
    sequence_gap_count: Mapped[int] = mapped_column(Integer, default=0)
    jitter: Mapped[float | None] = mapped_column(Float)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    out_of_order_count: Mapped[int] = mapped_column(Integer, default=0)
    interarrival_gap: Mapped[float | None] = mapped_column(Float)

    stream: Mapped[MediaStream] = relationship(back_populates='metrics')

    __table_args__ = (
        Index('ix_metric_stream_time', 'stream_id', 'timestamp'),
    )


# ============================================================
# M09 诊断事件
# ============================================================
class DiagnosticEvent(Base):
    __tablename__ = 'diagnostic_event'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey('analysis_task.id', ondelete='CASCADE'), index=True)
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey('business_session.id', ondelete='SET NULL'), index=True)
    stream_id: Mapped[int | None] = mapped_column(Integer)

    rule_id: Mapped[str] = mapped_column(String(40), index=True)
    severity: Mapped[str] = mapped_column(
        Enum(DiagnosticSeverity), default=DiagnosticSeverity.INFO, index=True)
    evidence_level: Mapped[str] = mapped_column(
        Enum(EvidenceLevel), default=EvidenceLevel.SUSPECTED)

    timestamp: Mapped[float | None] = mapped_column(Float)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default='')

    # PRD M09-03 要求的结构化字段
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    possible_causes: Mapped[list] = mapped_column(JSON, default=list)
    recommendations: Mapped[list] = mapped_column(JSON, default=list)
    related_packet_ids: Mapped[list] = mapped_column(JSON, default=list)

    device_id: Mapped[str | None] = mapped_column(String(40))

    task: Mapped[AnalysisTask] = relationship(
        back_populates='diagnostics', foreign_keys=[task_id])


# ============================================================
# 设备与通道（M11 拓扑）
# ============================================================
class Device(Base):
    __tablename__ = 'device'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey('analysis_task.id', ondelete='CASCADE'), index=True)
    device_id: Mapped[str] = mapped_column(String(40), index=True)
    name: Mapped[str] = mapped_column(String(200), default='')
    parent_id: Mapped[str | None] = mapped_column(String(40), index=True)
    status: Mapped[str | None] = mapped_column(String(10))
    manufacturer: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(100))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    longitude: Mapped[float | None] = mapped_column(Float)
    latitude: Mapped[float | None] = mapped_column(Float)
    is_channel: Mapped[bool] = mapped_column(Boolean, default=False)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)

    __table_args__ = (
        UniqueConstraint('task_id', 'device_id', name='uq_task_device'),
    )


class Endpoint(Base):
    """网络端点 —— M11 拓扑节点"""
    __tablename__ = 'endpoint'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey('analysis_task.id', ondelete='CASCADE'), index=True)
    ip: Mapped[str] = mapped_column(String(64), index=True)
    port: Mapped[int | None] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(30), default='unknown')
    packet_count: Mapped[int] = mapped_column(Integer, default=0)
    byte_count: Mapped[int] = mapped_column(BigInteger, default=0)
    device_id: Mapped[str | None] = mapped_column(String(40))


class Report(Base):
    """M13 报告"""
    __tablename__ = 'report'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey('analysis_task.id', ondelete='CASCADE'), index=True)
    format: Mapped[str] = mapped_column(String(10), default='html')
    path: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    size: Mapped[int] = mapped_column(Integer, default=0)
