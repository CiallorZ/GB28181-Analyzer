#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DeepSeek AI 分析（P2 功能，但接口层已就绪）

安全边界（PRD 明令）：
- 只发送**解析后的结构化摘要**，绝不发送抓包原始字节
- 摘要隐藏文件名、设备 ID、协商地址与自由文本；不发送报文原文
- Key 只存本机文件，不回传给前端明文
"""
from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request

from sqlalchemy import func

from ..core.config import settings
from ..core.security import validate_ai_base_url
from ..models.entities import (
    AnalysisTask, BusinessSession, DiagnosticEvent, MediaStream, SipMessage,
)
from .diagnosis import RULES, severity_order_clause

DEFAULT_BASE = 'https://api.deepseek.com'
DEFAULT_MODEL = 'deepseek-flash'


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """不跟随重定向：urllib 默认会把 Authorization 头带到重定向目标，
    若网关（或其被劫持后）返回 30x，就会把 API Key 送给第三方。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None
AI_TIMEOUT = 180
CONFIG_PATH = settings.DATA_DIR / 'ai_config.json'


# ---------------------------------------------------------------
# 配置读写
# ---------------------------------------------------------------
def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, encoding='utf-8') as f:
                cfg = json.load(f)
            if isinstance(cfg, dict):
                return cfg
        except Exception:
            pass
    return {}


def save_config(cfg: dict) -> None:
    """原子写入，文件权限 0600（含 API Key，避免同机其他用户读取）"""
    tmp = str(CONFIG_PATH) + '.tmp'
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    try:
        os.chmod(tmp, 0o600)      # 临时文件已存在时 os.open 的 mode 不生效
    except OSError:
        pass                      # Windows 等不支持 POSIX 权限的平台
    os.replace(tmp, CONFIG_PATH)


def _api_key(cfg: dict) -> str:
    """优先使用环境变量 DEEPSEEK_API_KEY（不落盘），其次配置文件"""
    return (os.environ.get('DEEPSEEK_API_KEY') or cfg.get('api_key') or '').strip()


def public_config() -> dict:
    """给前端的配置（key 脱敏）"""
    cfg = load_config()
    key = _api_key(cfg)
    hint = ''
    if key:
        hint = '****' + key[-4:] if len(key) > 8 else '****'
    return {
        'has_key': bool(key),
        'key_hint': hint,
        'model': cfg.get('model') or DEFAULT_MODEL,
        'base_url': cfg.get('base_url') or DEFAULT_BASE,
    }


# ---------------------------------------------------------------
# 上下文构建（只发摘要，不发原文）
# ---------------------------------------------------------------
def _enum_val(v) -> str:
    """枚举值转成人类/AI 可读的字符串（避免 SignalStatus.SUCCESS 这种）"""
    if v is None:
        return '未知'
    return getattr(v, 'value', str(v))


