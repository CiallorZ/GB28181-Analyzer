#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_tshark_lines 流式读取超时回归：stdout 阻塞时不能被永久挂住。"""
from __future__ import annotations

import queue
import threading

import pytest

from app.parsers import capture


class _BlockingStdout:
    """永不产出行的 stdout；close() 时释放阻塞中的读线程。"""

    def __init__(self, lines=()):
        self._lines = queue.Queue()
        for line in lines:
            self._lines.put(line)
        self._release = threading.Event()
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        try:
            return self._lines.get_nowait()
        except queue.Empty:
            pass
        self._release.wait(5)
        raise StopIteration

    def close(self):
        self.closed = True
        self._release.set()


class _FakeProc:
    def __init__(self, lines=()):
        self.stdout = _BlockingStdout(lines)
        self.returncode = None
        self.killed = False
        self.wait_timeouts = []

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        if self.returncode is None:
            self.returncode = -9

    def wait(self, timeout=None):
        self.wait_timeouts.append(timeout)
        return self.returncode


def _install_clock(monkeypatch, values):
    """把 monotonic 换成按序返回给定值的假时钟（需要先返回 started）。"""
    it = iter(values)

    def _fake():
        try:
            return next(it)
        except StopIteration:
            return values[-1]

    monkeypatch.setattr(capture.time, 'monotonic', _fake)


def test_tshark_lines_timeout_when_stdout_never_yields(monkeypatch):
    """进程一行都不输出：超时必须抛错，且杀掉并回收进程。"""
    proc = _FakeProc()
    monkeypatch.setattr(capture.subprocess, 'Popen', lambda *a, **kw: proc)
    # started=0，第一次循环 remaining=0.01（走一次有界 get），第二次直接越过 deadline
    _install_clock(monkeypatch, [0.0, 0.0, 10.0])

    with pytest.raises(capture.CaptureError, match='超时'):
        list(capture._tshark_lines(['fake-tshark'], timeout=0.01))

    assert proc.killed
    assert proc.wait_timeouts, 'kill 后应调用 wait 回收进程'
    assert proc.stdout.closed


def test_tshark_lines_timeout_after_partial_output(monkeypatch):
    """输出中途卡住（stdout 仍打开）同样要触发 deadline。"""
    proc = _FakeProc(lines=['first\n'])
    monkeypatch.setattr(capture.subprocess, 'Popen', lambda *a, **kw: proc)
    _install_clock(monkeypatch, [0.0, 0.0, 0.0, 10.0])

    got = []
    with pytest.raises(capture.CaptureError, match='超时'):
        for line in capture._tshark_lines(['fake-tshark'], timeout=0.01):
            got.append(line)

    assert got == ['first\n'], '超时前已产出的行不能丢'
    assert proc.killed
    assert proc.wait_timeouts
