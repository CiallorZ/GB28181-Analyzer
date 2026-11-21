from app.models.entities import BusinessSession, MediaStream


def test_timeline_does_not_invent_time_for_max_gap(client, db, make_task):
    task = make_task()
    session = BusinessSession(task_id=task.id, session_type='live', call_ids=[])
    db.add(session)
    db.flush()
    db.add(MediaStream(task_id=task.id, session_id=session.id, ssrc=1234,
                       transport='UDP', start_time=2.0, end_time=20.0,
                       packet_count=10, max_gap=9.0))
    db.commit()
    response = client.get(f'/api/v1/sessions/{session.id}/timeline')
    assert response.status_code == 200
    events = response.json()['items']
    assert [event['label'] for event in events] == ['RTP 首包', 'RTP 末包']
    assert [event['timestamp'] for event in events] == [2.0, 20.0]