def build_context(db, task_id: int) -> str:
    task = db.get(AnalysisTask, task_id)
    if not task:
        return ''
    s = task.summary or {}
    cf = task.files[0] if task.files else None

    lines = []
    lines.append('## 抓包基本信息')
    if cf:
        lines.append('- 文件名：已隐藏')
        lines.append('- 报文总数：%s' % (cf.packet_count if cf.packet_count is not None else '未知'))
        lines.append('- 抓包时长：%s 秒' % (round(cf.duration, 3)
                                        if cf.duration is not None else '未知'))
        lines.append('- 链路类型：%s' % (cf.link_type or '未知'))
        if cf.warnings:
            lines.append('- 解析警告：%d 条（详情已隐藏）' % len(cf.warnings))

    lines.append('')
    lines.append('## 总体统计')
    lines.append('- 点播会话：%s 个' % s.get('session_count', 0))
    lines.append('- 信令成功率：%s' % (
        '%s%%' % s['signal_success_rate']
        if s.get('signal_success_rate') is not None else '无法计算'))
    lines.append('- 发现媒体会话：%s 个' % s.get('sessions_with_media', 0))
    lines.append('- 媒体流条数：%s' % s.get('total_streams', 0))
    if s.get('avg_first_media_latency') is not None:
        lines.append('- 平均首媒体耗时：%s 秒' % s['avg_first_media_latency'])
    else:
        lines.append('- 平均首媒体耗时：无法计算（无媒体流）')
    if s.get('avg_first_keyframe_latency') is not None:
        lines.append('- 平均首关键帧耗时（估算）：%s 秒'
                     % s['avg_first_keyframe_latency'])
    if s.get('avg_jitter_ms') is not None:
        lines.append('- 平均 RTP 抖动：%s ms' % s['avg_jitter_ms'])

    # 会话明细（最多 8 个）
    sessions = (db.query(BusinessSession)
                .filter(BusinessSession.task_id == task_id)
                .order_by(BusinessSession.start_time)
                .limit(8).all())
    session_total = db.query(func.count(BusinessSession.id)).filter(
        BusinessSession.task_id == task_id).scalar() or 0
    if sessions:
        lines.append('')
        lines.append('## 点播会话（列出 %d / %d 个，按开始时间）' % (len(sessions), session_total))
        devices = {}
        addresses = {}
        for x in sessions:
            dur = ('%.2fs' % x.total_duration) if x.total_duration is not None else '未知'
            fml = ('%.3fs' % x.first_media_latency
                   if x.first_media_latency is not None else '无法计算')
            if x.device_id:
                devices.setdefault(x.device_id, '设备%d' % (len(devices) + 1))
            if x.negotiated_ip:
                addresses.setdefault(x.negotiated_ip, '地址%d' % (len(addresses) + 1))
            lines.append(
                '- 会话#%d 设备=%s 信令=%s 媒体=%s 结束=%s 时长=%s '
                '端口=%s:%s/%s Subject_SSRC=%s SDP_y_SSRC=%s 首媒体=%s '
                '首关键帧=%s'
                % (x.id, devices.get(x.device_id, '未知'), _enum_val(x.signal_status),
                   _enum_val(x.media_status), _enum_val(x.end_reason), dur,
                   addresses.get(x.negotiated_ip, '未知'), x.negotiated_port or '?',
                   x.negotiated_transport or '?',
                   x.subject_ssrc or '空', x.sdp_ssrc or '空', fml,
                   ('%.3fs' % x.first_keyframe_latency
                    if x.first_keyframe_latency is not None else '无法计算')))

    # 媒体流明细
    streams = (db.query(MediaStream)
               .filter(MediaStream.task_id == task_id)
               .order_by(MediaStream.id)
               .limit(8).all())
    stream_total = db.query(func.count(MediaStream.id)).filter(
        MediaStream.task_id == task_id).scalar() or 0
    if streams:
        lines.append('')
        lines.append('## 媒体流（列出 %d / %d 条）' % (len(streams), stream_total))
        for r in streams:
            lines.append(
                '- SSRC=%s %s %s→%s 包数=%d 码率=%s kbps 抖动=%s ms '
                '序号缺口=%d包 乱序=%d 最大静默=%ss' % (
                    ('未知' if r.ssrc is None else f'0x{r.ssrc:08x}'), r.transport,
                    r.source_port or '?', r.destination_port or '?',
                    r.packet_count,
                    r.avg_bitrate if r.avg_bitrate is not None else '未知',
                    r.jitter_avg if r.jitter_avg is not None else '未知',
                    r.seq_gap_packets, r.out_of_order_count,
                    r.max_gap if r.max_gap is not None else '未知'))

    # 诊断
    events = (db.query(DiagnosticEvent)
              .filter(DiagnosticEvent.task_id == task_id)
              .order_by(severity_order_clause(DiagnosticEvent.severity), DiagnosticEvent.timestamp,
                        DiagnosticEvent.id)
              .limit(30).all())
    event_total = db.query(func.count(DiagnosticEvent.id)).filter(
        DiagnosticEvent.task_id == task_id).scalar() or 0
    if events:
        lines.append('')
        lines.append('## 诊断结论（列出 %d / %d 条，按严重程度）' % (len(events), event_total))
        for e in events:
            lines.append('- [%s][%s] %s %s（详细描述已隐藏）' % (
                _enum_val(e.severity), _enum_val(e.evidence_level), e.rule_id,
                RULES.get(e.rule_id, '未知规则')))

    # SIP 概况
    sip_total = db.query(func.count(SipMessage.id)).filter(SipMessage.task_id == task_id).scalar() or 0
    if sip_total:
        methods = (db.query(SipMessage.method, func.count(SipMessage.id))
                   .filter(SipMessage.task_id == task_id, SipMessage.is_request.is_(True),
                           SipMessage.method.is_not(None))
                   .group_by(SipMessage.method).all())
        codes = (db.query(SipMessage.status_code, func.count(SipMessage.id))
                 .filter(SipMessage.task_id == task_id, SipMessage.is_request.is_not(True),
                         SipMessage.status_code.is_not(None))
                 .group_by(SipMessage.status_code).all())
        lines.append('')
        lines.append('## SIP 概况')
        lines.append('- 消息总数：%d' % sip_total)
        lines.append('- 方法分布：%s' % ', '.join(
            '%s×%d' % (k, v) for k, v in sorted(methods)))
        lines.append('- 响应码分布：%s' % ', '.join(
            '%s×%d' % (k, v) for k, v in sorted(codes)))

    lines.append('')
    lines.append('## 分析局限（必须遵守）')
    lines.append('- 以上数据仅来自单一抓包点，不代表端到端网络状况')
    lines.append('- SIP 成功不等于媒体成功，更不等于客户端看到画面')
    lines.append('- 视频重建结果不等于客户端实际播放成功；缺少播放证据时不能判断客户端是否看到画面')
    lines.append('- 无法计算的指标已明确标注，不要臆造数值')
    lines.append('- 摘要可能只列出部分会话、媒体流和诊断；不能将未列出的内容视为不存在')
    lines.append('- 文件名、设备标识、协商地址和自由文本已隐藏；设备与地址别名仅在本摘要内有效')

    return '\n'.join(lines)


