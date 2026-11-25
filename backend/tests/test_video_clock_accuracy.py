from app.parsers import ps_parser, rtp_analyzer


class BitWriter:
    def __init__(self):
        self.bits = []

    def u(self, value, width):
        self.bits.extend((value >> shift) & 1 for shift in range(width - 1, -1, -1))

    def ue(self, value):
        code = value + 1
        width = code.bit_length()
        self.bits.extend([0] * (width - 1))
        self.bits.extend((code >> shift) & 1 for shift in range(width - 1, -1, -1))

    def bytes(self):
        self.bits.extend([0] * (-len(self.bits) % 8))
        return bytes(
            sum(bit << (7 - index) for index, bit in enumerate(self.bits[start:start + 8]))
            for start in range(0, len(self.bits), 8)
        )


def h265_sps(width=1920, height=1088, bottom_crop=4, luma_depth=10):
    bits = BitWriter()
    bits.u(0, 4)                 # sps_video_parameter_set_id
    bits.u(0, 3)                 # max_sub_layers_minus1
    bits.u(0, 1)                 # temporal_id_nesting
    bits.u(0, 2)                 # general_profile_space
    bits.u(0, 1)                 # general_tier_flag
    bits.u(1, 5)                 # Main profile
    bits.u(0, 32)                # compatibility flags
    bits.u(0, 4)                 # constraint flags
    bits.u(0, 44)                # remaining constraints
    bits.u(120, 8)               # level 4.0
    bits.ue(0)                   # sps_id
    bits.ue(1)                   # 4:2:0
    bits.ue(width)
    bits.ue(height)
    bits.u(1, 1)                 # conformance_window_flag
    bits.ue(0)                   # left
    bits.ue(0)                   # right
    bits.ue(0)                   # top
    bits.ue(bottom_crop)
    bits.ue(luma_depth - 8)
    bits.ue(luma_depth - 8)
    return b'\x42\x01' + bits.bytes()


def test_h265_sps_applies_chroma_crop_and_luma_depth():
    parsed = ps_parser.parse_h265_sps(h265_sps())
    assert parsed['width'] == 1920
    assert parsed['height'] == 1080
    assert parsed['bit_depth'] == 10
    assert parsed['bit_depth_chroma'] == 10
    assert parsed['chroma_format'] == 1


def test_timestamp_jump_threshold_uses_stream_clock_rate():
    packets = [
        rtp_analyzer.RtpPacket(seq=0, timestamp=0, arrival=0),
        rtp_analyzer.RtpPacket(seq=1, timestamp=8000 * 6, arrival=6),
    ]
    stats = rtp_analyzer.analyze_stream(packets, clock_rate=8000)
    assert any(item['type'] == 'timestamp_jump' for item in stats.ts_anomalies)


def test_timestamp_jump_is_not_reported_inside_five_seconds():
    packets = [
        rtp_analyzer.RtpPacket(seq=0, timestamp=0, arrival=0),
        rtp_analyzer.RtpPacket(seq=1, timestamp=8000 * 4, arrival=4),
    ]
    stats = rtp_analyzer.analyze_stream(packets, clock_rate=8000)
    assert not [item for item in stats.ts_anomalies if item['type'] == 'timestamp_jump']
