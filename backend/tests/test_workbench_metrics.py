from app.models.entities import MediaMetric, MediaStream


def test_task_metrics_include_unassigned_streams_and_exclude_other_tasks(client, db, make_task):
    task = make_task('抓包 A')
    other = make_task('抓包 B')
    first = MediaStream(task_id=task.id, ssrc=42, start_time=0, end_time=3)
    second = MediaStream(task_id=other.id, start_time=0, end_time=3)
    db.add_all([first, second])
    db.flush()
    db.add_all([
        MediaMetric(stream_id=first.id, timestamp=2, bitrate=18, jitter=0),
        MediaMetric(stream_id=first.id, timestamp=1, bitrate=12),
        MediaMetric(stream_id=second.id, timestamp=1, bitrate=999),
    ])
    db.commit()

    response = client.get(f'/api/v1/tasks/{task.id}/media-metrics', params=[
        ('stream_id', first.id), ('stream_id', second.id),
    ])
    assert response.status_code == 200
    item, = response.json()['items']
    assert item['stream_id'] == first.id
    assert item['bitrate_series'] == [{'t': 1, 'v': 12}, {'t': 2, 'v': 18}]
    assert item['jitter_series'] == [{'t': 2, 'v': 0}]


def test_quality_reads_all_sessions_and_orphans_in_two_queries(client, db, make_task):
    from sqlalchemy import event
    from app.models.entities import BusinessSession

    task = make_task('51 sessions')
    sessions = [BusinessSession(task_id=task.id) for _ in range(51)]
    db.add_all(sessions)
    db.flush()
    linked = MediaStream(task_id=task.id, session_id=sessions[-1].id, start_time=0, end_time=1)
    orphan = MediaStream(task_id=task.id, start_time=0, end_time=1)
    other = MediaStream(task_id=make_task('other').id, start_time=0, end_time=1)
    db.add_all([linked, orphan, other])
    db.flush()
    db.add(MediaMetric(stream_id=orphan.id, timestamp=1, bitrate=12, jitter=0))
    db.commit()
    url = f'/api/v1/tasks/{task.id}/media-quality'
    selects = []

    def count(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith('SELECT'):
            selects.append(statement)

    engine = db.get_bind()
    event.listen(engine, 'before_cursor_execute', count)
    try:
        response = client.get(url)
    finally:
        event.remove(engine, 'before_cursor_execute', count)
    assert response.is_success and len(selects) == 2
    items = {item['id']: item for item in response.json()['items']}
    assert set(items) == {linked.id, orphan.id}
    assert items[linked.id]['session_id'] == sessions[-1].id
    assert items[orphan.id]['session_id'] is None
    assert items[orphan.id]['jitter'] == [[1, 0]]
    assert items[orphan.id]['bitrate'] == [[1, 12]]
