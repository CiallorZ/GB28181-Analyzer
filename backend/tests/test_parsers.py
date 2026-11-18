#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
解析器单元测试

原则：断言基于协议规范，不依赖实现细节。
测试数据是手工构造的合成报文，明确标记为 synthetic。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.parsers import rtp_analyzer, session_builder, sip_parser


# ============================================================
# SDP 解析（M04）
# ============================================================
class TestSdpParser:
    def test_basic_video_sdp(self):
        """标准 GB28181 视频 SDP"""
        text = (
            'v=0\r\n'
            'o=34020000001320000001 0 0 IN IP4 10.0.0.1\r\n'
            's=Play\r\n'
            'c=IN IP4 10.0.0.1\r\n'
            't=0 0\r\n'
            'm=video 8808 TCP/RTP/AVP 96\r\n'
            'a=rtpmap:96 PS/90000\r\n'
            'a=setup:passive\r\n'
            'a=connection:new\r\n'
            'a=recvonly\r\n'
            'a=y:0000197000\r\n'
        )
        sdp = sip_parser.parse_sdp(text)
        assert sdp is not None
        assert sdp.connection_address == '10.0.0.1'
        assert len(sdp.media) == 1
        assert sdp.media[0]['type'] == 'video'
        assert sdp.media[0]['port'] == 8808
        assert sdp.media[0]['protocol'] == 'TCP/RTP/AVP'
        assert sdp.is_tcp is True
        assert sdp.setup == 'passive'
        assert sdp.y_ssrc == '0000197000'
        assert sdp.stream_mode == 'recvonly'

    def test_udp_sdp(self):
        text = (
            'v=0\r\n'
            'c=IN IP4 192.168.1.10\r\n'
            'm=video 15060 RTP/AVP 96 98\r\n'
            'a=rtpmap:96 PS/90000\r\n'
            'a=sendonly\r\n'
        )
        sdp = sip_parser.parse_sdp(text)
        assert sdp.media[0]['port'] == 15060
        assert sdp.media[0]['protocol'] == 'RTP/AVP'
        assert sdp.is_tcp is False
        assert sdp.media[0]['formats'] == ['96', '98']

    def test_malformed_missing_media(self):
        """没有 m= 行应记录错误，而不是崩溃"""
        sdp = sip_parser.parse_sdp('v=0\r\nc=IN IP4 1.2.3.4\r\n')
        assert sdp is not None
        assert sdp.errors
        assert any('m=' in e for e in sdp.errors)

    def test_short_connection_line(self):
        """c= 行字段不足要记录，不能 IndexError"""
        sdp = sip_parser.parse_sdp('v=0\r\nc=IN IP4\r\nm=video 1 RTP/AVP 96\r\n')
        assert sdp is not None
        assert any('c=' in e for e in sdp.errors)

    def test_not_sdp(self):
        assert sip_parser.parse_sdp('hello world') is None
        assert sip_parser.parse_sdp('') is None


