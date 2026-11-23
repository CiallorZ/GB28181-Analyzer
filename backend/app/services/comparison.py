"""Deterministic comparison of two database snapshots."""
from collections import Counter, defaultdict
from decimal import Decimal

SESSION_FIELDS = (
    'signal_status media_status end_reason negotiated_ip negotiated_port negotiated_transport '
    'subject_ssrc sdp_ssrc invite_latency sdp_negotiation_latency first_media_latency '
    'first_keyframe_latency media_duration total_duration media_stream_count critical_count warning_count'
).split()
STREAM_FIELDS = (
    'present ssrc payload_type transport packet_count avg_bitrate peak_bitrate seq_gap_packets '
    'out_of_order_count duplicate_count jitter_avg jitter_max max_gap interruption_count codec '
    'width height fps keyframe_count has_audio rebuild'
).split()
TOLERANCES = {
    **dict.fromkeys(('invite_latency', 'sdp_negotiation_latency', 'first_media_latency',
                    'first_keyframe_latency', 'media_duration', 'total_duration', 'max_gap'), 0.05),
    **dict.fromkeys(('avg_bitrate', 'peak_bitrate'), 0.1),
    **dict.fromkeys(('jitter_avg', 'jitter_max'), 5),
    **dict.fromkeys(('seq_gap_packets', 'out_of_order_count', 'duplicate_count'), 10),
}
LIMITS = {'sessions': 200, 'streams': 500, 'diagnostics': 300}
LIMITATIONS = [
    '对比只描述两侧观察到的结果差异，不证明差异发生的位置或原因。',
    '抓包点、时间窗、过滤条件不同都会造成差异。',
    '未对齐项不能视为「不存在」。',
]
METHODS = '会话按 Call-ID 交集精确对齐，其次按唯一设备、通道和会话类型低置信度推断。流只在已对齐会话内按 唯一 SSRC 精确对齐，或按唯一传输方式和载荷类型低置信度推断；流继承会话的低置信度。'


def verdict(field, a, b):
    if a is None or b is None or a == 'unknown' or b == 'unknown':
        return 'unknown'
    if a == b:
        return 'same'
    if field in TOLERANCES:
        x, y = Decimal(str(a)), Decimal(str(b))
        limit = Decimal(str(TOLERANCES[field]))
        if field in ('avg_bitrate', 'peak_bitrate'):
            limit *= abs(x)
        if abs(x - y) <= limit:
            return 'same'
    return 'different'


def keys(row, layer, exact):
    if exact and layer == 'sessions':
        return set(filter(None, row['call_ids'] or []))
    fields = ('ssrc',) if exact else (
        ('device_id', 'channel_id', 'session_type') if layer == 'sessions' else ('transport', 'payload_type'))
    key = tuple(row[f] for f in fields)
    return [key] if all(v is not None and v != '' for v in key) else []


def align(left, right, layer):
    """Index shared keys. Traverse each connected component once, including collisions."""
    sides = [left, right]
    used = set()
    for exact in (True, False):
        indexes = [defaultdict(list), defaultdict(list)]
        links = defaultdict(set)
        for side, rows in enumerate(sides):
            for i, row in enumerate(rows):
                for key in keys(row, layer, exact):
                    indexes[side][key].append((side, i))
        for key in indexes[0].keys() & indexes[1].keys():
            nodes = indexes[0][key] + indexes[1][key]
            # Uniqueness is checked on the original two populations.
            if not exact and any(n in used for n in nodes):
                remaining = [[sides[side][i] for nside, i in nodes
                              if nside == side and (side, i) not in used] for side in (0, 1)]
                used.update(nodes)
                if any(remaining):
                    yield 'ambiguous' if layer == 'sessions' and all(remaining) else 'unmatched', *remaining
                continue
            pivot = nodes[0]
            for node in nodes:
                links[pivot].add(node)
                links[node].add(pivot)
        for node in sorted(links):
            if node in used:
                continue
            group = [[], []]
            stack = [node]
            while stack:
                n = stack.pop()
                if n in used:
                    continue
                used.add(n)
                group[n[0]].append(sides[n[0]][n[1]])
                stack.extend(links[n] - used)
            if all(len(g) == 1 for g in group):
                method = 'exact' if exact else 'inferred'
            else:
                method = 'ambiguous' if layer == 'sessions' else 'unmatched'
            yield method, *group
    for side, rows in enumerate(sides):
        for i, row in enumerate(rows):
            if (side, i) not in used:
                yield 'unmatched', [] if side else [row], [row] if side else []


def alignment_evidence(layer, method, a, b):
    if method == 'exact':
        if layer == 'sessions':
            return {'call_ids': sorted(keys(a, layer, True) & keys(b, layer, True))}
        return {'ssrc': a['ssrc']}
    fields = ('device_id', 'channel_id', 'session_type') if layer == 'sessions' else ('transport', 'payload_type')
    return {key: a[key] for key in fields}


