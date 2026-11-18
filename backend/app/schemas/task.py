#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""API 数据契约（Pydantic v2）"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------- 文件 ----------------
class FileInfo(ORMBase):
    id: int
    filename: str
    file_size: int
    file_format: str
    checksum: str
    packet_count: int | None = None
    capture_start: datetime | None = None
    capture_end: datetime | None = None
    duration: float | None = None
    link_type: str | None = None
    ip_count: int | None = None
    tcp_count: int | None = None
    udp_count: int | None = None
    warnings: list[Any] = Field(default_factory=list)


class UploadResult(BaseModel):
    task_id: int
    file_id: int
    filename: str
    size: int


# ---------------- 任务 ----------------
class TaskBrief(ORMBase):
    id: int
    name: str
    status: str
    progress: int
    stage: str | None = None
    created_at: datetime
    file_size: int | None = None
    packet_count: int | None = None
    duration: float | None = None
    session_count: int | None = None
    diagnostic_count: int | None = None
    error_message: str | None = None


class TaskDetail(TaskBrief):
    started_at: datetime | None = None
    completed_at: datetime | None = None
    configuration: dict = Field(default_factory=dict)
    summary: dict = Field(default_factory=dict)
    file: FileInfo | None = None


class TaskList(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[TaskBrief]


# ---------------- 概览 ----------------
class Overview(BaseModel):
    task_id: int
    summary: dict = Field(default_factory=dict)
    method_distribution: dict[str, int] = Field(default_factory=dict)
    code_distribution: dict[str, int] = Field(default_factory=dict)
    severity_distribution: dict[str, int] = Field(default_factory=dict)
    signal_distribution: dict[str, int] = Field(default_factory=dict)
    media_distribution: dict[str, int] = Field(default_factory=dict)
    session_types: dict[str, int] = Field(default_factory=dict)


# ---------------- 会话 ----------------
class SessionBrief(ORMBase):
    id: int
    device_id: str | None = None
    channel_id: str | None = None
    session_type: str
    start_time: float | None = None
    end_time: float | None = None
    total_duration: float | None = None
    signal_status: str
    media_status: str
    end_reason: str
    diagnostic_count: int = 0
    critical_count: int = 0
    warning_count: int = 0
    media_stream_count: int = 0


class SessionList(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[SessionBrief]


class SessionDetail(SessionBrief):
    initiator_ip: str | None = None
    receiver_ip: str | None = None
    initiator_id: str | None = None
    receiver_id: str | None = None
    invite_latency: float | None = None
    sdp_negotiation_latency: float | None = None
    first_media_latency: float | None = None
    signal_to_first_media: float | None = None
    media_duration: float | None = None
    first_keyframe_latency: float | None = None
    negotiated_ip: str | None = None
    negotiated_port: int | None = None
    negotiated_transport: str | None = None
    subject_ssrc: str | None = None
    sdp_ssrc: str | None = None
    call_ids: list[Any] = Field(default_factory=list)
    extra: dict = Field(default_factory=dict)


# ---------------- 诊断 ----------------
class DiagnosticOut(ORMBase):
    id: int
    session_id: int | None = None
    stream_id: int | None = None
    rule_id: str
    severity: str
    evidence_level: str
    timestamp: float | None = None
    title: str
    description: str
    evidence: dict = Field(default_factory=dict)
    possible_causes: list[Any] = Field(default_factory=list)
    recommendations: list[Any] = Field(default_factory=list)
    related_packet_ids: list[Any] = Field(default_factory=list)
    device_id: str | None = None


class DiagnosticList(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[DiagnosticOut]


# ---------------- 媒体 ----------------
class StreamOut(ORMBase):
    id: int
    session_id: int | None = None
    ssrc: int | None = None
    payload_type: int | None = None
    transport: str
    source_ip: str | None = None
    source_port: int | None = None
    destination_ip: str | None = None
    destination_port: int | None = None
    start_time: float
    end_time: float
    packet_count: int
    byte_count: int
    duration: float | None = None
    avg_bitrate: float | None = None
    peak_bitrate: float | None = None
    seq_gap_count: int = 0
    seq_gap_packets: int = 0
    out_of_order_count: int = 0
    duplicate_count: int = 0
    jitter_avg: float | None = None
    jitter_max: float | None = None
    max_gap: float | None = None
    interruption_count: int = 0
    has_video: bool = False
    has_audio: bool = False
    codec: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    frame_count: int | None = None
    keyframe_count: int | None = None
    rebuilt_path: str | None = None
    rebuild_error: str | None = None
    extra: dict = Field(default_factory=dict)


class StreamList(BaseModel):
    total: int
    items: list[StreamOut]


# ---------------- 报文 ----------------
class PacketOut(ORMBase):
    id: int
    packet_number: int
    timestamp: float | None = None
    source_ip: str | None = None
    destination_ip: str | None = None
    source_port: int | None = None
    destination_port: int | None = None
    transport: str | None = None
    protocol: str
    length: int
    summary: str
    call_id: str | None = None
    ssrc: int | None = None
    session_id: int | None = None


class PacketList(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[PacketOut]


class PacketDetail(PacketOut):
    raw_hex: str | None = None
    layers: list[dict] = Field(default_factory=list)