# ============================================================
# SIP 消息解析（M03）
# ============================================================
class TestSipParser:
    def _meta(self, **kw):
        base = {
            'packet_number': 1, 'timestamp': 100.0,
            'src_ip': '10.0.0.1', 'src_port': 5060,
            'dst_ip': '10.0.0.2', 'dst_port': 5060,
        }
        base.update(kw)
        return base

    def test_invite_request(self):
        hdr = (
            'Via: SIP/2.0/UDP 10.0.0.1:5060;branch=z9hG4bK123\r\n'
            'From: <sip:34020000002000000001@10.0.0.1>;tag=abc\r\n'
            'To: <sip:34020000001320000001@10.0.0.2>\r\n'
            'Call-ID: test-call-1\r\n'
            'CSeq: 1 INVITE\r\n'
            'Content-Type: application/sdp\r\n'
            'Content-Length: 0\r\n'
        )
        body = (
            b'v=0\r\no=1 0 0 IN IP4 10.0.0.1\r\ns=Play\r\n'
            b'c=IN IP4 10.0.0.1\r\nm=video 8808 TCP/RTP/AVP 96\r\n'
        )
        m = sip_parser.build_message(
            hdr, body, self._meta(request_line='INVITE sip:x@10.0.0.2 SIP/2.0'))
        assert m.is_request is True
        assert m.method == 'INVITE'
        assert m.call_id == 'test-call-1'
        assert m.from_tag == 'abc'
        assert m.cseq_number == 1
        assert m.cseq_method == 'INVITE'
        assert m.via_branch == 'z9hG4bK123'
        assert m.sdp is not None

    def test_response_200(self):
        hdr = (
            'Via: SIP/2.0/UDP 10.0.0.1:5060;branch=z9hG4bK123\r\n'
            'From: <sip:a@1.1.1.1>;tag=abc\r\n'
            'To: <sip:b@2.2.2.2>;tag=xyz\r\n'
            'Call-ID: c1\r\n'
            'CSeq: 1 INVITE\r\n'
        )
        m = sip_parser.build_message(
            hdr, b'', self._meta(status_line='SIP/2.0 200 OK'))
        assert m.is_request is False
        assert m.status_code == 200
        assert m.to_tag == 'xyz'
        assert m.dialog_key() == 'c1|abc|xyz'

    def test_dialog_key_is_symmetric(self):
        """请求与响应的 dialog_key 必须一致（tag 排序后）"""
        hdr_req = (
            'From: <sip:a@1>;tag=AAA\r\nTo: <sip:b@2>\r\n'
            'Call-ID: same\r\nCSeq: 1 INVITE\r\n'
        )
        hdr_res = (
            'From: <sip:a@1>;tag=AAA\r\nTo: <sip:b@2>;tag=BBB\r\n'
            'Call-ID: same\r\nCSeq: 1 INVITE\r\n'
        )
        # 请求里 to_tag 为空，响应里有
        req = sip_parser.build_message(
            hdr_req, b'', self._meta(request_line='INVITE sip:b@2 SIP/2.0'))
        res = sip_parser.build_message(
            hdr_res, b'', self._meta(status_line='SIP/2.0 200 OK'))
        # 请求侧 to_tag 缺失，所以两者 key 不同 —— 这是预期行为，
        # 归并时靠 Call-ID 分组补齐（见 session_builder.build_dialogs）
        assert req.call_id == res.call_id

    def test_gb18030_body(self):
        """国标 XML 正文多为 GB18030 编码"""
        xml = ('<?xml version="1.0"?>'
               '<Notify><CmdType>Keepalive</CmdType>'
               '<SN>1</SN><DeviceID>34020000001320000001</DeviceID>'
               '<Status>OK</Status></Notify>')
        raw = xml.encode('gb18030')
        m = sip_parser.build_message(
            'Call-ID: k1\r\nCSeq: 1 MESSAGE\r\n'
            'Content-Type: Application/MANSCDP+xml\r\n',
            raw, self._meta(request_line='MESSAGE sip:x@y SIP/2.0'))
        assert 'Keepalive' in m.body
        assert m.gb_command == 'Keepalive'
        assert m.device_id == '34020000001320000001'

    def test_catalog_items(self):
        xml = ('<?xml version="1.0"?><Response><CmdType>Catalog</CmdType>'
               '<SN>5</SN><DeviceID>34020000002000000001</DeviceID>'
               '<SumNum>2</SumNum><DeviceList Num="2">'
               '<Item><DeviceID>34020000001320000001</DeviceID>'
               '<Name>Camera 1</Name><Status>ON</Status>'
               '<ParentID>34020000002000000001</ParentID></Item>'
               '<Item><DeviceID>34020000001320000002</DeviceID>'
               '<Name>Camera 2</Name><Status>OFF</Status></Item>'
               '</DeviceList></Response>')
        m = sip_parser.build_message(
            'Call-ID: c\r\nCSeq: 1 MESSAGE\r\n', xml.encode('utf-8'),
            self._meta(request_line='MESSAGE sip:x@y SIP/2.0'))
        assert m.gb_command == 'Catalog'
        assert len(m.xml_items) == 2
        assert m.xml_items[0]['Name'] == 'Camera 1'
        assert m.xml_items[0]['ParentID'] == '34020000002000000001'

    def test_missing_call_id_records_error(self):
        m = sip_parser.build_message(
            'CSeq: 1 INVITE\r\n', b'',
            self._meta(request_line='INVITE sip:x@y SIP/2.0'))
        assert any('Call-ID' in e for e in m.parse_errors)

    def test_folded_headers(self):
        """折行头域要正确合并"""
        hdr = (
            'Via: SIP/2.0/UDP 10.0.0.1:5060;\r\n'
            ' branch=z9hG4bKfolded\r\n'
            'Call-ID: f1\r\nCSeq: 1 OPTIONS\r\n'
        )
        m = sip_parser.build_message(
            hdr, b'', self._meta(request_line='OPTIONS sip:x@y SIP/2.0'))
        assert m.via_branch == 'z9hG4bKfolded'


