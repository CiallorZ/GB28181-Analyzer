"""生成一个带 RTCP SR/RR 的抓包样本

样本内容完全确定，可直接断言：

- 1 个完整 INVITE 事务（SDP 声明 SSRC 0x00001234，UDP 8808）
- 120 个 UDP RTP/PS 包（SSRC 0x00001234）
- 发送端 SR：NTP 固定值、RTP 时间戳、包数/字节数
- 接收端 RR：报告 0x00001234，区间丢包 25%、抖动 1800、LSR 指向上面的 SR、
  DLSR 60ms

时间轴刻意设计成：抓包机墙钟比 SR 的 NTP 快 1 秒；SR→RR 抓包间隔
99.998ms，DLSR 3932 个单位（59.9976ms）—— 相减正好 RTT 40.000ms，
时钟差 1.000s。间隔取 99.998ms 而不是整 100ms，是因为 DLSR 只能按
1/65536 秒计数，整 100ms 减 59.9976ms 会得到 40.002ms。

用法：python make_rtcp_sr_rr.py rtcp-sr-rr.pcap
"""
import struct
import sys

NTP_EPOCH_OFFSET = 2208988800

# 不 import make_sip_udp_basic：那个模块在顶层就生成并写出抓包，
# 导入它会在 sys.argv[1] 上写出另一份样本、覆盖本脚本的输出。


