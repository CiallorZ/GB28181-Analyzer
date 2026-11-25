from app.parsers import rtp_analyzer
from app.services import rebuild


def packet(arrival, size=100):
    return rtp_analyzer.RtpPacket(arrival=arrival, payload=b'x' * size)


def test_sample_payloads_stops_at_time_window():
    packets = [packet(i * 10) for i in range(10)]
    payloads, sampled = rebuild.sample_payloads(packets, max_seconds=35)
    assert len(payloads) == 4
    assert sampled is True


def test_sample_timed_payloads_keeps_original_arrivals():
    packets = [packet(i * 10) for i in range(10)]
    pairs, sampled = rebuild.sample_timed_payloads(packets, max_seconds=35)
    assert [arrival for _payload, arrival in pairs] == [0, 10, 20, 30]
    assert sampled is True


def test_sample_payloads_stops_at_byte_budget():
    packets = [packet(0, size=80), packet(1, size=80), packet(2, size=80)]
    payloads, sampled = rebuild.sample_payloads(packets, max_bytes=100)
    assert len(payloads) == 1
    assert sampled is True


def test_sample_payloads_keeps_short_stream_complete():
    packets = [packet(0), packet(1), packet(2)]
    payloads, sampled = rebuild.sample_payloads(packets)
    assert len(payloads) == 3
    assert sampled is False