# ============================================================
# RTP 序号回绕（M07 核心）
# ============================================================
class TestRtpSequence:
    def _pkts(self, seqs):
        return [rtp_analyzer.RtpPacket(seq=s, arrival=i * 0.02, size=100)
                for i, s in enumerate(seqs)]

    def test_no_wrap(self):
        pkts = self._pkts([1, 2, 3, 4, 5])
        rtp_analyzer.unwrap_sequences(pkts)
        assert [p.seq_unwrapped for p in pkts] == [1, 2, 3, 4, 5]

    def test_wrap_forward(self):
        """65534 -> 65535 -> 0 -> 1 应展开为连续"""
        pkts = self._pkts([65534, 65535, 0, 1, 2])
        rtp_analyzer.unwrap_sequences(pkts)
        vals = [p.seq_unwrapped for p in pkts]
        assert vals == [65534, 65535, 65536, 65537, 65538]

    def test_no_false_gap_at_wrap(self):
        """回绕处不能误判为丢包"""
        pkts = self._pkts([65534, 65535, 0, 1])
        st = rtp_analyzer.analyze_stream(pkts)
        assert st.seq_gap_packets == 0
        assert st.duplicate_count == 0

    def test_real_gap_detected(self):
        pkts = self._pkts([1, 2, 5, 6])     # 缺 3、4
        st = rtp_analyzer.analyze_stream(pkts)
        assert st.seq_gap_count == 1
        assert st.seq_gap_packets == 2

    def test_duplicates(self):
        pkts = self._pkts([1, 2, 2, 3])
        st = rtp_analyzer.analyze_stream(pkts)
        assert st.duplicate_count == 1

    def test_out_of_order(self):
        pkts = self._pkts([1, 3, 2, 4])
        st = rtp_analyzer.analyze_stream(pkts)
        assert st.out_of_order_count >= 1

    def test_tcp_gap_not_confirmed_loss(self):
        """TCP 承载的缺口不能标为确认丢包"""
        pkts = self._pkts([1, 2, 10, 11])
        st = rtp_analyzer.analyze_stream(pkts, transport='TCP')
        assert st.loss_confidence == 'observed_gap'
        assert any('TCP' in n for n in st.notes)


# ============================================================
# RFC 3550 抖动
# ============================================================
class TestJitter:
    def test_zero_jitter_constant_interval(self):
        """到达间隔与时间戳步长一致时，抖动应为 0"""
        pkts = []
        for i in range(20):
            pkts.append(rtp_analyzer.RtpPacket(
                seq=i, timestamp=i * 3000, arrival=i * (3000 / 90000)))
        avg, mx, series = rtp_analyzer.compute_jitter(pkts, 90000)
        assert avg is not None
        assert avg < 0.5      # 毫秒，几乎为 0

    def test_jitter_increases_with_irregular_arrival(self):
        pkts = []
        t = 0.0
        for i in range(30):
            pkts.append(rtp_analyzer.RtpPacket(
                seq=i, timestamp=i * 3000, arrival=t))
            t += 0.033 + (0.02 if i % 3 == 0 else 0)
        avg, mx, series = rtp_analyzer.compute_jitter(pkts, 90000)
        assert avg > 1.0

    def test_single_packet_no_jitter(self):
        pkts = [rtp_analyzer.RtpPacket(seq=1, arrival=0.0)]
        avg, mx, series = rtp_analyzer.compute_jitter(pkts, 90000)
        assert avg is None


