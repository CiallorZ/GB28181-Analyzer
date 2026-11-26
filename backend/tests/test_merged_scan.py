"""iter_packets 合并 SIP 字段：一次 tshark 扫描同时产出索引与 SIP 原始行"""
from __future__ import annotations

import pytest

from app.parsers import capture
from app.services import analyzer


class _FakeStdout:
    def __init__(self, lines):
        self._lines = list(lines)

    def __iter__(self):
        return iter(self._lines)


class _FakeProc:
    def __init__(self, lines):
        self.stdout = _FakeStdout(lines)
        self.stderr = None
        self.returncode = 0

    def poll(self):
        return 0

    def kill(self):
        pass

    def wait(self, timeout=None):
        return 0


def _line(*fields) -> str:
    return '\x1f'.join(fields) + '\n'


def _index_line(num, ts, src, dst, proto_ports=('5060', '40000'), protos='eth:ip:udp:sip'):
    return _line(num, ts, '120', src, dst, '', '',
                 '', '', proto_ports[0], proto_ports[1], protos)


def _sip_line(num, ts, src, sport, dst, dport, request_line='INVITE sip:x SIP/2.0'):
    # 索引 12 列 + SIP 12 列：地址/端口与索引列重复，随后是 sip.* 字段
    return _line(num, ts, '300', src, dst, '', '',
                 '', '', sport, dport, 'eth:ip:udp:sip',
                 src, sport, '', dst, dport, '',
                 '1 INVITE', '', request_line, '',
                 'From: <sip:a@b>\r\nTo: <sip:c@d>\r\nCall-ID: abc\r\n',
                 '')


@pytest.fixture
def fake_tshark(monkeypatch):
    def install(lines):
        monkeypatch.setattr(capture, 'TSHARK', '/bin/true')
        monkeypatch.setattr(capture.subprocess, 'Popen',
                            lambda *a, **k: _FakeProc(lines))
    return install


def test_iter_packets_without_sip_keeps_old_shape(fake_tshark):
    fake_tshark([_index_line('1', '0.5', '10.0.0.1', '10.0.0.2')])

    items = list(capture.iter_packets('ignored.pcap'))

    assert len(items) == 1
    assert 'sip' not in items[0]
    assert items[0]['src_port'] == 5060


def test_iter_packets_collects_sip_only_for_sip_packets(fake_tshark):
    fake_tshark([
        _index_line('1', '0.1', '10.0.0.1', '10.0.0.2'),   # 普通 RTP，无 SIP 字段
        _sip_line('2', '0.2', '10.0.0.1', '5060', '10.0.0.2', '5060'),
    ])

    items = list(capture.iter_packets('ignored.pcap', include_sip=True))

    assert len(items) == 2
    assert 'sip' not in items[0]
    sip = items[1]['sip']
    # 元组前缀是 frame.number、frame.time_relative，与 _load_sip 的解包顺序一致
    assert sip[0] == '2'
    assert sip[8] == '1 INVITE'              # sip.CSeq
    assert sip[10] == 'INVITE sip:x SIP/2.0'  # sip.Request-Line
    assert 'Call-ID: abc' in sip[12]         # sip.msg_hdr


def test_load_sip_accepts_precollected_rows(db, make_task):
    """合并扫描后 _load_sip 不应再自己跑 tshark"""
    task = make_task()
    rows = [(str(n), str(0.1 * n), '10.0.0.1', '5060', '', '10.0.0.2', '5060',
             '', '1 INVITE', '', 'INVITE sip:x SIP/2.0', '',
             'From: <sip:a@b>;tag=1\r\nTo: <sip:c@d>\r\nCall-ID: abc\r\n'
             'CSeq: 1 INVITE\r\n', '')
            for n in (1, 2)]

    out = analyzer._load_sip(db, task, 'ignored.pcap', rows_raw=rows)

    assert len(out) == 2
    assert {m['info'].call_id for m in out} == {'abc'}
