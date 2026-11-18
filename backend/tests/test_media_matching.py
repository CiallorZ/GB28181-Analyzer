#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""会话-媒体流配对打分回归

`_match_score` 是「哪条流属于哪个会话」的唯一判据。
打错的后果比打不出分更严重：流会被静默归到错误会话，用户看到的是
「某个会话有媒体、某个会话没媒体」，而真实情况完全相反。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.parsers.session_builder import SessionInfo, _match_score  # noqa: E402


def _session(**kw) -> SessionInfo:
    s = SessionInfo()
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def _stream(**kw) -> dict:
    st = {'ssrc': 0, 'src_port': None, 'dst_port': None, 'transport': 'UDP',
          'start_time': 0.0, 'end_time': 1.0}
    st.update(kw)
    return st


class TestSsrcMissing:
    def test_zero_ssrc_does_not_match(self):
        """SSRC=0 表示「没解析到」，不能当成匹配成功"""
        s = _session(sdp_ssrc='00001234')
        st = _stream(ssrc=0, dst_port=9999)
        assert _match_score(s, st) == 0

    def test_none_ssrc_does_not_match(self):
        s = _session(sdp_ssrc='00001234')
        st = _stream(ssrc=None, dst_port=9999)
        assert _match_score(s, st) == 0

    def test_zero_ssrc_with_matching_port_still_only_weak(self):
        """即使端口对上，也只能拿到端口分，不能拿到 SSRC 满分"""
        s = _session(sdp_ssrc='00001234', negotiated_port=8808)
        st = _stream(ssrc=0, dst_port=8808)
        assert _match_score(s, st) == 60

    def test_all_zero_session_ssrc_ignored(self):
        """SDP 里写 y=00000000 时也不该参与匹配"""
        s = _session(sdp_ssrc='00000000')
        st = _stream(ssrc=0x1234, dst_port=9999)
        assert _match_score(s, st) == 0


class TestSsrcMatching:
    def test_exact_match_wins(self):
        s = _session(sdp_ssrc='00001234')
        assert _match_score(s, _stream(ssrc=0x1234)) == 10000

    def test_match_without_leading_zeros(self):
        s = _session(sdp_ssrc='1234')
        assert _match_score(s, _stream(ssrc=0x1234)) == 10000

    def test_match_ten_digit_gb_form(self):
        """GB 里 y= 常是 10 位十进制风格，设备实际 SSRC 可能只有低位"""
        s = _session(sdp_ssrc='0600001869')
        assert _match_score(s, _stream(ssrc=0x0600001869)) == 10000

    def test_subject_ssrc_also_matches(self):
        s = _session(subject_ssrc='00001234')
        assert _match_score(s, _stream(ssrc=0x1234)) == 10000

    def test_ssrc_beats_port_only(self):
        """SSRC 命中的流必须排在只有端口命中的流前面"""
        s = _session(sdp_ssrc='00001234', negotiated_port=8808)
        by_ssrc = _match_score(s, _stream(ssrc=0x1234, dst_port=1))
        by_port = _match_score(s, _stream(ssrc=0x9999, dst_port=8808))
        assert by_ssrc > by_port

    def test_wrong_ssrc_does_not_match(self):
        s = _session(sdp_ssrc='00001234')
        assert _match_score(s, _stream(ssrc=0x9999, dst_port=9999)) == 0