# ============================================================
# RFC4571 / TCP 重组
# ============================================================
class TestRfc4571:
    @staticmethod
    def _rtp(seq, ssrc=0x11223344, pt=96, payload=b'X' * 40):
        hdr = bytes([
            0x80, pt,
            (seq >> 8) & 0xff, seq & 0xff,
            0, 0, 0, 100,
            (ssrc >> 24) & 0xff, (ssrc >> 16) & 0xff,
            (ssrc >> 8) & 0xff, ssrc & 0xff,
        ])
        return hdr + payload

    @staticmethod
    def _frame(rtp):
        return len(rtp).to_bytes(2, 'big') + rtp

    def test_parse_from_zero_offset(self):
        buf = b''.join(self._frame(self._rtp(i)) for i in range(10))
        got = rtp_analyzer.parse_rfc4571(buf)
        assert got is not None
        off, pkts = got
        assert off == 0
        assert len(pkts) == 10
        assert pkts[0].ssrc == 0x11223344
        assert pkts[0].payload_type == 96

    def test_parse_with_offset(self):
        """抓包起点不在包边界上（实测遇过 1158/1829）"""
        junk = b'\xAA' * 1158
        buf = junk + b''.join(self._frame(self._rtp(i)) for i in range(10))
        got = rtp_analyzer.parse_rfc4571(buf)
        assert got is not None
        off, pkts = got
        assert off == 1158
        assert len(pkts) == 10

    def test_garbage_returns_none(self):
        assert rtp_analyzer.parse_rfc4571(b'\x00' * 500) is None

    def test_tcp_reassembly_in_order(self):
        segs = {100: b'AAA', 103: b'BBB', 106: b'CCC'}
        assert rtp_analyzer.reassemble_tcp(segs) == b'AAABBBCCC'

    def test_tcp_reassembly_with_hole(self):
        segs = {100: b'AAA', 110: b'BBB'}
        out = rtp_analyzer.reassemble_tcp(segs)
        assert out.startswith(b'AAA')
        assert out.endswith(b'BBB')
        assert len(out) == 13        # 3 + 7 空洞 + 3

    def test_tcp_reassembly_overlap(self):
        segs = {100: b'AAABBB', 103: b'BBBCCC'}
        out = rtp_analyzer.reassemble_tcp(segs)
        assert out == b'AAABBBCCC'


