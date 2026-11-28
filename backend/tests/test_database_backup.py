import sqlite3

from sqlalchemy import select

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


def test_ensure_columns_adds_missing_optional_column(tmp_path):
    from sqlalchemy import create_engine, inspect, text
    from app.core import db as db_module

    old_engine = db_module.engine
    database = tmp_path / 'upgrade.db'
    test_engine = create_engine('sqlite:///' + database.as_posix())
    try:
        with test_engine.begin() as connection:
            connection.execute(text(
                'create table media_stream (id integer primary key, task_id integer)'
            ))
        db_module.engine = test_engine
        changed = db_module.ensure_columns()
        assert 'media_stream.avg_bitrate' in changed
        columns = {c['name'] for c in inspect(test_engine).get_columns('media_stream')}
        assert 'avg_bitrate' in columns
        assert 'packet_count' in columns
    finally:
        db_module.engine = old_engine
        test_engine.dispose()


def test_ensure_columns_round_trips_boolean_and_numeric_defaults(tmp_path):
    from sqlalchemy import create_engine, text
    from app.core import db as db_module
    from app.models.entities import MediaStream

    old_engine = db_module.engine
    database = tmp_path / 'upgrade-defaults.db'
    test_engine = create_engine('sqlite:///' + database.as_posix())
    try:
        with test_engine.begin() as connection:
            connection.execute(text(
                'create table media_stream ('
                'id integer primary key, task_id integer, start_time float, end_time float)'
            ))
            connection.execute(text(
                'insert into media_stream(task_id, start_time, end_time) values (1, 0, 1)'
            ))
        db_module.engine = test_engine
        db_module.ensure_columns()

        with test_engine.connect() as connection:
            raw = connection.execute(text(
                'select has_video, typeof(has_video), has_audio, typeof(has_audio), '
                'packet_count, typeof(packet_count) from media_stream'
            )).one()
            orm = connection.execute(select(
                MediaStream.has_video, MediaStream.has_audio, MediaStream.packet_count
            )).one()
        assert raw == (0, 'integer', 0, 'integer', 0, 'integer')
        assert orm == (False, False, 0)
    finally:
        db_module.engine = old_engine
        test_engine.dispose()
