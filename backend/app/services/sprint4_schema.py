"""Explicit, additive Sprint 4 upgrades. Never bootstrap or seed legacy data."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from sqlalchemy import inspect
from sqlalchemy.schema import CreateIndex, CreateTable, UniqueConstraint, CheckConstraint

VERSION = "s4_002_product_temperature"
TABLES = ("cold_trips", "cold_trip_batches", "temperature_logs",
          "temperature_violations", "product_temperature_settings")
COLUMNS = {
    "has_temperature_violation": "BOOLEAN NOT NULL DEFAULT 0",
    "temperature_violation_count": "INTEGER NOT NULL DEFAULT 0",
}


def schema_status(engine):
    from app.database import Base
    from app import trip_models  # noqa: F401
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    missing = []
    for name in TABLES:
        if name not in tables:
            missing.append(f"table:{name}")
            continue
        model = Base.metadata.tables[name]
        with engine.connect() as connection:
            missing.extend(_contract_issues(connection.connection.driver_connection, model))
        actual = {c["name"]: c for c in inspector.get_columns(name)}
        for col in model.columns:
            if col.name not in actual:
                missing.append(f"column:{name}.{col.name}")
            elif str(actual[col.name]["type"]).upper() != str(col.type).upper():
                missing.append(f"type:{name}.{col.name}")
        indexes = {i["name"]: i for i in inspector.get_indexes(name)}
        for idx in model.indexes:
            found = indexes.get(idx.name)
            predicate = idx.dialect_options["sqlite"].get("where")
            expected_where = str(predicate) if predicate is not None else ""
            actual_where = str((found or {}).get("dialect_options", {}).get("sqlite_where", ""))
            if (not found or bool(found["unique"]) != idx.unique
                    or found["column_names"] != [c.name for c in idx.columns]
                    or actual_where.strip() != expected_where.strip()):
                missing.append(f"index:{idx.name}")
    actual_batch = {c["name"]: c for c in inspector.get_columns("batches")} if "batches" in tables else {}
    for name in COLUMNS:
        col = actual_batch.get(name)
        if (col is None or col["nullable"] or str(col["default"]).strip("'()") != '0'
                or str(col["type"]).upper() != COLUMNS[name].split()[0]):
            missing.append(f"column:batches.{name}")
    return {"ready": not missing, "target_version": VERSION, "missing": missing}


def _fingerprint(connection, table, columns):
    quoted = ','.join('"' + c.replace('"', '""') + '"' for c in columns)
    rows = connection.execute(f'SELECT {quoted} FROM "{table}"').fetchall()
    encoded = sorted(json.dumps(tuple(r), default=str, ensure_ascii=False) for r in rows)
    return hashlib.sha256('\n'.join(encoded).encode()).hexdigest()


def ensure_sprint4_schema(engine, *, upgrade=False):
    """Verify by default; explicit upgrades refuse both canonical databases/aliases."""
    if (engine.dialect.name == "sqlite" and engine.url.database not in (None, ":memory:")
            and not Path(engine.url.database).is_file()):
        raise RuntimeError("Database copy must already exist; startup never seeds")
    status = schema_status(engine)
    if status["ready"]:
        return status
    if not upgrade:
        raise RuntimeError("Sprint 4 schema chưa sẵn sàng: " + ', '.join(status["missing"])
                           + ". Dùng --upgrade-schema với bản sao SQLite độc lập đã được duyệt.")
    if engine.dialect.name != "sqlite" or not engine.url.database:
        raise RuntimeError("Sprint 4 upgrade requires an explicit SQLite file")
    target = Path(engine.url.database).resolve()
    root = Path(__file__).resolve().parents[3]
    for forbidden in (root / "data/agritrace.db", root / "backend/ttcs.db"):
        if target == forbidden.resolve() or (target.exists() and forbidden.exists() and target.samefile(forbidden)):
            raise RuntimeError("Refusing upgrade of protected main database")
    raw = engine.raw_connection()
    conn = raw.driver_connection
    backup = None
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or conn.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("Database integrity/foreign keys preflight failed")
        original_tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        columns = {t: [r[1] for r in conn.execute(f'PRAGMA table_info("{t}")')] for t in original_tables}
        _check_existing_batch_columns(conn)
        before = {t: _fingerprint(conn, t, columns[t]) for t in original_tables}
        old_objects = conn.execute("SELECT type,name,sql FROM sqlite_master WHERE type IN ('trigger','index')").fetchall()
        if ("temperature_violations" in original_tables
                and conn.execute("SELECT 1 FROM temperature_violations LIMIT 1").fetchone()):
            if any(c not in columns.get("batches", []) for c in COLUMNS):
                raise RuntimeError("Existing violations require a reviewed counter backfill")
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup = target.with_name(target.name + '.' + stamp + '.backup.db')
        with sqlite3.connect(target.as_uri() + '?mode=ro', uri=True) as source:
            with sqlite3.connect(backup) as dest:
                source.backup(dest)
        _upgrade_tables(conn, engine, original_tables)
        for name, ddl in COLUMNS.items():
            if name not in columns.get("batches", []):
                conn.execute(f'ALTER TABLE batches ADD COLUMN {name} {ddl}')
        _verify_preserved(conn, original_tables, columns, before, old_objects)
        conn.execute("CREATE TABLE IF NOT EXISTS sprint4_schema_versions (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
        conn.execute("INSERT OR IGNORE INTO sprint4_schema_versions VALUES (?, ?)", (VERSION, stamp))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        raw.close()
    result = schema_status(engine)
    if not result["ready"]:
        raise RuntimeError("Schema validation failed after upgrade: " + str(result["missing"]))
    result["backup"] = str(backup)
    return result


def _upgrade_tables(conn, engine, original_tables):
    from app.database import Base
    for name in TABLES:
        table = Base.metadata.tables[name]
        if name not in original_tables:
            conn.execute(str(CreateTable(table).compile(dialect=engine.dialect)))
        else:
            actual = {r[1]: r[2].upper() for r in conn.execute(f'PRAGMA table_info("{name}")')}
            if name == "temperature_violations" and "source_trip_id" not in actual:
                conn.execute("ALTER TABLE temperature_violations ADD COLUMN "
                             "source_trip_id INTEGER REFERENCES cold_trips(id)")
                actual["source_trip_id"] = "INTEGER"
            if any(c.name not in actual or actual[c.name] != str(c.type).upper() for c in table.columns):
                raise RuntimeError(f"Incompatible partial schema: {name}; manual review required")
        existing = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        for index in sorted(table.indexes, key=lambda i: i.name):
            if index.name not in existing:
                conn.execute(str(CreateIndex(index).compile(dialect=engine.dialect)))
            else:
                actual_sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='index' AND name=?",
                                          (index.name,)).fetchone()[0]
                expected_sql = str(CreateIndex(index).compile(dialect=engine.dialect))
                if _normal_sql(actual_sql) != _normal_sql(expected_sql):
                    raise RuntimeError(f"Incompatible index: {index.name}")
        issues = _contract_issues(conn, table)
        if issues:
            raise RuntimeError("Incompatible table constraints: " + ', '.join(issues))


def _contract_issues(conn, table):
    issues = []
    columns = {r[1]: r for r in conn.execute(f'PRAGMA table_info("{table.name}")')}
    for column in table.columns:
        row = columns.get(column.name)
        if row is not None and bool(row[3]) != (not column.nullable):
            issues.append(f"nullability:{table.name}.{column.name}")
    expected_pk = [c.name for c in table.primary_key.columns]
    actual_pk = [r[1] for r in sorted(columns.values(), key=lambda r: r[5]) if r[5]]
    if actual_pk != expected_pk:
        issues.append(f"primary_key:{table.name}")
    actual_fk = {(r[3], r[2], r[4], r[6]) for r in conn.execute(f'PRAGMA foreign_key_list("{table.name}")')}
    for fk in table.foreign_keys:
        expected = (fk.parent.name, fk.column.table.name, fk.column.name, fk.ondelete or 'NO ACTION')
        if expected not in actual_fk:
            issues.append(f"foreign_key:{table.name}.{fk.parent.name}")
    issues.extend(_constraint_issues(conn, table))
    return issues


def _constraint_issues(conn, table):
    issues = []
    unique_sets = []
    for row in conn.execute(f'PRAGMA index_list("{table.name}")'):
        if row[2] and not row[4]:
            unique_sets.append([r[2] for r in conn.execute(f'PRAGMA index_info("{row[1]}")')])
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table.name,)).fetchone()[0]
    for constraint in table.constraints:
        if isinstance(constraint, UniqueConstraint) and [c.name for c in constraint.columns] not in unique_sets:
            issues.append(f"unique:{table.name}.{constraint.name}")
        if isinstance(constraint, CheckConstraint) and _normal_sql(str(constraint.sqltext)) not in _normal_sql(sql):
            issues.append(f"check:{table.name}.{constraint.name}")
    return issues


def _normal_sql(sql):
    return ''.join((sql or '').upper().replace('"', '').split())


def _check_existing_batch_columns(conn):
    for row in conn.execute('PRAGMA table_info(batches)'):
        if row[1] in COLUMNS and (row[2].upper() != COLUMNS[row[1]].split()[0]
                                  or not row[3] or str(row[4]).strip("'()") != '0'):
            raise RuntimeError(f"Incompatible existing batch column: {row[1]}")


def _verify_preserved(conn, original_tables, columns, before, old_objects):
    for table in original_tables:
        if _fingerprint(conn, table, columns[table]) != before[table]:
            raise RuntimeError(f"Data preservation check failed: {table}")
    for kind, name, sql in old_objects:
        if conn.execute("SELECT sql FROM sqlite_master WHERE type=? AND name=?", (kind, name)).fetchone() != (sql,):
            raise RuntimeError(f"Protected schema object changed: {name}")
    if conn.execute("PRAGMA foreign_key_check").fetchall():
        raise RuntimeError("Post-upgrade foreign key check failed")


def bootstrap_staging_database(engine):
    """Khởi tạo cấu trúc schema hoàn chỉnh cho môi trường CI/Staging độc lập.

    Tuyệt đối từ chối chạy trên cơ sở dữ liệu chính hoặc các file được bảo vệ.
    """
    if engine.dialect.name != "sqlite":
        raise RuntimeError("Staging bootstrap chỉ hỗ trợ SQLite")
    if not engine.url.database or engine.url.database == ":memory:":
        return {"ready": True, "target_version": VERSION, "missing": []}

    target = Path(engine.url.database).resolve()
    root = Path(__file__).resolve().parents[3]
    forbidden_targets = {
        (root / "data/agritrace.db").resolve(),
        (root / "backend/ttcs.db").resolve(),
    }
    for forbidden in forbidden_targets:
        if target == forbidden or (target.exists() and forbidden.exists() and target.samefile(forbidden)):
            raise RuntimeError("Từ chối bootstrap trên database chính được bảo vệ")

    from app.database import Base, create_event_immutability_triggers
    from app import models, trip_models  # noqa: F401 - đảm bảo nạp toàn bộ ORM models

    Base.metadata.create_all(bind=engine)
    create_event_immutability_triggers(engine)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    raw = engine.raw_connection()
    conn = raw.driver_connection
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS sprint4_schema_versions (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        conn.execute("INSERT OR IGNORE INTO sprint4_schema_versions VALUES (?, ?)", (VERSION, stamp))
        conn.commit()
    finally:
        raw.close()

    result = schema_status(engine)
    if not result["ready"]:
        raise RuntimeError(f"Staging bootstrap validation failed: {result['missing']}")
    return result
