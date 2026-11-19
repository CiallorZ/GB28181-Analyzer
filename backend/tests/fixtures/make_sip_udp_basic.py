import struct
import sys

def csum(b):
    if len(b) % 2: b += b'\0'
    s = sum(struct.unpack('!%dH' % (len(b)//2), b))
    while s >> 16: s = (s & 0xffff) + (s >> 16)
    return (~s) & 0xffff

def ip_udp(src, dst, sport, dport, payload, ident):
    udp = struct.pack('!HHHH', sport, dport, 8+len(payload), 0) + payload
    pseudo = bytes(int(x) for x in src.split('.')) + bytes(int(x) for x in dst.split('.')) + struct.pack('!BBH', 0, 17, len(udp))
    uc = csum(pseudo + udp)
    udp = udp[:6] + struct.pack('!H', uc or 0xffff) + udp[8:]
    ip = struct.pack('!BBHHHBBH4s4s', 0x45, 0, 20+len(udp), ident, 0x4000, 64, 17, 0,
                     bytes(int(x) for x in src.split('.')), bytes(int(x) for x in dst.split('.')))
    ip = ip[:10] + struct.pack('!H', csum(ip)) + ip[12:]
    return ip + udp

def eth(payload):
    return b'\x00\x11\x22\x33\x44\x55' + b'\x66\x77\x88\x99\xaa\xbb' + b'\x08\x00' + payload

def sip(start, hdrs, body=b''):
    h = start + '\r\n' + hdrs + 'Content-Length: %d\r\n\r\n' % len(body)
    return h.encode('gb18030') + body

# 注意两种 y= 写法都故意保留：
#   offer  用标准写法（GB/T 28181 附录 F：会话级独立行 y=）
#   answer 用非标准的 a=y= （现场常见误写）
# 两者都必须能解析出 SSRC，否则回归测试会失败。
SDP_OFFER = (b'v=0\r\no=34020000001320000001 0 0 IN IP4 192.168.1.10\r\ns=Play\r\n'
             b'c=IN IP4 192.168.1.10\r\nt=0 0\r\ny=00001234\r\nf=v/2/5/25/1/4000a/1/1a\r\n'
             b'm=video 8808 TCP/RTP/AVP 96 98 97\r\n'
             b'a=recvonly\r\na=setup:passive\r\na=connection:new\r\na=rtpmap:96 PS/90000\r\n'
             b'a=rtpmap:98 H264/90000\r\na=rtpmap:97 MPEG4/90000\r\n')
SDP_ANSWER = (b'v=0\r\no=34020000001310000001 0 0 IN IP4 192.168.1.20\r\ns=Play\r\n'
              b'c=IN IP4 192.168.1.20\r\nt=0 0\r\nm=video 9 TCP/RTP/AVP 96 98 97\r\n'
              b'a=sendonly\r\na=setup:active\r\na=rtpmap:96 PS/90000\r\na=rtpmap:98 H264/90000\r\na=y=00005678\r\n')

CALLID = 'abc123def456@192.168.1.10'
pkts = []
t = 0.0
def add(src, dst, sp, dp, payload):
    global t
    pkts.append((t, eth(ip_udp(src, dst, sp, dp, payload, len(pkts)+1))))
    t += 0.01

A, B = '192.168.1.10', '192.168.1.20'
add(A, B, 5060, 5060, sip('INVITE sip:34020000001310000001@192.168.1.20 SIP/2.0',
    'Via: SIP/2.0/UDP 192.168.1.10:5060;branch=z9hG4bK-inv-1\r\n'
    'From: <sip:34020000001320000001@192.168.1.10>;tag=fromtag1\r\n'
    'To: <sip:34020000001310000001@192.168.1.20>\r\n'
    'Call-ID: %s\r\nCSeq: 1 INVITE\r\nContact: <sip:34020000001320000001@192.168.1.10:5060>\r\n'
    'Subject: 34020000001320000001:00001234,34020000001310000001:0\r\n'
    'Content-Type: application/sdp\r\n' % CALLID, SDP_OFFER))
add(B, A, 5060, 5060, sip('SIP/2.0 100 Trying',
    'Via: SIP/2.0/UDP 192.168.1.10:5060;branch=z9hG4bK-inv-1\r\n'
    'From: <sip:34020000001320000001@192.168.1.10>;tag=fromtag1\r\n'
    'To: <sip:34020000001310000001@192.168.1.20>\r\n'
    'Call-ID: %s\r\nCSeq: 1 INVITE\r\n' % CALLID))
t += 0.2
add(B, A, 5060, 5060, sip('SIP/2.0 200 OK',
    'Via: SIP/2.0/UDP 192.168.1.10:5060;branch=z9hG4bK-inv-1\r\n'
    'From: <sip:34020000001320000001@192.168.1.10>;tag=fromtag1\r\n'
    'To: <sip:34020000001310000001@192.168.1.20>;tag=totag1\r\n'
    'Call-ID: %s\r\nCSeq: 1 INVITE\r\n'
    'Contact: <sip:34020000001310000001@192.168.1.20:5060>\r\n'
    'Content-Type: application/sdp\r\n' % CALLID, SDP_ANSWER))
add(A, B, 5060, 5060, sip('ACK sip:34020000001310000001@192.168.1.20 SIP/2.0',
    'Via: SIP/2.0/UDP 192.168.1.10:5060;branch=z9hG4bK-ack-1\r\n'
    'From: <sip:34020000001320000001@192.168.1.10>;tag=fromtag1\r\n'
    'To: <sip:34020000001310000001@192.168.1.20>;tag=totag1\r\n'
    'Call-ID: %s\r\nCSeq: 1 ACK\r\n' % CALLID))

# ---- RTP/PS 媒体（UDP，SSRC 0x00001234 与 Subject 一致）----
def ps_packet(seq, ts, ssrc, payload):
    hdr = struct.pack('!BBHII', 0x80, 96, seq & 0xffff, ts & 0xffffffff, ssrc)
    return hdr + payload

SPS = b'\x00\x00\x00\x01\x67\x42\xc0\x1e\xd9\x00\x50\x05\xbb\x01\x10\x00\x00\x03\x00\x10\x00\x00\x03\x03\xc0\xf1\x83\x19\x60'
PPS = b'\x00\x00\x00\x01\x68\xce\x3c\x80'
def ps_pack(pes_payload, pts=0):
    pack = b'\x00\x00\x01\xba' + b'\x44' + b'\x00\x04\x00\x04\x01\x00\x01\x8b\xc5' + b'\x00\x00'
    pes = (b'\x00\x00\x01\xe0' + struct.pack('!H', 8 + len(pes_payload)) +
           b'\x80\x80\x05' + struct.pack('!Q', (2 << 30) | (pts & 0x1fffffff))[:5] + pes_payload)
    return pack + pes

seq = 0
ssrc = 0x00001234
ts = 0
for frame in range(120):
    es = (SPS + PPS) if frame == 0 else b''
    nal = SPS + PPS + (b'\x00\x00\x00\x01\x65' + b'\x88' * 800 if frame % 30 == 0 else b'\x00\x00\x00\x01\x41' + b'\x55' * 200)
    body = ps_pack(nal, pts=ts)
    for chunk in range(0, len(body), 1200):
        add(A, B, 40000, 8808, ps_packet(seq, ts, ssrc, body[chunk:chunk+1200]))
        seq += 1
    ts += 3600
    t += 0.03

# BYE
add(A, B, 5060, 5060, sip('BYE sip:34020000001310000001@192.168.1.20 SIP/2.0',
    'Via: SIP/2.0/UDP 192.168.1.10:5060;branch=z9hG4bK-bye-1\r\n'
    'From: <sip:34020000001320000001@192.168.1.10>;tag=fromtag1\r\n'
    'To: <sip:34020000001310000001@192.168.1.20>;tag=totag1\r\n'
    'Call-ID: %s\r\nCSeq: 2 BYE\r\n' % CALLID))
add(B, A, 5060, 5060, sip('SIP/2.0 200 OK',
    'Via: SIP/2.0/UDP 192.168.1.10:5060;branch=z9hG4bK-bye-1\r\n'
    'From: <sip:34020000001320000001@192.168.1.10>;tag=fromtag1\r\n'
    'To: <sip:34020000001310000001@192.168.1.20>;tag=totag1\r\n'
    'Call-ID: %s\r\nCSeq: 2 BYE\r\n' % CALLID))

out = sys.argv[1]
with open(out, 'wb') as f:
    f.write(struct.pack('<IHHiIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1))
    for ts_, data in pkts:
        sec = int(ts_); usec = int((ts_ - sec) * 1e6)
        f.write(struct.pack('<IIII', sec, usec, len(data), len(data)))
        f.write(data)
print('wrote %d packets -> %s' % (len(pkts), out))
