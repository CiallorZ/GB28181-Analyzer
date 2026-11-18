#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SDP 国标扩展字段（y= / f=）解析回归

GB/T 28181 附录 F 把 y=（SSRC）定义为**会话级独立行**，
不是 a= 属性。历史实现只处理 a= 分支，导致标准写法解析为空，
只有非标准的 `a=y:xxxx` 能解析出来 —— 现场抓包几乎都是标准写法。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.parsers.sip_parser import parse_sdp      # noqa: E402

BASE = (
    'v=0\r\n'
    'o=34020000001320000001 0 0 IN IP4 10.0.0.1\r\n'
    's=Play\r\n'
    'c=IN IP4 10.0.0.2\r\n'
    't=0 0\r\n'
)


def _sdp(extra: str) -> str:
    return BASE + extra + 'm=video 30000 RTP/AVP 96\r\n' \
        'a=rtpmap:96 PS/90000\r\n' \
        'a=setup:passive\r\n' \
        'a=connection:new\r\n'


class TestYField:
    def test_standard_session_level_y(self):
        """标准写法：y= 是会话级行，紧跟在 t= 之后"""
        sdp = parse_sdp(_sdp('y=0100000001\r\n'))
        assert sdp is not None
        assert sdp.y_ssrc == '0100000001'

    def test_standard_y_with_padding(self):
        """GB 里 y= 是 10 位十进制，设备常按 8 位 16 进制补零"""
        sdp = parse_sdp(_sdp('y=00001234\r\n'))
        assert sdp.y_ssrc == '00001234'

    def test_nonstandard_equals_attribute(self):
        """非标准但现场常见：a=y=00001234"""
        sdp = parse_sdp(_sdp('a=y=00001234\r\n'))
        assert sdp.y_ssrc == '00001234'

    def test_nonstandard_colon_attribute(self):
        """历史唯一能解析的写法，必须继续兼容"""
        sdp = parse_sdp(_sdp('a=y:0000197000\r\n'))
        assert sdp.y_ssrc == '0000197000'

    def test_y_after_media_section(self):
        """y= 出现在 m= 之后（部分设备这样写）"""
        sdp = parse_sdp(
            BASE + 'm=video 30000 RTP/AVP 96\r\n'
            'a=rtpmap:96 PS/90000\r\n'
            'y=1234567890\r\n'
        )
        assert sdp.y_ssrc == '1234567890'

    def test_y_absent(self):
        sdp = parse_sdp(_sdp(''))
        assert sdp.y_ssrc == ''

    def test_y_survives_media_attributes(self):
        """y= 不能被塞进 media 属性字典里当成普通属性"""
        sdp = parse_sdp(_sdp('y=0000abcd\r\n'))
        assert sdp.y_ssrc == '0000abcd'
        assert 'y' not in sdp.media[0]['attributes']


class TestFField:
    def test_standard_session_level_f(self):
        """f= 表示媒体流发送源，也是会话级行"""
        sdp = parse_sdp(_sdp('f=v/2/5/25/1/4000a/1/1a\r\n'))
        assert sdp.f_field == 'v/2/5/25/1/4000a/1/1a'

    def test_nonstandard_f_attribute(self):
        sdp = parse_sdp(_sdp('a=f=v/2/5/25/1/4000a\r\n'))
        assert sdp.f_field == 'v/2/5/25/1/4000a'

    def test_f_absent(self):
        sdp = parse_sdp(_sdp(''))
        assert sdp.f_field == ''


class TestOtherGbFields:
    def test_tcp_passive(self):
        sdp = parse_sdp(
            BASE + 'm=video 9 RTP/AVP 96\r\n'
            'a=rtpmap:96 PS/90000\r\n'
            'a=setup:passive\r\n'
        )
        assert sdp is not None
        assert sdp.setup == 'passive'
        assert sdp.is_tcp is False       # 只有 m= 里写 TCP 才算 TCP

    def test_tcp_in_media_protocol(self):
        sdp = parse_sdp(
            BASE + 'm=video 30000 TCP/RTP/AVP 96\r\n'
            'a=setup:passive\r\n'
        )
        assert sdp.is_tcp is True

    def test_ssrc_zero_preserved(self):
        # SSRC=0 是合法值，不能被当成「没解析到」
        sdp = parse_sdp(_sdp('y=00000000\r\n'))
        assert sdp.y_ssrc == '00000000'
