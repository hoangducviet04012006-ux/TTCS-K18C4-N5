"""Real file upgrades, preservation, repeatability and startup refusal."""
import sqlite3
import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.schema import CreateTable

from app.database import Base
from app.services.sprint4_schema import TABLES, ensure_sprint4_schema, schema_status


def legacy_copy(tmp_path):
    path = tmp_path / "legacy-copy.db"
    engine = create_engine("sqlite:///" + path.as_posix())
    Base.metadata.create_all(engine)
    with engine.begin() as c:
        for name in reversed(TABLES):
            c.exec_driver_sql(f'DROP TABLE "{name}"')
        c.exec_driver_sql("ALTER TABLE batches DROP COLUMN has_temperature_violation")
        c.exec_driver_sql("ALTER TABLE batches DROP COLUMN temperature_violation_count")
        c.exec_driver_sql("CREATE TABLE preserve (id INTEGER PRIMARY KEY, payload TEXT)")
        c.exec_driver_sql("INSERT INTO preserve VALUES (1, 'old sprint data')")
        c.exec_driver_sql("CREATE TABLE sprint_demo_marker (name TEXT PRIMARY KEY, value TEXT)")
        c.exec_driver_sql("INSERT INTO sprint_demo_marker VALUES ('scope', 'sprint123')")
    return engine, path


def test_upgrade_preserves_baseline_and_is_repeatable(tmp_path):
    engine, path = legacy_copy(tmp_path)
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match="schema"):
        ensure_sprint4_schema(engine)
    assert path.read_bytes() == before
    result = ensure_sprint4_schema(engine, upgrade=True)
    assert result["ready"] and list(tmp_path.glob('*.backup.db'))
    with engine.connect() as c:
        assert c.scalar(text("SELECT payload FROM preserve")) == 'old sprint data'
        assert c.scalar(text("SELECT value FROM sprint_demo_marker")) == 'sprint123'
        assert c.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
    before_repeat = path.read_bytes()
    assert ensure_sprint4_schema(engine, upgrade=True)["ready"]
    assert path.read_bytes() == before_repeat
    assert len(list(tmp_path.glob('*.backup.db'))) == 1
    engine.dispose()


def test_failed_upgrade_rolls_back_all_ddl(tmp_path):
    engine, path = legacy_copy(tmp_path)
    # A partial incompatible table must never be silently accepted.
    with engine.begin() as c:
        c.exec_driver_sql("CREATE TABLE temperature_logs (id TEXT PRIMARY KEY)")
    before = sqlite3.connect(path).execute("SELECT type,name,sql FROM sqlite_master ORDER BY name").fetchall()
    with pytest.raises(RuntimeError, match="partial schema"):
        ensure_sprint4_schema(engine, upgrade=True)
    after = sqlite3.connect(path).execute("SELECT type,name,sql FROM sqlite_master ORDER BY name").fetchall()
    assert before == after
    assert not schema_status(engine)["ready"]
    engine.dispose()


@pytest.mark.parametrize('alias', [False, True])
def test_protected_main_and_hardlink_cannot_be_upgraded(tmp_path, monkeypatch, alias):
    import app.services.sprint4_schema as schema
    engine, path = legacy_copy(tmp_path)
    engine.dispose()
    root = tmp_path / 'project'
    (root / 'data').mkdir(parents=True)
    protected = root / 'data/agritrace.db'
    protected.write_bytes(path.read_bytes())
    monkeypatch.setattr(schema, '__file__', str(root / 'backend/app/services/sprint4_schema.py'))
    target = protected
    if alias:
        target = tmp_path / 'alias.db'
        try:
            os.link(protected, target)
        except OSError:
            pytest.skip('Hardlinks unsupported on test filesystem')
    before = protected.read_bytes()
    test_engine = create_engine('sqlite:///' + target.as_posix())
    with pytest.raises(RuntimeError, match='protected'):
        ensure_sprint4_schema(test_engine, upgrade=True)
    assert protected.read_bytes() == before
    test_engine.dispose()


def test_wrong_unique_predicate_fails_without_schema_change(tmp_path):
    engine, path = legacy_copy(tmp_path)
    ensure_sprint4_schema(engine, upgrade=True)
    with engine.begin() as connection:
        connection.exec_driver_sql('DROP INDEX uq_cold_trips_active_container')
        connection.exec_driver_sql('CREATE INDEX uq_cold_trips_active_container ON cold_trips(container_code)')
    before = sqlite3.connect(path).execute('SELECT name,sql FROM sqlite_master ORDER BY name').fetchall()
    with pytest.raises(RuntimeError, match='Incompatible index'):
        ensure_sprint4_schema(engine, upgrade=True)
    assert sqlite3.connect(path).execute('SELECT name,sql FROM sqlite_master ORDER BY name').fetchall() == before
    engine.dispose()


def test_previous_sprint4_schema_upgrades_additively(tmp_path):
    engine, path = legacy_copy(tmp_path)
    ensure_sprint4_schema(engine, upgrade=True)
    table = Base.metadata.tables['temperature_violations']
    ddl = str(CreateTable(table).compile(dialect=engine.dialect))
    ddl = '\n'.join(line.rstrip() for line in ddl.splitlines() if 'source_trip_id' not in line)
    ddl = ddl.replace(',\n)', '\n)')
    with engine.begin() as c:
        c.exec_driver_sql('DROP TABLE product_temperature_settings')
        c.exec_driver_sql('DROP TABLE temperature_violations')
        c.exec_driver_sql(ddl)
    assert ensure_sprint4_schema(engine, upgrade=True)['ready']
    with engine.connect() as c:
        assert c.scalar(text('SELECT payload FROM preserve')) == 'old sprint data'
    engine.dispose()


def test_missing_database_is_not_created(tmp_path):
    target = tmp_path / 'does-not-exist.db'
    engine = create_engine('sqlite:///' + target.as_posix())
    with pytest.raises(RuntimeError, match='must already exist'):
        ensure_sprint4_schema(engine, upgrade=True)
    assert not target.exists()
    engine.dispose()


def test_lifespan_validates_the_isolated_request_database(client):
    with client:
        response = client.get('/ready')
        assert response.status_code == 200 and response.json()['ready']