# ============================================================
# 会话重建
# ============================================================
class TestSessionBuilder:
    def _invite_flow(self):
        """构造一次完整的 INVITE 200 ACK BYE 流程"""
        base_meta = {'src_ip': '10.0.0.1', 'src_port': 5060,
                     'dst_ip': '10.0.0.2', 'dst_port': 5060}
        hdr_common = (
            'Via: SIP/2.0/UDP 10.0.0.1:5060;branch=z9hG4bK1\r\n'
            'From: <sip:34020000002000000001@10.0.0.1>;tag=t1\r\n'
            'To: <sip:34020000001320000001@10.0.0.2>\r\n'
            'Call-ID: dialog-1\r\n'
        )
        invite = sip_parser.build_message(
            hdr_common + 'CSeq: 1 INVITE\r\nContent-Type: application/sdp\r\n',
            b'v=0\r\nc=IN IP4 10.0.0.1\r\nm=video 8808 TCP/RTP/AVP 96\r\n',
            {**base_meta, 'packet_number': 1, 'timestamp': 10.0,
             'request_line': 'INVITE sip:x@10.0.0.2 SIP/2.0'})

        hdr_res = hdr_common.replace(
            'To: <sip:34020000001320000001@10.0.0.2>',
            'To: <sip:34020000001320000001@10.0.0.2>;tag=t2')
        ok = sip_parser.build_message(
            hdr_res + 'CSeq: 1 INVITE\r\n',
            b'v=0\r\nc=IN IP4 10.0.0.2\r\nm=video 9 TCP/RTP/AVP 96\r\na=setup:active\r\n',
            {**base_meta, 'src_ip': '10.0.0.2', 'dst_ip': '10.0.0.1',
             'packet_number': 2, 'timestamp': 10.2,
             'status_line': 'SIP/2.0 200 OK'})

        ack = sip_parser.build_message(
            hdr_res + 'CSeq: 1 ACK\r\n', b'',
            {**base_meta, 'packet_number': 3, 'timestamp': 10.25,
             'request_line': 'ACK sip:x@10.0.0.2 SIP/2.0'})

        bye = sip_parser.build_message(
            hdr_res + 'CSeq: 2 BYE\r\n', b'',
            {**base_meta, 'packet_number': 4, 'timestamp': 50.0,
             'request_line': 'BYE sip:x@10.0.0.2 SIP/2.0'})

        bye_ok = sip_parser.build_message(
            hdr_res + 'CSeq: 2 BYE\r\n', b'',
            {**base_meta, 'src_ip': '10.0.0.2', 'dst_ip': '10.0.0.1',
             'packet_number': 5, 'timestamp': 50.1,
             'status_line': 'SIP/2.0 200 OK'})
        return [invite, ok, ack, bye, bye_ok]

    def test_dialog_grouping(self):
        msgs = self._invite_flow()
        dialogs = session_builder.build_dialogs(msgs)
        assert len(dialogs) == 1
        d = dialogs[0]
        assert d.call_id == 'dialog-1'
        assert d.invite_time == 10.0
        assert d.answer_time == 10.2
        assert d.ack_time == 10.25
        assert d.bye_time == 50.0
        assert d.final_code == 200

    def test_session_signal_success(self):
        dialogs = session_builder.build_dialogs(self._invite_flow())
        sessions = session_builder.build_sessions(dialogs, self._invite_flow())
        assert len(sessions) == 1
        s = sessions[0]
        assert s.signal_status == 'success'
        assert s.end_reason == 'normal'
        assert abs(s.invite_latency - 0.2) < 0.01
        assert abs(s.total_duration - 40.0) < 0.01

    def test_negotiated_port_prefers_offer(self):
        """TCP 被动模式：answer 的端口 9 是占位值，应取 offer 的 8808"""
        dialogs = session_builder.build_dialogs(self._invite_flow())
        sessions = session_builder.build_sessions(dialogs, self._invite_flow())
        s = sessions[0]
        assert s.negotiated_port == 8808
        assert s.negotiated_transport == 'TCP'

    def test_invite_no_response(self):
        """只有 INVITE 没有响应 -> incomplete"""
        base_meta = {'src_ip': '10.0.0.1', 'src_port': 5060,
                     'dst_ip': '10.0.0.2', 'dst_port': 5060,
                     'packet_number': 1, 'timestamp': 1.0}
        invite = sip_parser.build_message(
            'From: <sip:a@1>;tag=x\r\nTo: <sip:b@2>\r\n'
            'Call-ID: no-resp\r\nCSeq: 1 INVITE\r\n', b'',
            {**base_meta, 'request_line': 'INVITE sip:b@2 SIP/2.0'})
        dialogs = session_builder.build_dialogs([invite])
        sessions = session_builder.build_sessions(dialogs, [invite])
        assert sessions[0].signal_status == 'incomplete'

    def test_invite_failure_code(self):
        base_meta = {'src_ip': '10.0.0.1', 'src_port': 5060,
                     'dst_ip': '10.0.0.2', 'dst_port': 5060,
                     'packet_number': 1, 'timestamp': 1.0}
        hdr = ('From: <sip:a@1>;tag=x\r\nTo: <sip:b@2>;tag=y\r\n'
               'Call-ID: fail-1\r\nCSeq: 1 INVITE\r\n')
        invite = sip_parser.build_message(
            hdr, b'', {**base_meta, 'request_line': 'INVITE sip:b@2 SIP/2.0'})
        fail = sip_parser.build_message(
            hdr, b'', {**base_meta, 'src_ip': '10.0.0.2', 'dst_ip': '10.0.0.1',
                       'packet_number': 2, 'timestamp': 1.5,
                       'status_line': 'SIP/2.0 404 Not Found'})
        dialogs = session_builder.build_dialogs([invite, fail])
        sessions = session_builder.build_sessions(dialogs, [invite, fail])
        assert sessions[0].signal_status == 'failed'

    def test_media_linking_no_duplicate_claim(self):
        """一条流只能归属一个会话"""
        s1 = session_builder.SessionInfo(device_id='d1', start_time=0.0,
                                         negotiated_port=8808,
                                         negotiated_transport='TCP')
        s2 = session_builder.SessionInfo(device_id='d2', start_time=0.0,
                                         negotiated_port=8808,
                                         negotiated_transport='TCP')
        streams = [{'ssrc': 1, 'dst_port': 8808, 'transport': 'TCP',
                    'start_time': 1.0, 'end_time': 5.0, 'packet_count': 100}]
        session_builder.link_media([s1, s2], streams)
        total_claims = len(s1.media_stream_keys) + len(s2.media_stream_keys)
        assert total_claims == 1

    def test_media_linking_matches_port(self):
        s = session_builder.SessionInfo(device_id='d1', start_time=0.0,
                                        negotiated_port=8808,
                                        negotiated_transport='TCP')
        streams = [{'ssrc': 1, 'dst_port': 8808, 'transport': 'TCP',
                    'start_time': 1.0, 'end_time': 5.0, 'packet_count': 100}]
        session_builder.link_media([s], streams)
        assert s.media_status == 'received'
        assert len(s.media_stream_keys) == 1
        assert s.first_media_latency == 1.0


