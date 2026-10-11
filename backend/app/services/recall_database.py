"""Database boundary for the experimental Recall backend (SQLite only)."""
from pathlib import Path
from urllib.parse import unquote

from fastapi import HTTPException
from sqlalchemy import inspect, text, update

from app.database import DATABASE_FILE

RECALL_TABLES = {"recalls", "recall_acknowledgments", "idempotency_records"}


def is_protected_engine(engine) -> bool:
    if engine.dialect.name != "sqlite":
        return False
    name = engine.url.database
    if not name or name == ":memory:":
        return False
    name = unquote(name.removeprefix("file:").split("?")[0])
    path = Path(name).resolve()
    original = DATABASE_FILE.resolve()
    return path == original or (
        path.exists() and original.exists() and path.samefile(original)
    )


def recall_schema_available(db) -> bool:
    engine = db.get_bind()
    if is_protected_engine(engine) or engine.dialect.name != "sqlite":
        return False
    tables = set(inspect(db.connection()).get_table_names())
    found = tables & RECALL_TABLES
    if found and found != RECALL_TABLES:
        raise HTTPException(503, "Recall schema is incomplete; use a migrated test database")
    return found == RECALL_TABLES


def require_recall_database(db) -> None:
    if not recall_schema_available(db):
        raise HTTPException(503, "Recall is enabled only on a separate migrated SQLite test database")
    index_sql = db.scalar(text(
        "SELECT sql FROM sqlite_master WHERE type='index' AND name='uq_recall_event_evidence'"
    ))
    if not index_sql or not index_sql.upper().startswith("CREATE UNIQUE INDEX"):
        raise HTTPException(503, "Recall event uniqueness index is missing; prepare a Stage 3B.2A test copy")
    db.connection().exec_driver_sql("PRAGMA foreign_keys=ON")
    if db.connection().exec_driver_sql("PRAGMA foreign_keys").scalar() != 1:
        raise HTTPException(503, "Recall requires foreign key enforcement")


def acquire_write_lock(db) -> None:
    """Serialize Recall and physical mutations before reading their decision state.

    Matches the existing SQLite split/merge/handover write reservation. The
    no-op UPDATE obtains SQLite's database writer lock without changing status.
    This lock is held until the caller's single commit/rollback.
    """
    from app.models import Batch

    db.execute(update(Batch).values(status=Batch.status))
    db.expire_all()


def begin_read_snapshot(db) -> None:
    """pysqlite legacy SELECTs do not begin a DB transaction automatically."""
    connection = db.connection()
    if not connection.connection.driver_connection.in_transaction:
        connection.exec_driver_sql("BEGIN")


def prepare_physical_write(db) -> None:
    if recall_schema_available(db):
        acquire_write_lock(db)
