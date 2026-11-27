"""Cleanup and failed upload must preserve active analysis inputs."""
import asyncio
import errno
from datetime import timedelta

import pytest

from app.api import tasks
from app.core import analysis_control
from app.core.config import settings
from app.core.timeutil import utcnow
from app.models.entities import TaskStatus
from app.services import retention


@pytest.mark.parametrize('policy', ['count', 'age', 'budget', 'manual'])
def test_cleanup_preserves_reserved_inputs(client, db, make_task, tmp_path, monkeypatch, policy):
    active_source = tmp_path / 'active.pcap'
    old_source = tmp_path / 'old.pcap'
    for source in (active_source, old_source):
        source.write_bytes(b'capture')
    active = make_task(path=active_source)
    old = make_task(path=old_source, status=TaskStatus.COMPLETED)
    active.created_at = utcnow() - timedelta(days=5)
    old.created_at = utcnow() - timedelta(days=4)
    survivor = make_task(name='new', status=TaskStatus.COMPLETED)
    db.commit()
    monkeypatch.setattr(settings, 'KEEP_TASKS', 1 if policy == 'count' else 50)
    monkeypatch.setattr(settings, 'KEEP_DAYS', 1 if policy == 'age' else 0)
    if policy == 'budget':
        monkeypatch.setattr(settings, 'DISK_BUDGET_MB', 1)
        monkeypatch.setattr(retention, 'total_disk_usage', lambda: {'total_mb': 2})
    tasks._running[active.id] = analysis_control.Control()
    if policy == 'manual':
        assert client.delete('/api/v1/tasks/storage/all').status_code == 200
    else:
        retention.auto_purge(db)
    assert active_source.exists()
    assert not old_source.exists()
    db.expire_all()
    assert not db.get(type(active), active.id).configuration.get('media_purged')
    assert db.get(type(survivor), survivor.id) is not None


def test_resume_directories_count_toward_upload_usage(tmp_path, monkeypatch):
    uploads = tmp_path / 'uploads'
    resume = uploads / ('.resume-' + 'a' * 64)
    resume.mkdir(parents=True)
    (uploads / 'capture.pcap').write_bytes(bytes(1024**2))
    (resume / 'manifest').write_bytes(b'{}')
    (resume / '0').write_bytes(bytes(2 * 1024**2))
    monkeypatch.setattr(settings, 'UPLOAD_DIR', uploads)
    monkeypatch.setattr(settings, 'REBUILD_DIR', tmp_path / 'rebuilt')

    usage = retention.total_disk_usage()
    assert usage['uploads_mb'] == 3.0


@pytest.mark.parametrize('failure,status', [
    (asyncio.CancelledError(), None), (OSError(errno.ENOSPC, 'disk full'), 500),
])
def test_upload_failure_removes_partial_file(db, tmp_path, monkeypatch, failure, status):
    from fastapi import HTTPException
    from sqlalchemy import func, select

    from app.models.entities import AnalysisTask

    class Upload:
        filename = 'truncated.pcap'
        reads = 0

        async def read(self, _):
            self.reads += 1
            if self.reads == 1:
                return b'\xd4\xc3\xb2\xa1' + b'\0' * 20
            raise failure

    monkeypatch.setattr(settings, 'UPLOAD_DIR', tmp_path)
    with pytest.raises(HTTPException if status else asyncio.CancelledError) as caught:
        asyncio.run(tasks.upload_file(Upload(), db))
    if status:
        assert caught.value.status_code == status
    assert list(tmp_path.iterdir()) == []
    assert db.scalar(select(func.count()).select_from(AnalysisTask)) == 0