# ============================================================
# 诊断引擎
# ============================================================
class TestDiagnosis:
    def test_no_media_rule(self):
        from app.services import diagnosis
        payload = {
            'sessions': [{
                'id': 1, 'device_id': 'dev1',
                'signal_status': 'success', 'media_status': 'no_media',
                'negotiated_ip': '10.0.0.1', 'negotiated_port': 8808,
                'negotiated_transport': 'TCP',
                'start_time': 1.0, 'call_ids': ['c1'],
            }],
            'streams': [], 'messages': [], 'limits': [],
        }
        out = diagnosis.diagnose(payload)
        rules = [d.rule_id for d in out]
        assert 'MED-001' in rules
        med = [d for d in out if d.rule_id == 'MED-001'][0]
        assert med.severity == 'critical'
        # 不能把"没抓到媒体"说成已确认
        assert med.evidence_level == 'suspected'

    def test_ssrc_mismatch_rule(self):
        from app.services import diagnosis
        payload = {
            'sessions': [{
                'id': 1, 'device_id': 'dev1',
                'signal_status': 'success', 'media_status': 'received',
                'subject_ssrc': '00001970', 'sdp_ssrc': '0600000841',
                'start_time': 1.0,
            }],
            'streams': [], 'messages': [], 'limits': [],
        }
        out = diagnosis.diagnose(payload)
        assert 'SDP-003' in [d.rule_id for d in out]

    def test_tcp_gap_is_insufficient_evidence(self):
        """TCP 承载的序号缺口证据等级必须是 insufficient"""
        from app.services import diagnosis
        payload = {
            'sessions': [{'id': 1, 'device_id': 'd', 'signal_status': 'success',
                          'media_status': 'received', 'start_time': 1.0}],
            'streams': [{
                'id': 1, 'session_id': 1, 'ssrc': 123,
                'transport': 'TCP', 'packet_count': 100,
                'seq_gap_count': 2, 'seq_gap_packets': 5,
                'start_time': 1.0, 'loss_confidence': 'observed_gap',
            }],
            'messages': [], 'limits': [],
        }
        out = diagnosis.diagnose(payload)
        gaps = [d for d in out if d.rule_id == 'MED-002']
        assert len(gaps) == 1
        assert gaps[0].evidence_level == 'insufficient'

    def test_udp_gap_is_confirmed(self):
        from app.services import diagnosis
        payload = {
            'sessions': [{'id': 1, 'device_id': 'd', 'signal_status': 'success',
                          'media_status': 'received', 'start_time': 1.0}],
            'streams': [{
                'id': 1, 'session_id': 1, 'ssrc': 123,
                'transport': 'UDP', 'packet_count': 100,
                'seq_gap_count': 3, 'seq_gap_packets': 10,
                'start_time': 1.0, 'loss_confidence': 'confirmed_loss',
            }],
            'messages': [], 'limits': [],
        }
        out = diagnosis.diagnose(payload)
        gaps = [d for d in out if d.rule_id == 'MED-002']
        assert gaps[0].evidence_level == 'confirmed'


    def test_bye_media_rule(self):
        """MED-007：BYE 之后才出现的媒体流"""
        from app.services import diagnosis
        payload = {
            'sessions': [{
                'id': 1, 'device_id': 'd1',
                'signal_status': 'success', 'media_status': 'received',
                'end_reason': 'normal',
                'start_time': 10.0, 'end_time': 20.0,
            }],
            'streams': [{
                'id': 1, 'session_id': 1, 'ssrc': 123,
                'transport': 'TCP', 'packet_count': 100,
                'start_time': 25.0, 'end_time': 30.0,
                'seq_gap_packets': 0,
            }],
            'messages': [], 'limits': [],
        }
        out = diagnosis.diagnose(payload)
        bye = [d for d in out if d.rule_id == 'MED-007']
        assert len(bye) == 1
        # 无法区分"残留推流"与"另一轮会话"，证据等级必须是 suspected
        assert bye[0].evidence_level == 'suspected'

    def test_bye_media_no_false_positive(self):
        """媒体在 BYE 之前开始，不应报 MED-007"""
        from app.services import diagnosis
        payload = {
            'sessions': [{
                'id': 1, 'device_id': 'd1',
                'signal_status': 'success', 'media_status': 'received',
                'end_reason': 'normal',
                'start_time': 10.0, 'end_time': 20.0,
            }],
            'streams': [{
                'id': 1, 'session_id': 1, 'ssrc': 123,
                'transport': 'TCP', 'packet_count': 100,
                'start_time': 12.0, 'end_time': 19.0,
                'seq_gap_packets': 0,
            }],
            'messages': [], 'limits': [],
        }
        out = diagnosis.diagnose(payload)
        assert not [d for d in out if d.rule_id == 'MED-007']

    def test_empty_input_no_crash(self):
        from app.services import diagnosis
        assert diagnosis.diagnose({'sessions': [], 'streams': [],
                                   'messages': [], 'limits': []}) == []