SYSTEM_PROMPT = '''你是一名资深的 GB/T 28181 视频监控联网与国标级联排查专家。
用户会给你一份由抓包分析平台生成的结构化摘要，请据此给出故障定位报告。

要求：
1. 只使用摘要中给出的数据。摘要里没有的信息，明确说"数据不足以判断"
2. 区分三个层面：信令是否建立、媒体是否传输、画面是否可播放。
   不要把 SIP 200 OK 当成播放成功
3. 引用具体数值时精确引用；设备与地址使用摘要中的别名，不能猜测原始值
4. 结论要能追溯到摘要中的证据；给出判断依据
5. 用 Markdown 组织，结构清晰但不要过度分层
6. 篇幅控制在 700 字以内，信息密度优先
7. 不要用"可能"、"也许"来回避判断——能确定就直说，不能确定就说明缺什么证据

输出结构建议：
## 结论
一句话说明最可能的问题定位。

## 证据链
按信令层 / 媒体层 / 编码层分段列出关键证据。

## 处置建议
按优先级排序，每条写清"做什么"和"怎么验证"。

## 数据不足的地方
明确列出需要补充哪些信息才能进一步定位。'''

CHAT_SUFFIX = '''

## 对话模式
用户会在报告基础上继续追问。请：
- 直接回答问题，不要重复整份报告
- 需要数据时精确引用摘要中的字段值
- 超出证据范围时明确指出需要什么额外信息
- 回答简洁，除非用户要求展开'''

MAX_HISTORY = 12


