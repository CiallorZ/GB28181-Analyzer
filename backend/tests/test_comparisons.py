"""Offline comparison acceptance, using only the temporary test database."""
from datetime import timedelta
from time import perf_counter

import pytest
from sqlalchemy import create_engine, insert, inspect, select

from app.core.timeutil import utcnow
from app.models.entities import (
    AnalysisTask, Base, BusinessSession, CaptureFile, MediaStream, PacketIndex, TaskComparison, TaskStatus,
)
from app.services.comparison import SESSION_FIELDS, STREAM_FIELDS, align, snapshot, verdict
from app.services.retention import auto_purge, settings

API = '/api/v1/comparisons'


def session(i, calls=(), device='cam', **kwargs):
    row = dict.fromkeys(SESSION_FIELDS, 1)
    row.update(id=i, call_ids=list(calls), device_id=device, channel_id='ch', session_type='live')
    return {**row, **kwargs}


def stream(i, parent, ssrc, **kwargs):
    row = dict.fromkeys(STREAM_FIELDS, 1)
    row.update(id=i, session_id=parent, ssrc=ssrc, transport='UDP', payload_type=96)
    return {**row, **kwargs}


@pytest.mark.parametrize(('a', 'b', 'expected'), [
    ([session(1, ['x','y'])], [session(9, ['y','z'], 'other')], ['exact']),
    ([session(1, ['x'])], [session(9, ['z'])], ['inferred']),
    ([session(1, ['x','y'])], [session(8,['x']), session(9,['y'])], ['ambiguous']),
    ([session(1), session(2)], [session(3)], ['ambiguous']),
    ([session(1, device=None)], [session(2, device=None)], ['unmatched','unmatched']),
])
def test_session_alignment(a, b, expected):
    groups = list(align(a, b, 'sessions'))
    assert [g[0] for g in groups] == expected
    assert sum(len(x) + len(y) for _, x, y in groups) == len(a) + len(b)


def test_same_input_and_missing_values():
    sessions, streams = [session(1,['x'])], [stream(1,1,0)]
    res, summary = snapshot((sessions,sessions), (streams,streams), ([],[]))
    assert all(cell[2] == 'same' for layer in ('sessions','streams')
               for r in res[layer] for cell in r['fields'].values())
    assert summary == dict(aligned_sessions=1, aligned_streams=1, structural=0,
                           beyond_tolerance=0, unknown=0, unaligned=0)
    assert verdict('fps', None, None) == verdict('fps', None, 0) == 'unknown'


@pytest.mark.parametrize(('field','a','b','expected'), [
    ('avg_bitrate',100,110,'same'), ('avg_bitrate',100,110.1,'different'),
    ('peak_bitrate',0,0.1,'different'), ('total_duration',0.1,0.15,'same'),
    ('jitter_max',1,6,'same'), ('jitter_avg',1,6.01,'different'),
    ('seq_gap_packets',0,10,'same'), ('duplicate_count',0,11,'different'),
    ('negotiated_port',100,101,'different'), ('has_audio',False,True,'different'),
])
def test_tolerance(field, a, b, expected):
    assert verdict(field, a, b) == expected


def test_media_and_rules_respect_local_alignment():
    sessions = ([session(1), session(2, device=None)], [session(9)])
    streams = ([stream(10,1,0), stream(11,1,None,payload_type=97), stream(12,2,999)],
               [stream(20,9,0), stream(21,9,888,payload_type=97), stream(22,9,999,payload_type=98)])
    def event(i, sid, mid, severity):
        return dict(id=i, session_id=sid, stream_id=mid, rule_id='R1', severity=severity)
    events = ([event(1,1,10,'info'), event(2,1,11,'warning'), event(3,2,12,'critical')],
              [event(8,9,20,'info'), {**event(9,None,None,'warning'), 'rule_id':'R2'}])
    r, s = snapshot(sessions, streams, events)
    assert [(row['method'],row['confidence']) for row in r['streams']] == [('exact','low'),('inferred','low')]
    assert r['diagnostics'][0]['fields'] == {'count':[2,1,'different'], 'severity':['warning','info','different']}
    assert r['diagnostics'][1]['fields']['count'] == [None,1,'only_b']
    assert r['unmatched_totals'] == dict(sessions=1, streams=2, diagnostics=1)
    assert s['unaligned'] == 4 and s['structural'] == 2 and s['beyond_tolerance'] == 0
    assert r['streams'][1]['fields']['ssrc'] == [None,888,'unknown']


