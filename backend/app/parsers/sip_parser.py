#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SIP / SDP 解析器（M03 / M04）

自研解析，不依赖 tshark 的 SIP 解析结果，只从 tshark 取原始字节。

关键实现点（都踩过坑）：
1. tshark 的 sip.msg_hdr 从 Via 开始，不含请求行/状态行 —— 必须单独取
2. 消息正文多为 GB18030 编码（国标要求），不能按 UTF-8 硬解
3. 一个 Call-ID 可能承载多次事务（INVITE + BYE），不能当成一个对话
4. Dialog 由 Call-ID + From-Tag + To-Tag 三者确定，缺一不可
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

# ---------------------------------------------------------------
# 常量
# ---------------------------------------------------------------
SIP_METHODS = {
    'REGISTER', 'INVITE', 'ACK', 'BYE', 'CANCEL', 'MESSAGE',
    'INFO', 'OPTIONS', 'SUBSCRIBE', 'NOTIFY', 'PRACK', 'UPDATE',
    'REFER', 'PUBLISH',
}

# 国标 MANSCDP 命令类型
GB_COMMANDS = {
    'Catalog': '设备目录',
    'DeviceInfo': '设备信息',
    'DeviceStatus': '设备状态',
    'DeviceControl': '设备控制',
    'Keepalive': '心跳',
    'Alarm': '报警',
    'ConfigDownload': '配置下载',
    'PresetQuery': '预置位',
    'RecordInfo': '录像查询',
    'Broadcast': '语音广播',
    'MediaStatus': '媒体状态',
}

PROVISIONAL_CODES = {100, 180, 183}
MAX_BODY = 512 * 1024          # 单个 SIP 正文上限，防畸形数据


@dataclass
class SdpInfo:
    """SDP 解析结果（M04）"""
    version: str = ''
    origin_user: str = ''
    origin_session_id: str = ''
    origin_version: str = ''
    origin_address: str = ''
    session_name: str = ''
    connection_address: str = ''
    timing: str = ''

    media: list = field(default_factory=list)   # [{type, port, protocol, formats, attrs}]
    attributes: dict = field(default_factory=dict)
    raw: str = ''

    # 国标扩展字段
    y_ssrc: str = ''
    f_field: str = ''
    setup: str = ''            # active/passive/actpass
    stream_mode: str = ''      # sendonly/recvonly/sendrecv
    is_tcp: bool = False
    xstreamtype: str = ''
    errors: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'origin_user': self.origin_user,
            'origin_session_id': self.origin_session_id,
            'session_name': self.session_name,
            'connection_address': self.connection_address,
            'media': self.media,
            'attributes': self.attributes,
            'y_ssrc': self.y_ssrc,
            'f_field': self.f_field,
            'setup': self.setup,
            'stream_mode': self.stream_mode,
            'is_tcp': self.is_tcp,
            'xstreamtype': self.xstreamtype,
            'errors': self.errors,
        }


def make_dialog_key(call_id: str, from_tag: str, to_tag: str) -> str:
    """Dialog 键的唯一构造入口，所有调用方必须用这里，避免排序规则不一致"""
    tags = sorted([from_tag or '', to_tag or ''])
    return '%s|%s|%s' % (call_id or '', tags[0], tags[1])


@dataclass
class SipInfo:
    """单条 SIP 消息（M03）"""
    packet_number: int = 0
    timestamp: float = 0.0
    is_request: bool = True
    method: str = ''
    status_code: int | None = None
    reason_phrase: str = ''

    source_ip: str = ''
    source_port: int | None = None
    destination_ip: str = ''
    destination_port: int | None = None

    call_id: str = ''
    from_tag: str = ''
    to_tag: str = ''
    cseq_number: int | None = None
    cseq_method: str = ''
    via_branch: str = ''
    via_received: str = ''

    request_uri: str = ''
    user_agent: str = ''
    contact: str = ''
    content_type: str = ''
    expires: str = ''
    max_forwards: str = ''
    subject: str = ''

    headers: dict = field(default_factory=dict)
    body: str = ''
    sdp: SdpInfo | None = None

    # 国标业务
    gb_command: str = ''
    device_id: str = ''
    sn: str = ''
    result: str = ''
    xml_items: list = field(default_factory=list)
    parse_errors: list = field(default_factory=list)

    def dialog_key(self) -> str:
        """Dialog 唯一键：Call-ID + From-Tag + To-Tag（排序后，保证双向一致）"""
        return make_dialog_key(self.call_id, self.from_tag, self.to_tag)

    def transaction_key(self) -> str:
        """事务键：Via branch + CSeq method"""
        return '%s|%s|%s' % (self.via_branch, self.cseq_number, self.cseq_method)