def csum(b):
    if len(b) % 2:
        b += b'\0'
    s = sum(struct.unpack('!%dH' % (len(b) // 2), b))
    while s >> 16:
        s = (s & 0xffff) + (s >> 16)
    return (~s) & 0xffff


def ip_udp(src, dst, sport, dport, payload, ident):
    udp = struct.pack('!HHHH', sport, dport, 8 + len(payload), 0) + payload
    src_b = bytes(int(x) for x in src.split('.'))
    dst_b = bytes(int(x) for x in dst.split('.'))
    pseudo = src_b + dst_b + struct.pack('!BBH', 0, 17, len(udp))
    uc = csum(pseudo + udp)
    udp = udp[:6] + struct.pack('!H', uc or 0xffff) + udp[8:]
    ip = struct.pack('!BBHHHBBH4s4s', 0x45, 0, 20 + len(udp), ident, 0x4000,
                     64, 17, 0, src_b, dst_b)
    ip = ip[:10] + struct.pack('!H', csum(ip)) + ip[12:]
    return ip + udp


def eth(payload):
    return (b'\x00\x11\x22\x33\x44\x55' + b'\x66\x77\x88\x99\xaa\xbb'
            + b'\x08\x00' + payload)


def sip(start, hdrs, body=b''):
    h = start + '\r\n' + hdrs + 'Content-Length: %d\r\n\r\n' % len(body)
    return h.encode('gb18030') + body


CALLID = 'rtcp123def456@192.168.1.10'
SDP_OFFER = (b'v=0\r\no=34020000001320000001 0 0 IN IP4 192.168.1.10\r\ns=Play\r\n'
             b'c=IN IP4 192.168.1.10\r\nt=0 0\r\ny=00001234\r\n'
             b'm=video 8808 RTP/AVP 96\r\na=recvonly\r\na=rtpmap:96 PS/90000\r\n')
SDP_ANSWER = (b'v=0\r\no=34020000001310000001 0 0 IN IP4 192.168.1.20\r\ns=Play\r\n'
              b'c=IN IP4 192.168.1.20\r\nt=0 0\r\nm=video 40001 RTP/AVP 96\r\n'
              b'a=sendonly\r\na=rtpmap:96 PS/90000\r\na=y=00001234\r\n')

pkts = []
t = 0.0


def add(src, dst, sp, dp, payload):
    """追加一个报文，时间戳按整数微秒记录，避免浮点累积误差

    抓包时间必须精确到微秒：SR→RR 的间隔直接决定 RTT，
    差 1 µs 就会让断言里的 40.0ms 变成 39.999ms。
    """
    global t
    pkts.append((round(t * 1e6),
                 eth(ip_udp(src, dst, sp, dp, payload, len(pkts) + 1))))
    t += 0.01


A, B = '192.168.1.10', '192.168.1.20'
MEDIA_SSRC = 0x00001234
RECEIVER_SSRC = 0x00005678


# ---------------- 信令 ----------------
add(A, B, 5060, 5060, sip(
    'INVITE sip:34020000001310000001@192.168.1.20 SIP/2.0',
    'Via: SIP/2.0/UDP 192.168.1.10:5060;branch=z9hG4bK-inv-1\r\n'
    'From: <sip:34020000001320000001@192.168.1.10>;tag=fromtag1\r\n'
    'To: <sip:34020000001310000001@192.168.1.20>\r\n'
    'Call-ID: %s\r\nCSeq: 1 INVITE\r\n'
    'Subject: 34020000001320000001:00001234,34020000001310000001:0\r\n'
    'Content-Type: application/sdp\r\n' % CALLID, SDP_OFFER))
t += 0.2
add(B, A, 5060, 5060, sip(
    'SIP/2.0 200 OK',
    'Via: SIP/2.0/UDP 192.168.1.10:5060;branch=z9hG4bK-inv-1\r\n'
    'From: <sip:34020000001320000001@192.168.1.10>;tag=fromtag1\r\n'
    'To: <sip:34020000001310000001@192.168.1.20>;tag=totag1\r\n'
    'Call-ID: %s\r\nCSeq: 1 INVITE\r\n'
    'Content-Type: application/sdp\r\n' % CALLID, SDP_ANSWER))
add(A, B, 5060, 5060, sip(
    'ACK sip:34020000001310000001@192.168.1.20 SIP/2.0',
    'Via: SIP/2.0/UDP 192.168.1.10:5060;branch=z9hG4bK-ack-1\r\n'
    'From: <sip:34020000001320000001@192.168.1.10>;tag=fromtag1\r\n'
    'To: <sip:34020000001310000001@192.168.1.20>;tag=totag1\r\n'
    'Call-ID: %s\r\nCSeq: 1 ACK\r\n' % CALLID))


# ---------------- RTP/PS ----------------
def ps_packet(seq, ts, ssrc, payload):
    return struct.pack('!BBHII', 0x80, 96, seq & 0xffff, ts & 0xffffffff, ssrc) + payload


SPS = (b'\x00\x00\x00\x01\x67\x42\xc0\x1e\xd9\x00\x50\x05\xbb\x01\x10\x00'
       b'\x00\x03\x00\x10\x00\x00\x03\x03\xc0\xf1\x83\x19\x60')
PPS = b'\x00\x00\x00\x01\x68\xce\x3c\x80'


def ps_pack(pes_payload, pts=0):
    pack = b'\x00\x00\x01\xba' + b'\x44' + b'\x00\x04\x00\x04\x01\x00\x01\x8b\xc5' + b'\x00\x00'
    pes = (b'\x00\x00\x01\xe0' + struct.pack('!H', 8 + len(pes_payload)) +
           b'\x80\x80\x05' + struct.pack('!Q', (2 << 30) | (pts & 0x1fffffff))[:5] + pes_payload)
    return pack + pes


seq = 0
ts = 0
for frame in range(120):
    if frame % 30 == 0:
        nal = SPS + PPS + b'\x00\x00\x00\x01\x65' + b'\x88' * 800
    else:
        nal = b'\x00\x00\x00\x01\x41' + b'\x55' * 200
    body = ps_pack(nal, pts=ts)
    for chunk in range(0, len(body), 1200):
        add(A, B, 40000, 8808, ps_packet(seq, ts, MEDIA_SSRC, body[chunk:chunk + 1200]))
        seq += 1
    ts += 3600
    t += 0.03


# ---------------- RTCP ----------------
def rtcp_sr(ssrc, ntp_msw, ntp_lsw, rtp_ts, packet_count, octet_count):
    body = (ssrc.to_bytes(4, 'big') + ntp_msw.to_bytes(4, 'big')
            + ntp_lsw.to_bytes(4, 'big') + rtp_ts.to_bytes(4, 'big')
            + packet_count.to_bytes(4, 'big') + octet_count.to_bytes(4, 'big'))
    return bytes([0x80, 200]) + (len(body) // 4).to_bytes(2, 'big') + body


def rtcp_rr(reporter, block):
    body = reporter.to_bytes(4, 'big') + block
    return bytes([0x81, 201]) + (len(body) // 4).to_bytes(2, 'big') + body


def report_block(ssrc, fraction, cumulative, jitter, lsr, dlsr):
    return (ssrc.to_bytes(4, 'big') + bytes([fraction])
            + (cumulative & 0xFFFFFF).to_bytes(3, 'big')
            + (1000).to_bytes(4, 'big') + jitter.to_bytes(4, 'big')
            + lsr.to_bytes(4, 'big') + dlsr.to_bytes(4, 'big'))


NTP_MSW, NTP_LSW = 0xE0000001, 0x80000000
LSR = ((NTP_MSW & 0xFFFF) << 16) | (NTP_LSW >> 16)

# 发送端 SR（媒体端口发往接收端）。SR 在 120 个 RTP 包之后发出，
# 所以它的 NTP 必须按"这一刻的抓包墙钟"来定，不能按 t=0 算。
SR_T = t
add(A, B, 8808, 40001, rtcp_sr(MEDIA_SSRC, NTP_MSW, NTP_LSW, ts, seq, seq * 1200))
# DLSR 的单位是 1/65536 秒，3932 个单位 = 59.9976ms，凑不出整 60ms。
# 把 SR→RR 的抓包间隔定成 99.998ms，相减正好 40.000ms 的 RTT。
t = SR_T + 0.099998
add(B, A, 40001, 8808, rtcp_rr(
    RECEIVER_SSRC,
    report_block(MEDIA_SSRC, 64, 25, 1800, LSR, int(0.060 * 65536))))

# BYE
add(A, B, 5060, 5060, sip(
    'BYE sip:34020000001310000001@192.168.1.20 SIP/2.0',
    'Via: SIP/2.0/UDP 192.168.1.10:5060;branch=z9hG4bK-bye-1\r\n'
    'From: <sip:34020000001320000001@192.168.1.10>;tag=fromtag1\r\n'
    'To: <sip:34020000001310000001@192.168.1.20>;tag=totag1\r\n'
    'Call-ID: %s\r\nCSeq: 2 BYE\r\n' % CALLID))
add(B, A, 5060, 5060, sip(
    'SIP/2.0 200 OK',
    'Via: SIP/2.0/UDP 192.168.1.10:5060;branch=z9hG4bK-bye-1\r\n'
    'From: <sip:34020000001320000001@192.168.1.10>;tag=fromtag1\r\n'
    'To: <sip:34020000001310000001@192.168.1.20>;tag=totag1\r\n'
    'Call-ID: %s\r\nCSeq: 2 BYE\r\n' % CALLID))


out = sys.argv[1]
# 墙钟基准要让 SR 那一刻满足：抓包机墙钟 − SR 的 NTP = 1.0 秒。
# SR 是在 120 个 RTP 包之后发出的，所以基准要按 SR_T 回推，
# 不能直接把 t=0 当成 NTP 时刻（否则时钟差会多出 SR_T 秒）。
NTP_SECONDS = NTP_MSW - NTP_EPOCH_OFFSET + NTP_LSW / (1 << 32)
WALL_BASE_US = round((NTP_SECONDS + 1.0 - SR_T) * 1e6)
with open(out, 'wb') as f:
    f.write(struct.pack('<IHHiIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1))
    for us, data in pkts:
        sec, usec = divmod(WALL_BASE_US + us, 1_000_000)
        f.write(struct.pack('<IIII', sec, usec, len(data), len(data)))
        f.write(data)
print('wrote %d packets -> %s' % (len(pkts), out))