# ---------------------------------------------------------------
# 调用
# ---------------------------------------------------------------
def _post(body: dict, on_delta=None) -> str:
    cfg = load_config()
    key = _api_key(cfg)
    if not key:
        raise RuntimeError('尚未配置 DeepSeek API Key')

    # 发送前再校验一次：配置文件可能是旧版本写入、或被手工改过
    try:
        base = validate_ai_base_url(cfg.get('base_url') or DEFAULT_BASE)
    except ValueError as e:
        raise RuntimeError('AI 网关地址不安全，已拒绝发送：%s' % e)
    url = base + '/chat/completions'
    data = json.dumps(body, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(url, data=data, method='POST')
    req.add_header('Content-Type', 'application/json')
    req.add_header('Authorization', 'Bearer ' + key)
    req.add_header('Accept', 'text/event-stream' if on_delta else 'application/json')

    try:
        opener = urllib.request.build_opener(
            _NoRedirect(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        resp = opener.open(req, timeout=AI_TIMEOUT)
    except urllib.error.HTTPError as e:
        detail = ''
        try:
            detail = e.read().decode('utf-8', 'replace')[:300]
        except Exception:
            pass
        if e.code == 401:
            raise RuntimeError('API Key 无效或已过期（401）')
        if e.code == 402:
            raise RuntimeError('账户余额不足（402）')
        if e.code == 429:
            raise RuntimeError('请求过于频繁，请稍后重试（429）')
        raise RuntimeError('DeepSeek 返回 %s：%s' % (e.code, detail))
    except urllib.error.URLError as e:
        raise RuntimeError('无法连接 DeepSeek：%s'
                           % getattr(e, 'reason', e))

    if not on_delta:
        try:
            j = json.loads(resp.read().decode('utf-8', 'replace'))
            return j['choices'][0]['message']['content']
        except Exception as e:
            raise RuntimeError('解析响应失败：%s' % e)
        finally:
            resp.close()

    parts = []
    completed = False
    try:
        for raw in resp:
            line = raw.decode('utf-8', 'replace').strip()
            if not line.startswith('data:'):
                continue
            chunk = line[5:].strip()
            if chunk == '[DONE]':
                completed = True
                break
            try:
                j = json.loads(chunk)
                delta = j['choices'][0]['delta'].get('content') or ''
            except (json.JSONDecodeError, KeyError, IndexError):
                # 流式分块可能被截断，跳过坏块继续读是正确行为
                continue
            if delta:
                parts.append(delta)
                try:
                    on_delta(delta)
                except Exception:
                    pass
    finally:
        resp.close()

    if not completed:
        raise RuntimeError('模型连接中断，响应不完整，请重试')
    text = ''.join(parts)
    if not text.strip():
        raise RuntimeError('模型没有返回内容')
    return text


EXPERTS = {
    'general': '综合研判：先给结论，再列信令与媒体的交叉证据和最短验证路径。每条结论标注已观测或待验证，只引用摘要中存在的会话、流或报文标识。',
    'sip': '信令专家：按事务与方向核对 INVITE、最终响应、ACK 和 BYE。按 Call-ID 和 CSeq 区分重传、未观察到响应与明确拒绝，注明抓包窗口边界。',
    'media': '媒体专家：核对 SDP 和 RTP 的地址、端口、SSRC 与方向，再对照序号缺口、编码和重建结果。',
    'field': '现场排障专家：给出按优先级排列的检查步骤，每步注明检查端、预期观测和下一步分支。'
}


def analyze(db, task_id: int, on_delta=None, context=None, expert='general') -> str:
    cfg = load_config()
    ctx = context if context is not None else build_context(db, task_id)
    if not ctx.strip():
        raise RuntimeError('没有可供分析的数据')

    body = {
        'model': cfg.get('model') or DEFAULT_MODEL,
        'messages': [
            {'role': 'system', 'content': SYSTEM_PROMPT + '\n' + EXPERTS[expert]},
            {'role': 'user',
             'content': '以下是抓包分析摘要，请给出排查报告：\n\n' + ctx},
        ],
        'max_tokens': 2200,
        'stream': bool(on_delta),
        # deepseek-flash 默认开启 thinking：只输出 reasoning_content，
        # content 为空，前端会看到"模型没有返回内容"。显式关闭。
        # 注意 thinking 模式不支持 temperature 等采样参数，故不传。
        'thinking': {'type': 'disabled'},
    }
    return _post(body, on_delta)


def chat(db, task_id: int, history: list, question: str, on_delta=None, context=None, expert='general') -> str:
    if not (question or '').strip():
        raise RuntimeError('问题不能为空')

    cfg = load_config()
    ctx = context if context is not None else build_context(db, task_id)

    msgs = [
        {'role': 'system', 'content': SYSTEM_PROMPT + '\n' + EXPERTS[expert] + CHAT_SUFFIX},
        {'role': 'user', 'content': '以下是抓包分析摘要：\n\n' + ctx},
        {'role': 'assistant',
         'content': '好的，我已了解这份抓包的分析结果，可以回答后续问题。'},
    ]

    tail = [h for h in (history or [])
            if h.get('role') in ('user', 'assistant')
            and (h.get('content') or '').strip()][-MAX_HISTORY:]
    for h in tail:
        msgs.append({'role': h['role'], 'content': h['content']})
    msgs.append({'role': 'user', 'content': question.strip()})

    body = {
        'model': cfg.get('model') or DEFAULT_MODEL,
        'messages': msgs,
        'max_tokens': 1600,
        'stream': bool(on_delta),
        'thinking': {'type': 'disabled'},
    }
    return _post(body, on_delta)


def test_connection() -> str:
    cfg = load_config()
    if not _api_key(cfg):
        raise RuntimeError('尚未填写 API Key')
    body = {
        'model': cfg.get('model') or DEFAULT_MODEL,
        'messages': [{'role': 'user', 'content': 'reply with OK only'}],
        'max_tokens': 10,
        'thinking': {'type': 'disabled'},
    }
    return _post(body)