# ---------------------------------------------------------------
# 头域解析
# ---------------------------------------------------------------
_HDR_ALIAS = {
    'i': 'call-id', 'f': 'from', 't': 'to', 'm': 'contact',
    'v': 'via', 'l': 'content-length', 'c': 'content-type',
    's': 'subject', 'k': 'supported',
}


def _parse_headers(header_block: str) -> dict:
    """解析 SIP 头域，支持折行与别名，保留重复头"""
    result: dict = {}
    raw_lines = header_block.replace('\r\n', '\n').split('\n')

    # 合并折行（以空格/Tab 开头的续行）
    merged: list[str] = []
    for ln in raw_lines:
        if ln[:1] in (' ', '\t') and merged:
            merged[-1] += ' ' + ln.strip()
        elif ln.strip():
            merged.append(ln)

    for ln in merged:
        if ':' not in ln:
            continue
        name, value = ln.split(':', 1)
        name = name.strip().lower()
        name = _HDR_ALIAS.get(name, name)
        # Via 可以出现多次，CSeq 等只取第一个
        if name in result:
            if name in ('via', 'route', 'record-route', 'contact'):
                result[name] = result[name] + '\n' + value.strip()
            continue
        result[name] = value.strip()
    return result


def _extract_tag(header: str) -> str:
    m = re.search(r'[;,]?\s*tag\s*=\s*([^;,\s>]+)', header or '')
    return m.group(1) if m else ''


def _extract_uri_id(header: str) -> str:
    """从 sip:xxx@ip 中取出 xxx（通常是设备/平台国标 ID）"""
    m = re.search(r'sip:([^@;>\s]+)@', header or '')
    if m:
        return m.group(1)
    m = re.search(r'sip:([^@;>\s]+)', header or '')
    return m.group(1) if m else ''


# ---------------------------------------------------------------
# SDP 解析（M04）
# ---------------------------------------------------------------
def parse_sdp(text: str) -> SdpInfo | None:
    if not text or 'v=' not in text[:20]:
        return None
    sdp = SdpInfo(raw=text[:8000])
    cur_media = None
    for raw in text.replace('\r\n', '\n').split('\n'):
        line = raw.strip()
        if len(line) < 2 or line[1] != '=':
            continue
        k, v = line[0], line[2:]
        if k == 'v':
            sdp.version = v
        elif k == 'o':
            parts = v.split()
            if len(parts) >= 6:
                (sdp.origin_user, sdp.origin_session_id, sdp.origin_version,
                 _net, _addr_type, sdp.origin_address) = parts[:6]
            else:
                sdp.errors.append('o= 行字段不足：%s' % v[:60])
        elif k == 's':
            sdp.session_name = v
        elif k == 'c':
            parts = v.split()
            if len(parts) >= 3:
                sdp.connection_address = parts[2]
            else:
                sdp.errors.append('c= 行字段不足：%s' % v[:60])
        elif k == 't':
            sdp.timing = v
        elif k == 'm':
            parts = v.split()
            if len(parts) >= 3:
                cur_media = {
                    'type': parts[0],
                    'port': _to_int(parts[1]),
                    'protocol': parts[2],
                    'formats': parts[3:],
                    'attributes': {},
                    'connection': '',
                }
                sdp.media.append(cur_media)
                if 'TCP' in parts[2].upper():
                    sdp.is_tcp = True
            else:
                sdp.errors.append('m= 行字段不足：%s' % v[:60])
        elif k in ('y', 'f'):
            # GB/T 28181 附录 F：y= / f= 是会话级独立行，不是 a= 属性。
            # 只处理 a= 分支会漏掉标准写法（实测标准写法解析为 ''）。
            if k == 'y':
                sdp.y_ssrc = v.strip()
            else:
                sdp.f_field = v.strip()
        elif k == 'a':
            if ':' in v:
                name, val = v.split(':', 1)
                name, val = name.strip(), val.strip()
            elif '=' in v:
                # 兼容非标准写法 a=y=00001234（现场抓包常见）
                name, val = v.split('=', 1)
                name, val = name.strip(), val.strip()
            else:
                name, val = v.strip(), ''
            sdp.attributes[name] = val
            if cur_media is not None:
                cur_media['attributes'][name] = val
            # 国标关键扩展
            if name == 'y':
                sdp.y_ssrc = val
            elif name == 'f':
                sdp.f_field = val
            elif name == 'setup':
                sdp.setup = val
            elif name in ('sendonly', 'recvonly', 'sendrecv', 'inactive'):
                sdp.stream_mode = name
            elif name == 'xstreamtype':
                sdp.xstreamtype = val
        elif k == 'b':
            sdp.attributes.setdefault('bandwidth', v)

    if not sdp.media:
        sdp.errors.append('SDP 中没有 m= 媒体描述行')
    return sdp


