# -*- coding: utf-8 -*-
"""分析报告导出（Markdown / JSON）

只读现有分析结果，不重新计算：报告里出现的每个数字都必须能在页面上找到，
否则用户会拿两份不一致的结论去对账。
"""
from __future__ import annotations

import json

from ..schemas import task as S

SEV_LABEL = {'critical': '严重', 'warning': '警告', 'info': '提示',
             'unknown': '未知'}
LEVEL_LABEL = {'confirmed': '已确认', 'suspected': '疑似', 'unknown': '未知'}
# 枚举直接 f-string 会输出 SignalStatus.SUCCESS 这种名字，报告里必须转中文
SIGNAL_LABEL = {'success': '成功', 'failed': '失败',
                'incomplete': '不完整', 'unknown': '未知'}
MEDIA_LABEL = {'received': '已收到', 'no_media': '无媒体',
               'undecodable': '无法解码', 'unknown': '未知'}


def _sec(v):
    return '—' if v is None else '%.3fs' % v


def _num(v, digits=2):
    return '—' if v is None else ('%.' + str(digits) + 'f') % v


def _label(table, v):
    return table.get(getattr(v, 'value', v), str(v))


def _time(v):
    return v.strftime('%Y-%m-%d %H:%M:%S') if v else '—'


def _bytes(n):
    if not n:
        return '0 B'
    units = ['B', 'KB', 'MB', 'GB']
    i = 0
    v = float(n)
    while v >= 1024 and i < len(units) - 1:
        v /= 1024
        i += 1
    return '%.1f %s' % (v, units[i])


def _cell(v):
    """表格单元格：竖线会把 Markdown 表格拆坏"""
    if v is None or v == '':
        return '—'
    return str(v).replace('|', '\\|').replace('\n', ' ')


def _evidence_lines(ev: dict) -> list[str]:
    out = []
    for k, v in (ev or {}).items():
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False)
        out.append('- %s：%s' % (k, v))
    return out


def build_markdown(task, file, sessions, streams, diagnostics) -> str:
    summary = task.summary or {}
    diag = summary.get('diagnostics') or {}
    lines = []
    add = lines.append

    add('# GB28181 抓包分析报告')
    add('')
    add('- 文件：%s' % (file.filename if file else '—'))
    add('- 文件大小：%s' % _bytes(file.file_size if file else 0))
    add('- 报文数：%s（抓包时长 %s）'
        % (summary.get('packet_count', 0), _sec(file.duration if file else None)))
    add('- 任务：#%s，分析完成于 %s' % (task.id, _time(task.completed_at)))
    add('')

    add('## 一、结论摘要')
    add('')
    add('| 指标 | 数值 |')
    add('|---|---|')
    add('| 点播会话 | %s |' % summary.get('session_count', 0))
    rate = summary.get('signal_success_rate')
    add('| 信令建立成功率 | %s |'
        % ('—' if rate is None else '%.1f%%' % rate))
    add('| 发现媒体的会话 | %s / %s |'
        % (summary.get('sessions_with_media', 0), summary.get('session_count', 0)))
    add('| RTP 流 | %s |' % summary.get('total_streams', 0))
    add('| 异常事件 | %s 严重 · %s 警告 · %s 提示 |'
        % (diag.get('critical', 0), diag.get('warning', 0), diag.get('info', 0)))
    add('| 首媒体包耗时 | %s |' % _sec(summary.get('avg_first_media_latency')))
    add('| RTP 平均抖动 | %s ms |' % _num(summary.get('avg_jitter_ms'), 2))
    add('')

    add('## 二、信令会话')
    add('')
    if sessions:
        add('| # | 设备 | 通道 | 开始 | 时长 | 信令 | 媒体 | 诊断 |')
        add('|---|---|---|---|---|---|---|---|')
        for i, s in enumerate(sessions, 1):
            add('| %d | %s | %s | %s | %s | %s | %s | %s |' % (
                i, _cell(s.device_id), _cell(s.channel_id),
                _sec(s.start_time), _sec(s.total_duration),
                _label(SIGNAL_LABEL, s.signal_status),
                _label(MEDIA_LABEL, s.media_status), s.diagnostic_count))
    else:
        add('未解析到 SIP 会话（抓包中可能不含信令）。')
    add('')

    add('## 三、媒体流')
    add('')
    if streams:
        add('| SSRC | 传输 | 包数 | 码率 | 抖动 | 丢包段 | 编码 | 分辨率 |')
        add('|---|---|---|---|---|---|---|---|')
        for st in streams:
            ssrc = '%08x' % st.ssrc if st.ssrc else '—'
            res = ('%d×%d' % (st.width, st.height)
                   if st.width and st.height else '—')
            add('| %s | %s | %d | %s kbps | %s ms | %d | %s | %s |' % (
                ssrc, st.transport, st.packet_count,
                _num(st.avg_bitrate, 1), _num(st.jitter_avg, 2),
                st.seq_gap_count, _cell(st.codec), res))
    else:
        add('未识别到 RTP 媒体流。')
    add('')

    add('## 四、诊断明细')
    add('')
    if diagnostics:
        order = {'critical': 0, 'warning': 1, 'info': 2, 'unknown': 3}
        for d in sorted(diagnostics, key=lambda x: order.get(x.severity, 9)):
            add('### [%s] %s %s' % (SEV_LABEL.get(d.severity, d.severity),
                                    d.rule_id, d.title))
            add('')
            add(d.description or '')
            add('')
            add('- 证据等级：%s' % LEVEL_LABEL.get(d.evidence_level,
                                                 d.evidence_level))
            if d.device_id:
                add('- 设备：%s' % d.device_id)
            if d.timestamp is not None:
                add('- 时间：%s' % _sec(d.timestamp))
            ev = _evidence_lines(d.evidence)
            if ev:
                add('')
                add('**证据**')
                add('')
                lines.extend(ev)
            if d.possible_causes:
                add('')
                add('**可能原因**')
                add('')
                lines.extend('- %s' % c for c in d.possible_causes)
            if d.recommendations:
                add('')
                add('**建议**')
                add('')
                lines.extend('- %s' % c for c in d.recommendations)
            add('')
    else:
        add('规则引擎未在该任务中检测到异常。')
        add('')

    add('## 五、分析范围')
    add('')
    add('本报告只反映抓包点观察到的流量，不代表端到端网络状况，'
        '也不代表客户端实际播放结果。')
    add('')
    add('信令显示成功不等于画面正常：码流能否解码、丢包发生在哪一段，'
        '需要结合媒体指标与诊断结论判断。')
    add('')
    add('报告中「—」表示该指标无法从抓包中计算，不是 0。')
    add('')
    return '\n'.join(lines)


def build_payload(task, file, sessions, streams, diagnostics) -> dict:
    """机器可读版本：字段与接口返回保持一致，方便二次处理"""
    return {
        'task': {
            'id': task.id,
            'name': task.name,
            'status': task.status,
            'completed_at': (task.completed_at.isoformat()
                             if task.completed_at else None),
        },
        'file': {
            'filename': file.filename if file else None,
            'size': file.file_size if file else None,
            'duration': file.duration if file else None,
            'packet_count': file.packet_count if file else None,
        },
        'summary': task.summary or {},
        'sessions': [S.SessionBrief.model_validate(s).model_dump()
                     for s in sessions],
        'streams': [S.StreamOut.model_validate(st).model_dump()
                    for st in streams],
        'diagnostics': [S.DiagnosticOut.model_validate(d).model_dump()
                        for d in diagnostics],
    }
