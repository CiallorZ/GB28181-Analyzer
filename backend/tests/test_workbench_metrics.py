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