def snapshot(sessions, streams, events):
    result = {k: [] for k in LIMITS}
    result.update(unmatched=[], limitations=LIMITATIONS, methods=METHODS, tolerances=TOLERANCES)
    # Each bucket is bounded while scanning. Rows outside the detail budget still count.
    buckets = {layer: defaultdict(list) for layer in LIMITS}
    differing = Counter()
    def retain(layer, bucket, row):
        items = buckets[layer][bucket]
        if len(items) < LIMITS[layer]:
            items.append(row)

    def retain_pair(layer, row):
        statuses = {cell[2] for cell in row['fields'].values()}
        changed = bool(statuses & {'different', 'only_a', 'only_b'})
        differing[layer] += changed
        retain(layer, 'changed' if changed else 'unknown' if 'unknown' in statuses else 'same', row)

    counts = Counter()
    unmatched_counts = Counter()
    summary = dict(aligned_sessions=0, aligned_streams=0, structural=0, beyond_tolerance=0, unknown=0)
    eligible = [[set(), set()] for _ in range(2)]
    by_session = [defaultdict(list), defaultdict(list)]
    for side, rows in enumerate(streams):
        for row in rows:
            by_session[side][row['session_id']].append(row)

    def record(layer, method, aa, bb, confidence=None):
        if method in ('ambiguous', 'unmatched'):
            for side, group in [('a', aa), ('b', bb)]:
                for row in group:
                    unmatched_counts[layer] += 1
                    if len(buckets[layer][method]) < LIMITS[layer]:
                        identifiers = {'sessions': ('call_ids', 'device_id', 'channel_id'),
                                       'streams': ('session_id', 'ssrc', 'transport', 'payload_type'),
                                       'diagnostics': ('rule_id', 'session_id', 'stream_id')}[layer]
                        retain(layer, method, dict(layer=layer, side=side, id=row['id'], method=method,
                            observed={key: row[key] for key in identifiers},
                            status='ambiguous' if method == 'ambiguous' else 'only_' + side))
            return
        a, b = aa[0], bb[0]
        counts[layer] += 1
        summary['aligned_' + layer] += 1
        cells = {}
        for field in SESSION_FIELDS if layer == 'sessions' else STREAM_FIELDS:
            x, y = a[field], b[field]
            status = verdict(field, x, y)
            if status == 'different':
                summary['beyond_tolerance' if field in TOLERANCES else 'structural'] += 1
            elif status == 'unknown':
                summary['unknown'] += 1
            cells[field] = [x, y, status]
        for side, row in enumerate((a, b)):
            eligible[side][int(layer == 'streams')].add(row['id'])
        retain_pair(layer, dict(a=a['id'], b=b['id'], session_a=a.get('session_id', a['id']),
                session_b=b.get('session_id', b['id']), method=method, evidence=alignment_evidence(layer, method, a, b),
                confidence='low' if 'inferred' in (method, confidence) else 'high', fields=cells))

    for method, aa, bb in align(*sessions, 'sessions'):
        record('sessions', method, aa, bb)
        if method in ('exact', 'inferred'):
            for sm, sa, sb in align(by_session[0].pop(aa[0]['id'], []),
                                    by_session[1].pop(bb[0]['id'], []), 'streams'):
                record('streams', sm, sa, sb, method)
    for side, groups in enumerate(by_session):
        for rows in groups.values():
            record('streams', 'unmatched', [] if side else rows, rows if side else [])
    rank = ['unknown', 'info', 'warning', 'critical']
    rules = [dict(), dict()]
    for side, rows in enumerate(events):
        for row in rows:
            if any(row[key] is not None and row[key] not in eligible[side][i]
                   for i, key in enumerate(('session_id', 'stream_id'))):
                record('diagnostics', 'unmatched', [] if side else [row], [row] if side else [])
                continue
            stat = rules[side].setdefault(row['rule_id'], [0, 0])
            stat[0] += 1
            stat[1] = max(stat[1], rank.index(row['severity']))
    for key in sorted(rules[0].keys() | rules[1].keys()):
        a, b = (r.get(key) for r in rules)
        counts['diagnostics'] += 1
        fields = {}
        for i, field in enumerate(('count', 'severity')):
            x, y = (None if v is None else (rank[v[i]] if i else v[i]) for v in (a, b))
            status = ('only_a' if a else 'only_b') if not a or not b else verdict(field, x, y)
            fields[field] = [x, y, status]
            if status == 'different':
                summary['structural'] += 1
            elif status == 'unknown':
                summary['unknown'] += 1
        retain_pair('diagnostics', dict(rule_id=key, fields=fields))
    result['totals'] = {k: counts[k] for k in LIMITS}
    result['unmatched_totals'] = {k: unmatched_counts[k] for k in LIMITS}
    result['detail_counts'] = {}
    for layer, cap in LIMITS.items():
        pool = buckets[layer]
        unpaired = pool['ambiguous'] + pool['unmatched']
        paired = pool['changed'] + pool['unknown'] + pool['same']
        # Keep up to a quarter for unpaired evidence; reuse every unused slot.
        reserve = min(len(unpaired), max(1, cap // 4)) if cap > 1 else 0
        result[layer] = paired[:cap - reserve]
        if counts[layer] + unmatched_counts[layer] <= cap:
            order_key = 'rule_id' if layer == 'diagnostics' else 'a'
            result[layer].sort(key=lambda row: row[order_key])
        kept = unpaired[:cap - len(result[layer])]
        result['unmatched'].extend(kept)
        result['detail_counts'][layer] = dict(different=differing[layer],
            kept_different=min(len(pool['changed']), len(result[layer])), kept_unmatched=len(kept))
    result['truncated'] = any(counts[k] + unmatched_counts[k] > cap for k, cap in LIMITS.items())
    summary['unaligned'] = sum(unmatched_counts.values())
    return result, summary
