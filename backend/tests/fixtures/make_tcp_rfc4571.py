import struct
import sys

def csum(b):
    if len(b) % 2: b += b'\0'
    s = sum(struct.unpack('!%dH' % (len(b)//2), b))
    while s >> 16: s = (s & 0xffff) + (s >> 16)
    return (~s) & 0xffff

def ip_tcp(src, dst, sport, dport, seq, ack, flags, payload, ident):
    off_flags = (5 << 12) | flags
    tcp = struct.pack('!HHIIHHHH', sport, dport, seq, ack, off_flags, 65535, 0, 0) + payload
    pseudo = bytes(int(x) for x in src.split('.')) + bytes(int(x) for x in dst.split('.')) + struct.pack('!BBH', 0, 6, len(tcp))
    tc = csum(pseudo + tcp)
    tcp = tcp[:16] + struct.pack('!H', tc) + tcp[18:]
    ip = struct.pack('!BBHHHBBH4s4s', 0x45, 0, 20+len(tcp), ident, 0x4000, 64, 6, 0,
                     bytes(int(x) for x in src.split('.')), bytes(int(x) for x in dst.split('.')))
    ip = ip[:10] + struct.pack('!H', csum(ip)) + ip[12:]
    return ip + tcp

def eth(p):
    return b'\x00\x11\x22\x33\x44\x55' + b'\x66\x77\x88\x99\xaa\xbb' + b'\x08\x00' + p

def rtp(seq, ts, ssrc, payload):
    return struct.pack('!BBHII', 0x80, 96, seq & 0xffff, ts & 0xffffffff, ssrc) + payload

def ps_pack(payload, pts):
    pack = b'\x00\x00\x01\xba' + b'\x44' + b'\x00\x04\x00\x04\x01\x00\x01\x8b\xc5' + b'\x00\x00'
    pes = (b'\x00\x00\x01\xe0' + struct.pack('!H', 8+len(payload)) + b'\x80\x80\x05' +
           struct.pack('!Q', (2 << 30) | (pts & 0x1fffffff))[:5] + payload)
    return pack + pes

SPS = b'\x00\x00\x00\x01\x67\x42\xc0\x1e\xd9\x00\x50\x05\xbb\x01\x10\x00\x00\x03\x00\x10\x00\x00\x03\x03\xc0\xf1\x83\x19\x60'
PPS = b'\x00\x00\x00\x01\x68\xce\x3c\x80'

A, B = '192.168.1.10', '192.168.1.20'
# 设备主动连我方 8808（setup=active），源端口 40000
pkts = []
t = 0.0
def add(p):
    global t
    pkts.append((t, eth(p)))
    t += 0.005

add(ip_tcp(A, B, 40000, 8808, 1000, 0, 0x002, b'', 1))
add(ip_tcp(B, A, 8808, 40000, 5000, 1001, 0x012, b'', 2))
add(ip_tcp(A, B, 40000, 8808, 1001, 5001, 0x010, b'', 3))

# 第一个段里混入非对齐前缀（模拟抓包起点不在包边界）
stream = b'\xde\xad\xbe\xef' * 300   # 1200 字节垃圾前缀
seq = 1001
ssrc = 0x00001234
ts = 0
next_seq = [0]
for i in range(150):
    nal = SPS + PPS + (b'\x00\x00\x00\x01\x65' + b'\x88'*900 if i % 25 == 0 else b'\x00\x00\x00\x01\x41' + b'\x55'*250)
    body = ps_pack(nal, ts)
    for c in range(0, len(body), 1000):
        r = rtp(next_seq[0], ts, ssrc, body[c:c+1000]); next_seq[0] += 1
        stream += struct.pack('!H', len(r)) + r
    ts += 3600
    t += 0.04

for c in range(0, len(stream), 1400):
    add(ip_tcp(A, B, 40000, 8808, seq, 5001, 0x018, stream[c:c+1400], 100+c))
    seq += len(stream[c:c+1400])

out = sys.argv[1]
with open(out, 'wb') as f:
    f.write(struct.pack('<IHHiIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1))
    for ts_, data in pkts:
        s = int(ts_); u = int((ts_-s)*1e6)
        f.write(struct.pack('<IIII', s, u, len(data), len(data))); f.write(data)
print('wrote %d packets -> %s' % (len(pkts), out))
