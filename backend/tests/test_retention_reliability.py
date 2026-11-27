"""Retention reliability: quarantine, startup reconciliation, KEEP_UPLOADS, orphan resumes."""
import os
import time

from app.core.config import settings
from app.models.entities import TaskStatus
from app.services import retention


def test_purge_commits_db_before_deleting_quarantine(db, make_task, monkeypatch, tmp_path):
    uploads = tmp_path / 'uploads'
    uploads.mkdir()
    source = uploads / 'capture.pcap'
    source.write_bytes(b'capture-data')
    task = make_task(path=str(source), status=TaskStatus.COMPLETED)
    monkeypatch.setattr(settings, 'UPLOAD_DIR', uploads)
    monkeypatch.setattr(settings, 'REBUILD_DIR', tmp_path / 'rebuilt')
    monkeypatch.setattr(settings, 'DATA_DIR', tmp_path / 'data')

    qdir = retention.quarantine_dir(task.id)
    original_rmtree = retention.shutil.rmtree
    seen = {}

    def spy_rmtree(path, *args, **kwargs):
        if str(path) == str(qdir):
            seen['db_state'] = db.get(type(task), task.id).configuration
            seen['qdir_existed'] = os.path.isdir(path)
        return original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(retention.shutil, 'rmtree', spy_rmtree)
    result = retention.purge_task_media(db, task.id)
    assert result['removed'] > 0
    assert seen['db_state']['media_purged'] is True
    assert seen['qdir_existed'] is True
    assert not source.exists()
    assert not qdir.exists()


def test_failed_commit_restores_quarantined_files(db, make_task, monkeypatch, tmp_path):
    uploads = tmp_path / 'uploads'
    uploads.mkdir()
    source = uploads / 'capture.pcap'
    source.write_bytes(b'capture-data')
    task = make_task(path=str(source), status=TaskStatus.COMPLETED)
    monkeypatch.setattr(settings, 'DATA_DIR', tmp_path / 'data')
    monkeypatch.setattr(settings, 'REBUILD_DIR', tmp_path / 'rebuilt')

    def fail_commit():
        raise RuntimeError('db commit failed')

    monkeypatch.setattr(db, 'commit', fail_commit)
    try:
        retention.purge_task_media(db, task.id)
    except RuntimeError:
        pass
    else:
        raise AssertionError('commit failure should propagate')
    db.rollback()
    assert source.exists()
    assert source.read_bytes() == b'capture-data'


def test_reconcile_quarantine_deletes_purged_and_restores_pending(db, make_task,
                                                                  monkeypatch, tmp_path):
    uploads = tmp_path / 'uploads'
    uploads.mkdir()
    source = uploads / 'capture.pcap'
    source.write_bytes(b'capture-data')
    task = make_task(path=str(source), status=TaskStatus.COMPLETED)
    monkeypatch.setattr(settings, 'DATA_DIR', tmp_path / 'data')
    monkeypatch.setattr(settings, 'REBUILD_DIR', tmp_path / 'rebuilt')

    # Simulate a crash after the move but before the DB commit.
    qdir = retention.quarantine_dir(task.id)
    qdir.mkdir(parents=True)
    quarantined = qdir / 'moved.pcap'
    quarantined.write_bytes(source.read_bytes())
    source.unlink()
    retention._write_manifest(qdir, task.id, {
        'files': [{'id': 1, 'path': str(source), 'quarantined_as': quarantined.name}],
        'rebuild': False,
    }, drop_task=False, upload_only=False)

    result = retention.reconcile_quarantine(db)
    assert result['restored'] == 1
    assert source.read_bytes() == b'capture-data'
    assert not qdir.exists()

    # Already-purged task: quarantine content is simply discarded.
    task.configuration = {'media_purged': True, 'index_purged': True}
    db.commit()
    qdir.mkdir(parents=True)
    (qdir / 'leftover.pcap').write_bytes(b'old')
    result = retention.reconcile_quarantine(db)
    assert result['deleted'] == 1
    assert not qdir.exists()


def test_keep_uploads_false_purges_only_source(db, make_task, monkeypatch, tmp_path):
    uploads = tmp_path / 'uploads'
    uploads.mkdir()
    source = uploads / 'capture.pcap'
    source.write_bytes(b'capture-data')
    task = make_task(path=str(source), status=TaskStatus.COMPLETED)
    rebuild = tmp_path / 'rebuilt' / str(task.id)
    rebuild.mkdir(parents=True)
    video = rebuild / 'video.mp4'
    video.write_bytes(b'video')

    monkeypatch.setattr(settings, 'DATA_DIR', tmp_path / 'data')
    monkeypatch.setattr(settings, 'UPLOAD_DIR', uploads)
    monkeypatch.setattr(settings, 'REBUILD_DIR', tmp_path / 'rebuilt')
    monkeypatch.setattr(settings, 'KEEP_TASKS', 50)
    monkeypatch.setattr(settings, 'KEEP_DAYS', 0)
    monkeypatch.setattr(settings, 'KEEP_UPLOADS', False)

    result = retention.auto_purge(db)
    assert any(a.get('upload_purged') for a in result['actions'])
    assert not source.exists()
    assert video.exists()
    db.expire_all()
    cfg = db.get(type(task), task.id).configuration
    assert cfg['upload_purged'] is True
    assert 'media_purged' not in cfg
    # Subsequent purge runs are no-ops for this task.
    assert not any(a['task_id'] == task.id for a in retention.auto_purge(db)['actions'])


def test_cleanup_orphan_resumes_removes_only_stale_dirs(monkeypatch, tmp_path):
    uploads = tmp_path / 'uploads'
    uploads.mkdir()
    stale = uploads / ('.resume-' + 'a' * 64)
    fresh = uploads / ('.resume-' + 'b' * 64)
    stale.mkdir()
    fresh.mkdir()
    (stale / '0').write_bytes(b'old-part')
    (fresh / '0').write_bytes(b'new-part')

    old = time.time() - 48 * 3600
    os.utime(stale, (old, old))
    monkeypatch.setattr(settings, 'UPLOAD_DIR', uploads)

    result = retention.cleanup_orphan_resumes(max_age_hours=24)
    assert result['count'] == 1
    assert not stale.exists()
    assert fresh.exists()
