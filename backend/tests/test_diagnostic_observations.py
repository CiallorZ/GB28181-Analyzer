"""Boundary tests for the nine evidence-based additions to the rule catalog."""
import pytest

from app.parsers.sip_parser import build_message
from app.services.analyzer import _message_dict
from app.services.diagnosis import diagnose


def message(**fields):
    return dict({'packet_number': 11, 'timestamp': 3., 'is_request': True, 'method': 'REGISTER',
                 'source_ip': '10.1.0.1', 'destination_ip': '10.1.0.2',
                 'source_port': 5060, 'destination_port': 5060, 'via_branch': 'z9hG4bK-test', 'call_id': 'demo', 'cseq_number': 0}, **fields)


def matches(rule, **data):
    return [event for event in diagnose(data) if event.rule_id == rule]


def test_register_window_and_response():
    req = message()
    assert not matches('SIP-002', messages=[req], capture_end=34.99)
    event, = matches('SIP-002', messages=[req], capture_end=35)
    assert event.related_packet_ids == [11] and event.evidence['window_s'] == 32
    assert not matches('SIP-002', messages=[req,message(is_request=False,status_code=401)], capture_end=40)


def test_repeated_requests_and_orphan_responses():
    req = message()
    assert not matches('SIP-004', messages=[req]*3)
    other = message(source_port=5061, packet_number=16)
    assert not matches('SIP-004', messages=[req]*3 + [other])
    assert not matches('SIP-004', messages=[message(source_ip=None)]*4)
    event, = matches('SIP-004', messages=[other] + [req]*4)
    assert event.evidence['observations'] == 4 and 16 not in event.related_packet_ids
    assert not matches('SIP-004', messages=[req]*3 + [message(via_branch='another')])
    assert not matches('SIP-004', messages=[message(method='ACK')]*4)
    response = message(is_request=False, status_code=200)
    assert not matches('SIP-005', messages=[response,req])
    event, = matches('SIP-005', messages=[response])
    assert event.related_packet_ids == [11] and event.evidence_level == 'insufficient'


@pytest.mark.parametrize(('rule','bad','good'), [
    ('SIP-006', {'parse_errors':['缺少 CSeq']}, {'parse_errors':[]}),
    ('SDP-001', {'sdp_address':'999.1.1.1'}, {'sdp_address':'ff15::1234'}),
    ('SDP-004', {'sdp_errors':['媒体描述无效']}, {'sdp_errors':[]}),
])
def test_signaling_structure(rule, bad, good):
    assert matches(rule, messages=[message(**bad)])[0].related_packet_ids == [11]
    assert not matches(rule, messages=[message(**good)])


def test_parser_delivers_evidence():
    raw = 'Via: SIP/2.0/UDP host;branch=z9hG4bKx\r\nCall-ID: demo\r\nContent-Type: application/sdp'
    sip = build_message(raw, b'v=0\r\nc=IN IP4 999.1.1.1\r\nm=video abc RTP/AVP 96',
                        {'packet_number':7,'timestamp':1,'request_line':'INVITE sip:x SIP/2.0'})
    events = diagnose({'messages':[_message_dict(sip)]})
    assert {event.rule_id for event in events if event.related_packet_ids == [7]} >= {'SIP-006','SDP-001','SDP-004'}


def test_abnormal_end_requires_observation():
    assert matches('SIP-007', sessions=[{'id':17,'end_reason':'abnormal'}])[0].session_id == 17
    assert not matches('SIP-007', sessions=[{'id':17,'end_reason':'capture_ended'}])


def test_media_mismatch_requires_exact_association():
    s = {'id':3,'negotiated_port':9000,'negotiated_transport':'TCP'}
    stream = {'id':5,'session_id':3,'source_port':8600,'destination_port':9001,'link_mode':'exact','transport':'TCP'}
    assert matches('SDP-002',sessions=[s],streams=[stream])[0].stream_id == 5
    assert not matches('SDP-002',sessions=[s],streams=[{**stream,'link_mode':'weak'}])
    assert not matches('SDP-002',sessions=[s],streams=[{**stream,'destination_port':9000}])


def test_bitrate_drop_requires_three_complete_low_windows():
    stream = {'id':20, 'bitrate_samples':list(enumerate([10,100,100,100,30,30,30,2]))}
    event, = matches('MED-006',streams=[stream])
    assert event.stream_id == 20 and event.evidence['baseline_kbps'] == 100
    stream['bitrate_samples'].pop()
    assert not matches('MED-006',streams=[stream])


def test_sdp_port_count_is_valid():
    from app.parsers.sip_parser import parse_sdp
    sdp = parse_sdp('v=0\r\nm=video 5004/2 RTP/AVP 96')
    assert sdp.media[0]['port'] == 5004 and not sdp.errors

@pytest.mark.parametrize(('rule', 'quiet', 'observed', 'measurement'), [
    ('MED-003', {'jitter_avg': 50}, {'jitter_avg': 200}, 'jitter_avg_ms'),
    ('MED-004', {'max_gap': 3}, {'max_gap': 3.01}, 'max_gap_seconds'),
    ('MED-005', {'ts_anomalies': [{'type': 'wrap'}]},
     {'ts_anomalies': [{'type': 'wrap'}, {'type': 'backward'}]}, 'kinds'),
])
def test_media_rule_boundaries(rule, quiet, observed, measurement):
    assert not matches(rule, streams=[{'id': 7, 'ssrc': 0, **quiet}])
    event, = matches(rule, streams=[{'id': 7, 'ssrc': 0, **observed}])
    assert event.stream_id == 7 and event.evidence_level == 'confirmed'
    assert measurement in event.evidence
    if rule == 'MED-005':
        assert event.evidence[measurement] == {'backward': 1}