def test_nonunique_streams_are_never_paired():
    groups = list(align([stream(1,1,55),stream(2,1,55)], [stream(3,2,55)], 'streams'))
    assert len(groups) == 1 and groups[0][0] == 'unmatched'


def task_pair(make_task):
    return {f'task_{side}_id':make_task(side, status=TaskStatus.COMPLETED).id for side in 'ab'}


def test_api_contract_and_snapshot(db, client, make_task):
    pair = task_pair(make_task)
    for side in 'ab':
        db.add(BusinessSession(task_id=pair[f'task_{side}_id'], call_ids=['call'], negotiated_port=5060))
    db.commit()
    res = client.post(API, json={**pair, 'label_a':'设备\n侧|A', 'label_b':'平台侧'})
    assert res.status_code == 201
    data = res.json()
    url = f"{API}/{data['id']}"
    assert data['label_a'] == '设备侧|A' and not data['stale']
    assert data['result']['sessions'][0]['fields']['negotiated_port'] == [5060,5060,'same']
    assert data['fingerprint']['a']['sessions'] == 1 and 'checksum' in data['fingerprint']['a']['files'][0]
    for side in 'ab':
        session_id = data['result']['sessions'][0][side]
        assert client.get(f'/api/v1/sessions/{session_id}/source').json() == {'task_id': pair[f'task_{side}_id']}
    assert client.get('/api/v1/sessions/-1/source').status_code == 404
    assert client.get(url).json() == data
    assert client.get(url+'/report?format=json').json() == data
    md = client.get(url+'/report?format=md')
    assert f"comparison-{data['id']}.md" in md.headers['content-disposition']
    for value in ['设备侧&#124;A','| negotiated_port | 5060 | 5060 | same |','## 局限声明','快照过期 否']:
        assert value in md.text
    second = client.post(API,json=pair).json()
    assert client.get(API+'?limit=1').json()['items'][0]['id'] == second['id']
    assert client.get(API+'?limit=1&offset=1').json()['items'][0]['id'] == data['id']
    assert client.get(API+'?offset=2').json() == {'total':2, 'items':[]}
    task = db.get(AnalysisTask,pair['task_a_id'])
    task.completed_at = utcnow()
    row = db.scalar(select(BusinessSession).where(BusinessSession.task_id == task.id))
    row.negotiated_port = 5062
    db.commit()
    updated = client.get(url).json()
    assert updated['stale'] and updated['result'] == data['result']
    assert client.get(url+'/report?format=json').json() == updated
    assert '快照过期 是' in client.get(url+'/report').text
    assert client.delete(url).status_code == 204
    assert client.get(url).status_code == 404
    assert client.delete(url).status_code == 404
    db.delete(task)
    db.commit()
    assert client.get(API).json()['total'] == 0


def test_errors(client, make_task):
    pair = task_pair(make_task)
    for change, status in [
        ({'task_b_id':pair['task_a_id']},400), ({'task_a_id':-1},404),
        ({'task_b_id':make_task('pending').id},409), ({'label_a':'a'*101},422),
    ]:
        assert client.post(API,json={**pair, **change}).status_code == status
    assert client.get(API+'/123456/report').status_code == 404
    assert client.get(API+'/1/report?format=html').status_code == 422


def test_retention_removes_old_snapshots(db, client, make_task, monkeypatch):
    pair = task_pair(make_task)
    old, recent = [client.post(API,json=pair).json()['id'] for _ in range(2)]
    db.get(TaskComparison,old).created_at = utcnow() - timedelta(days=2)
    db.commit()
    monkeypatch.setattr(settings,'KEEP_DAYS',1)
    auto_purge(db)
    assert client.get(f'{API}/{old}').status_code == 404
    assert client.get(f'{API}/{recent}').status_code == 200


def test_create_all_extends_existing_sqlite(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'existing.db'}")
    try:
        tables = [t for t in Base.metadata.sorted_tables if t is not TaskComparison.__table__]
        Base.metadata.create_all(engine, tables=tables)
        with engine.begin() as conn:
            conn.execute(insert(AnalysisTask).values(name='既有任务'))
        before = inspect(engine).get_table_names()
        Base.metadata.create_all(engine)
        assert set(inspect(engine).get_table_names()) - set(before) == {'task_comparison'}
        assert all(f['options']['ondelete'] == 'CASCADE'
                   for f in inspect(engine).get_foreign_keys('task_comparison'))
        with engine.connect() as conn:
            assert conn.scalar(select(AnalysisTask.name)) == '既有任务'
    finally:
        engine.dispose()


