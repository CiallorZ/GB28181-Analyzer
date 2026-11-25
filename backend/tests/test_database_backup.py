import sqlite3

from app.core.db import backup_sqlite


def test_backup_sqlite_only_when_version_changes(tmp_path):
    source = tmp_path / 'analyzer.db'
    with sqlite3.connect(source) as db:
        db.execute('create table evidence(value text)')
        db.execute("insert into evidence values ('kept')")
        db.commit()

    backups = tmp_path / 'backups'
    marker = tmp_path / 'db-version.txt'
    first = backup_sqlite(source, backups, marker, '1.2.0')
    assert first is not None and first.is_file()
    with sqlite3.connect(first) as db:
        assert db.execute('select value from evidence').fetchone() == ('kept',)

    assert backup_sqlite(source, backups, marker, '1.2.0') is None
    second = backup_sqlite(source, backups, marker, '1.2.1')
    assert second is not None and second != first

    marker.write_text('2.0.0', encoding='utf-8')
    assert backup_sqlite(source, backups, marker, '2.0.0') is None