def _to_int(v):
    try:
        return int(str(v).split('/')[0])
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------
# 国标 XML 正文解析（M03-03）
# ---------------------------------------------------------------
def parse_gb_xml(body: str) -> dict:
    """解析 MANSCDP XML，返回结构化信息"""
    if not body:
        return {}
    txt = body.strip()
    if '<' not in txt:
        return {}
    if len(txt) > MAX_BODY:
        return {'_error': '正文过大，跳过解析'}
    # 去掉 XML 声明前的杂字符
    i = txt.find('<')
    if i > 0:
        txt = txt[i:]
    try:
        root = ET.fromstring(txt)
    except ET.ParseError:
        j = txt.rfind('>')
        if j <= 0:
            return {'_error': 'XML 结构损坏'}
        try:
            root = ET.fromstring(txt[:j + 1])
        except ET.ParseError as e:
            return {'_error': 'XML 解析失败：%s' % e}

    out = {'_tag': root.tag}
    for tag in ('CmdType', 'SN', 'DeviceID', 'DeviceName', 'Result', 'Status',
                'SumNum', 'Event', 'ParentID', 'Manufacturer', 'Model',
                'Firmware', 'Owner', 'CivilCode', 'Address', 'Port',
                'IPAddress', 'Longitude', 'Latitude', 'Secrecy', 'Parental',
                'RegisterWay', 'IFameCmd', 'PTZCmd', 'StartTime', 'EndTime'):
        el = root.find(tag)
        if el is not None and el.text:
            out[tag] = el.text.strip()

    lst = root.find('DeviceList')
    if lst is not None:
        items = []
        for it in lst.findall('Item'):
            d = {}
            for ch in it:
                if ch.text:
                    d[ch.tag] = ch.text.strip()
            if d:
                items.append(d)
        out['items'] = items
        out['Num'] = lst.get('Num', str(len(items)))
        try:
            out['SumNum'] = out.get('SumNum') or str(len(items))
        except Exception:
            pass
    return out