def test_typical_scale(db, make_task, client):
    pair = task_pair(make_task)
    for base, tid in enumerate(pair.values(), 1):
        rows = [dict(task_id=tid, id=base*1000+i, call_ids=[str(i)],
                     invite_latency=i/100, negotiated_port=5000) for i in range(500)]
        db.execute(insert(BusinessSession), rows)
        db.execute(insert(MediaStream), [
            dict(task_id=tid, session_id=row['id'], ssrc=i, start_time=1, end_time=3,
                 avg_bitrate=100+base, peak_bitrate=150+base, jitter_avg=3+base)
            for row in rows for i in range(4)])
    db.commit()
    start = perf_counter()
    response = client.post(API,json=pair)
    elapsed = perf_counter() - start
    print(f"POST comparison, 500 sessions / 2000 streams per side: {elapsed:.3f}s, {len(response.content)} bytes")
    assert response.status_code == 201
    result = response.json()['result']
    assert result['truncated'] and result['totals'] == dict(sessions=500, streams=2000, diagnostics=0)
    assert len(result['sessions']) == 200 and len(result['streams']) == 500
    assert elapsed < 1.0


def test_shared_detail_budget_includes_unmatched(monkeypatch):
    from app.services.comparison import LIMITS
    for key in LIMITS:
        monkeypatch.setitem(LIMITS, key, 1)
    a, b = session(1, ['x']), session(2, ['x'])
    streams = ([stream(1,1,1), stream(2,None,2)], [stream(3,2,1)])
    rules = [dict(id=i, session_id=None, stream_id=None, rule_id=str(i), severity='info') for i in range(2)]
    result, summary = snapshot(([a,session(5,device=None)],[b]), streams, (rules,rules))
    assert result['unmatched_totals'] == dict(sessions=1, streams=1, diagnostics=0)
    assert result['totals'] == dict(sessions=1, streams=1, diagnostics=2)
    assert result['truncated'] and not result['unmatched']
    assert summary['unaligned'] == 2 and summary['structural'] == 0
    assert all(result['diagnostics'][0]['fields'][key][2] == 'same' for key in ('count','severity'))


@pytest.mark.parametrize('change', ['checksum','sessions','streams','state'])
def test_source_changes_and_missing_links(db, client, make_task, change):
    pair = task_pair(make_task)
    tid = pair['task_b_id']
    source = db.scalar(select(CaptureFile).where(CaptureFile.task_id == tid))
    packet = PacketIndex(task_id=tid, file_id=source.id, packet_number=1)
    db.add(packet)
    db.commit()
    data = client.post(API, json=pair).json()
    url = f"{API}/{data['id']}"
    assert data['links']['b']['packets']
    db.delete(packet)
    db.commit()
    after_purge = client.get(url).json()
    assert not after_purge['links']['b']['packets'] and not after_purge['stale']
    if change == 'checksum':
        source.checksum = 'a' * 64
    elif change == 'sessions':
        db.add(BusinessSession(task_id=tid))
    elif change == 'streams':
        db.add(MediaStream(task_id=tid,start_time=0,end_time=1))
    else:
        db.get(AnalysisTask,tid).status = TaskStatus.ANALYZING
    db.commit()
    stale = client.get(url).json()
    assert stale['stale'] and stale['fingerprint'] == data['fingerprint'] and stale['result'] == data['result']


def test_late_difference_and_unmatched_survive_in_both_reports(client, make_task, db):
    pair = task_pair(make_task)
    for side in 'ab':
        size = 202 if side == 'a' else 201
        db.execute(insert(BusinessSession), [
            dict(task_id=pair[f'task_{side}_id'], call_ids=[str(i)],
                 negotiated_port=5002 if i == 200 and side == 'b' else 5000)
            for i in range(size)])
    db.commit()
    data = client.post(API, json=pair).json()
    url = f"{API}/{data['id']}/report"
    result = data['result']
    assert result['detail_counts']['sessions'] == {'different':1, 'kept_different':1, 'kept_unmatched':1}
    assert result['sessions'][0]['fields']['negotiated_port'] == [5000,5002,'different']
    assert result['unmatched'][0]['observed']['call_ids'] == ['201']
    assert len(result['sessions']) == 199
    assert client.get(url+'?format=json').json() == data
    report = client.get(url).text
    assert '差异记录保留 1 / 1，未对齐记录保留 1 / 1' in report
    assert '| negotiated_port | 5000 | 5002 | different |' in report
