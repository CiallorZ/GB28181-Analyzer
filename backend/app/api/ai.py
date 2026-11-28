#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DeepSeek AI 分析接口（SSE 流式）"""
from __future__ import annotations

from typing import Literal

import hashlib
import inspect
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.security import validate_ai_base_url
from ..models.entities import AnalysisTask
from ..services import ai

router = APIRouter(prefix='/ai', tags=['ai'])


class ConfigIn(BaseModel):
    api_key: str | None = None
    model: str | None = None
    base_url: str | None = None


class ChatIn(BaseModel):
    question: str
    history: list = []
    expert: Literal['general', 'sip', 'media', 'field', 'packet'] = 'general'
    context_hash: str | None = None


class AnalyzeIn(BaseModel):
    expert: Literal['general', 'sip', 'media', 'field', 'packet'] = 'general'
    context_hash: str | None = None


def _sse(event: str, data: dict) -> str:
    return 'event: %s\ndata: %s\n\n' % (
        event, json.dumps(data, ensure_ascii=False))


@router.get('/config')
def get_config():
    return ai.public_config()


@router.post('/config')
def set_config(body: ConfigIn):
    cfg = ai.load_config()
    if body.api_key is not None and body.api_key.strip():
        cfg['api_key'] = body.api_key.strip()
    if body.model is not None:
        cfg['model'] = body.model.strip() or ai.DEFAULT_MODEL
    if body.base_url is not None:
        try:
            cfg['base_url'] = (validate_ai_base_url(body.base_url)
                               if body.base_url.strip() else ai.DEFAULT_BASE)
        except ValueError as e:
            raise HTTPException(400, str(e))
    ai.save_config(cfg)
    return ai.public_config()


@router.post('/test')
def test_conn():
    try:
        out = ai.test_connection()
        return {'ok': True, 'reply': out[:80]}
    except RuntimeError as e:
        raise HTTPException(400, str(e))


def _accepts_cancel_event(func) -> bool:
    """兼容旧的 monkeypatch/扩展：若被替换的函数不接受 cancel_event，就不传。"""
    try:
        signature = inspect.signature(func)
        return ('cancel_event' in signature.parameters or
                any(p.kind == inspect.Parameter.VAR_KEYWORD
                    for p in signature.parameters.values()))
    except (TypeError, ValueError):
        return False


def _context(db: Session, task_id: int) -> str:
    task = db.get(AnalysisTask, task_id)
    if not task:
        raise HTTPException(404, '任务不存在')
    if task.status != 'completed':
        raise HTTPException(400, '任务尚未完成分析')
    return ai.build_context(db, task_id)


@router.get('/context/{task_id}')
def preview_context(task_id: int, db: Session = Depends(get_db)):
    context = _context(db, task_id)
    return {'context': context, 'context_hash': hashlib.sha256(context.encode('utf-8')).hexdigest()}


@router.post('/analyze/{task_id}')
def analyze_stream(task_id: int, body: AnalyzeIn = AnalyzeIn(), db: Session = Depends(get_db)):
    """真正的逐 token 流式（SSE）"""
    context = _context(db, task_id)
    if body.context_hash and body.context_hash != hashlib.sha256(context.encode('utf-8')).hexdigest():
        raise HTTPException(409, '分析摘要已变化，请重新预览')

    def gen():
        # 有界队列 + 取消事件：客户端断开（生成器被 close）时立即通知 worker，
        # worker 再通知上游停止读取，避免连接断开后仍持续消耗 token。
        import queue
        import threading

        q: queue.Queue = queue.Queue(maxsize=256)
        cancelled = threading.Event()
        result = {'text': '', 'error': None}

        def _put(item):
            """投递事件；取消后丢弃增量，终端事件用短超时避免 worker 卡住。"""
            if cancelled.is_set() and item[0] == 'delta':
                return
            while not cancelled.is_set():
                try:
                    q.put(item, timeout=0.2)
                    return
                except queue.Full:
                    if item[0] == 'delta':
                        continue
                    # 终端事件必须送达，但队列长期被占满时不要永久阻塞
                    break

        def worker():
            try:
                def on_delta(t):
                    if not cancelled.is_set():
                        _put(('delta', t))
                kwargs = {'on_delta': on_delta, 'context': context,
                          'expert': body.expert}
                if _accepts_cancel_event(ai.analyze):
                    kwargs['cancel_event'] = cancelled
                text = ai.analyze(db, task_id, **kwargs)
                result['text'] = text
                _put(('done', text))
            except RuntimeError as e:
                _put(('error', str(e)))
            except Exception as e:
                _put(('error', '分析失败：%s' % e))

        th = threading.Thread(target=worker, daemon=True)
        th.start()

        try:
            while True:
                try:
                    kind, payload = q.get(timeout=180)
                except queue.Empty:
                    yield _sse('error', {'error': '分析超时'})
                    break
                if cancelled.is_set() and kind == 'delta':
                    continue
                if kind == 'delta':
                    yield _sse('delta', {'t': payload})
                elif kind == 'done':
                    yield _sse('done', {'text': payload})
                    break
                elif kind == 'error':
                    yield _sse('error', {'error': payload})
                    break
        finally:
            # 正常结束、超时或客户端断开都会执行；幂等地通知 worker 与上游。
            cancelled.set()

    return StreamingResponse(gen(), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache',
                                      'X-Accel-Buffering': 'no'})


@router.post('/chat/{task_id}')
def chat(task_id: int, body: ChatIn, db: Session = Depends(get_db)):
    context = _context(db, task_id)
    if body.context_hash and body.context_hash != hashlib.sha256(context.encode('utf-8')).hexdigest():
        raise HTTPException(409, '分析摘要已变化，请重新分析后追问')

    def gen():
        import queue
        import threading

        q: queue.Queue = queue.Queue(maxsize=256)
        cancelled = threading.Event()

        def _put(item):
            """投递事件；取消后丢弃增量，终端事件用短超时避免 worker 卡住。"""
            if cancelled.is_set() and item[0] == 'delta':
                return
            while not cancelled.is_set():
                try:
                    q.put(item, timeout=0.2)
                    return
                except queue.Full:
                    if item[0] == 'delta':
                        continue
                    break

        def worker():
            try:
                def on_delta(t):
                    if not cancelled.is_set():
                        _put(('delta', t))
                kwargs = {'on_delta': on_delta, 'context': context,
                          'expert': body.expert}
                if _accepts_cancel_event(ai.chat):
                    kwargs['cancel_event'] = cancelled
                text = ai.chat(db, task_id, body.history, body.question, **kwargs)
                _put(('done', text))
            except RuntimeError as e:
                _put(('error', str(e)))
            except Exception as e:
                _put(('error', '对话失败：%s' % e))

        th = threading.Thread(target=worker, daemon=True)
        th.start()

        try:
            while True:
                try:
                    kind, payload = q.get(timeout=180)
                except queue.Empty:
                    yield _sse('error', {'error': '对话超时'})
                    break
                if cancelled.is_set() and kind == 'delta':
                    continue
                if kind == 'delta':
                    yield _sse('delta', {'t': payload})
                elif kind == 'done':
                    yield _sse('done', {'text': payload})
                    break
                elif kind == 'error':
                    yield _sse('error', {'error': payload})
                    break
        finally:
            cancelled.set()

    return StreamingResponse(gen(), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache',
                                      'X-Accel-Buffering': 'no'})