# ---------------------------------------------------------------
# 主解析入口
# ---------------------------------------------------------------
def build_message(raw_header: str, raw_body: bytes, meta: dict) -> SipInfo | None:
    """从 tshark 取出的头块 + 正文构造 SipInfo

    raw_header : msg_hdr（tshark 给的是从 Via 开始的头部，不含起始行）
    raw_body   : 正文原始字节

    注意：tshark 的 `sip.msg_body` 是 FT_NONE 的存在标记（值为 "1"），
    不是十六进制正文；真正的正文通常附在 `sip.msg_hdr` 的空白行之后。
    所以这里必须先从 msg_hdr 里把正文拆出来，否则所有 SDP/MANSCDP 都解析不到。

    meta       : {packet_number, timestamp, src_ip, src_port, dst_ip, dst_port,
                  request_line, status_line, status_code}
    """
    info = SipInfo(
        packet_number=meta.get('packet_number') or 0,
        timestamp=meta.get('timestamp') or 0.0,
        source_ip=meta.get('src_ip') or '',
        source_port=meta.get('src_port'),
        destination_ip=meta.get('dst_ip') or '',
        destination_port=meta.get('dst_port'),
    )

    raw = (raw_header or '').replace('\\r\\n', '\r\n')
    header_text = raw
    for sep in ('\r\n\r\n', '\n\n'):
        if sep in raw:
            head, _, tail = raw.partition(sep)
            header_text = head
            if tail and not raw_body:
                raw_body = tail.encode('utf-8', errors='replace')
            break
    # tshark 的 msg_hdr 可能不含起始行，用单独的字段补
    req_line = (meta.get('request_line') or '').strip()
    stat_line = (meta.get('status_line') or '').strip()

    full_header = header_text
    if req_line and not header_text.startswith(req_line):
        full_header = req_line + '\r\n' + header_text
    elif stat_line and not header_text.startswith('SIP/'):
        full_header = stat_line + '\r\n' + header_text

    # 拆起始行与头域
    lines = full_header.replace('\r\n', '\n').split('\n')
    start_line = lines[0].strip() if lines else ''
    hdr_block = '\n'.join(lines[1:])

    # 判定请求/响应
    if start_line.upper().startswith('SIP/'):
        info.is_request = False
        m = re.match(r'SIP/\d\.\d\s+(\d{3})\s*(.*)', start_line)
        if m:
            info.status_code = int(m.group(1))
            info.reason_phrase = m.group(2).strip()
        else:
            info.parse_errors.append('状态行格式异常：%s' % start_line[:60])
    else:
        info.is_request = True
        parts = start_line.split()
        if parts and parts[0].upper() in SIP_METHODS:
            info.method = parts[0].upper()
            info.request_uri = parts[1] if len(parts) > 1 else ''
        elif parts:
            # 起始行缺失时退化为从 CSeq 推断
            info.parse_errors.append('起始行无法识别：%s' % start_line[:60])

    info.headers = _parse_headers(hdr_block)

    # 关键字段
    h = info.headers
    info.call_id = h.get('call-id', '')
    info.from_tag = _extract_tag(h.get('from', ''))
    info.to_tag = _extract_tag(h.get('to', ''))
    info.contact = h.get('contact', '')
    info.content_type = h.get('content-type', '')
    info.user_agent = h.get('user-agent', '')
    info.expires = h.get('expires', '')
    info.max_forwards = h.get('max-forwards', '')
    info.subject = h.get('subject', '')

    via = h.get('via', '').split('\n')[0]
    m = re.search(r'branch=([^;,\s]+)', via)
    info.via_branch = m.group(1) if m else ''
    m = re.search(r'received=([^;,\s]+)', via)
    info.via_received = m.group(1) if m else ''

    cseq = h.get('cseq', '')
    mc = re.match(r'\s*(\d+)\s+(\S+)', cseq)
    if mc:
        info.cseq_number = int(mc.group(1))
        info.cseq_method = mc.group(2).upper()
    if not info.method and info.cseq_method:
        info.method = info.cseq_method

    # 正文：国标多为 GB18030
    info.body = _decode_body(raw_body)
    if info.body:
        if 'sdp' in info.content_type.lower() or info.body.lstrip().startswith('v='):
            info.sdp = parse_sdp(info.body)
        if '<' in info.body:
            xml = parse_gb_xml(info.body)
            if xml:
                if xml.get('_error'):
                    info.parse_errors.append(xml['_error'])
                info.gb_command = xml.get('CmdType', '')
                info.device_id = xml.get('DeviceID', '')
                info.sn = xml.get('SN', '')
                info.result = xml.get('Result', '')
                info.xml_items = xml.get('items', [])

    # 必填字段校验
    if not info.call_id:
        info.parse_errors.append('缺少 Call-ID')
    if info.cseq_number is None:
        info.parse_errors.append('缺少或无法解析 CSeq')

    return info


def _decode_body(raw: bytes) -> str:
    """正文解码：GB18030 优先（国标要求），其次 UTF-8"""
    if not raw:
        return ''
    if len(raw) > MAX_BODY:
        raw = raw[:MAX_BODY]
    for enc in ('gb18030', 'utf-8', 'latin-1'):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return ''


def body_from_hex(hexstr: str) -> bytes:
    """tshark 的 msg_body 是十六进制字符串"""
    s = re.sub(r'[^0-9a-fA-F]', '', hexstr or '')
    if not s or len(s) % 2:
        return b''
    try:
        return bytes.fromhex(s)
    except ValueError:
        return b''
