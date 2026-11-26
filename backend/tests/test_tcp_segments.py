"""dump_tcp_segments：按方向拆分与时间窗"""

from app.parsers import capture


def test_tcp_segments_split_by_direction(monkeypatch):
    """同一 tcp.stream 的两个方向必须分开，否则 seq 会互相"补洞\""""
    rows = [
        ['1', '1000', '1.000', '10.0.0.1', '5060', '10.0.0.2', '40000', 'aabb'],
        ['1', '1002', '1.200', '10.0.0.1', '5060', '10.0.0.2', '40000', 'ccdd'],
        ['1', '3000', '1.100', '10.0.0.2', '40000', '10.0.0.1', '5060', 'eeff'],
        ['1', '3002', '1.300', '10.0.0.2', '40000', '10.0.0.1', '5060', '0011'],
    ]
    monkeypatch.setattr(capture, 'TSHARK', '/bin/true')
    monkeypatch.setattr(capture, 'iter_fields', lambda *a, **k: iter(rows))

    out = capture.dump_tcp_segments('ignored.pcap')

    assert len(out) == 2
    up = out['1:10.0.0.1:5060->10.0.0.2:40000']
    down = out['1:10.0.0.2:40000->10.0.0.1:5060']
    assert sorted(up['segs']) == [1000, 1002]
    assert sorted(down['segs']) == [3000, 3002]
    assert (up['t0'], up['t1']) == (1.0, 1.2)
    assert (down['t0'], down['t1']) == (1.1, 1.3)
    assert up['meta']['stream_id'] == '1'
    assert up['meta']['src_port'] == 5060
    assert down['meta']['dst_ip'] == '10.0.0.1'


def test_tcp_segments_skips_empty_and_bad_rows(monkeypatch):
    rows = [
        ['2', '1', '0.1', 'a', '1', 'b', '2', ''],
        ['2', 'x', '0.1', 'a', '1', 'b', '2', 'ff'],
        ['2', '3', '0.2', 'a', '1', 'b', '2', 'zz'],
    ]
    monkeypatch.setattr(capture, 'TSHARK', '/bin/true')
    monkeypatch.setattr(capture, 'iter_fields', lambda *a, **k: iter(rows))

    assert capture.dump_tcp_segments('ignored.pcap') == {}
