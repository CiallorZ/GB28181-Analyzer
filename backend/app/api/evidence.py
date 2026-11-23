"""On-demand topology, RTCP receiver reports and media capture export."""
import ipaddress
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from ..core.db import get_db
from ..models.entities import AnalysisTask, Device, MediaStream, SipMessage
from ..parsers import capture

router = APIRouter()


def source(db, task_id):
    task = db.get(AnalysisTask, task_id)
    if not task or not task.files or not Path(task.files[0].stored_path).is_file():
        raise HTTPException(404, '原始抓包不可用')
    return task.files[0].stored_path


def tshark(args):
    if not capture.TSHARK:
        raise HTTPException(503, '需要 TShark')
    try:
        result = capture._run([capture.TSHARK, *args], 120, '抓包证据读取')
    except capture.CaptureError as e:
        raise HTTPException(503, str(e)) from e
    if result.returncode:
        raise HTTPException(422, 'TShark 未能读取抓包')
    return result.stdout


@router.get('/tasks/{task_id}/topology')
def topology(task_id: int, db: Session = Depends(get_db)):
    if not db.get(AnalysisTask, task_id):
        raise HTTPException(404, '任务不存在')
    edges = []
    for entity, protocol in [(SipMessage, 'SIP'), (MediaStream, 'RTP')]:
        src, dst = entity.source_ip, entity.destination_ip
        count = func.count() if protocol == 'SIP' else func.sum(entity.packet_count)
        rows = db.execute(select(src, dst, count).where(entity.task_id == task_id)
                          .group_by(src, dst).order_by(count.desc()))
        edges.extend(dict(source=a, target=b, label=protocol, count=n) for a, b, n in rows)
    devices = db.scalars(select(Device).where(Device.task_id == task_id))
    edges.extend(dict(source=d.parent_id, target=d.device_id, label='目录', count=None)
                 for d in devices if d.parent_id)
    return edges


@router.get('/tasks/{task_id}/rtcp')
def rtcp(task_id: int, db: Session = Depends(get_db)):
    fields = ['frame.number', 'rtcp.ssrc.identifier', 'rtcp.ssrc.fraction',
              'rtcp.ssrc.cum_nr', 'rtcp.ssrc.jitter', 'rtcp.roundtrip-delay']
    output = tshark(['-n', '-2', '-r', source(db, task_id), '-Y', 'rtcp.ssrc.fraction',
                     '-T', 'fields', *(x for f in fields for x in ('-e', f))])
    reports = []
    for line in output.splitlines():
        frame, identifiers, fractions, losses, jitters, delay = line.split('\t')
        for identifier, fraction, lost, jitter in zip(identifiers.split(','),
                                                      fractions.split(','),
                                                      losses.split(','), jitters.split(',')):
            reports.append(dict(frame=int(frame), ssrc=identifier, loss=round(int(fraction)*100/256, 2),
                                lost=lost, jitter=jitter, delay=delay or None))
    return reports


@router.get('/streams/{stream_id}/capture')
def stream_capture(stream_id: int, db: Session = Depends(get_db)):
    stream = db.get(MediaStream, stream_id)
    if not stream or not all((stream.source_ip, stream.destination_ip, stream.destination_port, stream.source_port)):
        raise HTTPException(404, '缺少媒体端点')
    path = source(db, stream.task_id)
    proto = stream.transport.lower()
    if proto not in ('tcp', 'udp'):
        raise HTTPException(422, '不支持的传输协议')
    src, dst = ipaddress.ip_address(stream.source_ip), ipaddress.ip_address(stream.destination_ip)
    ip = 'ip' if src.version == 4 else 'ipv6'
    expr = (f'{ip}.src == {src} && {ip}.dst == {dst} && '
            f'{proto}.srcport == {stream.source_port} && {proto}.dstport == {stream.destination_port}')
    decode = []
    if proto == 'udp':
        if stream.ssrc is None:
            raise HTTPException(422, '缺少 SSRC')
        decode = ['-d', f'udp.port=={stream.destination_port},rtp']
        expr += f' && rtp.ssrc == {stream.ssrc}'
    fd, dest = tempfile.mkstemp(suffix='.pcapng')
    os.close(fd)
    try:
        tshark(['-n', '-r', path, *decode, '-Y', expr, '-w', dest])
        return FileResponse(dest, filename=f'{proto}-{stream_id}.pcapng',
                            background=BackgroundTask(os.unlink, dest))
    except BaseException:
        os.unlink(dest)
        raise
