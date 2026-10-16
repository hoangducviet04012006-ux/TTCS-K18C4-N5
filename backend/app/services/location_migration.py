"""Explicit QA-only migration. No startup migration and no data backfill."""

from pathlib import Path
from sqlalchemy import inspect
from app import models  # noqa: F401 - register referenced tables for standalone CLI
from app.location_models import Location
from app.services.recall_database import is_protected_engine


def apply_phase_c_schema(engine):
    repo = Path(__file__).resolve().parents[3]
    official = repo / ".sprint123-trial/demo_sprint123_north.db"
    path = Path(engine.url.database).resolve() if engine.url.database and engine.url.database != ":memory:" else None
    if is_protected_engine(engine) or (
        path and (path == official.resolve() or (path.exists() and official.exists() and path.samefile(official)))
    ):
        raise RuntimeError("Migration on official databases is forbidden")
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            Location.__table__.create(conn, checkfirst=True)
            if not any(c["name"] == "location_id" for c in inspect(conn).get_columns("batches")):
                conn.exec_driver_sql(
                    "ALTER TABLE batches ADD COLUMN location_id INTEGER REFERENCES locations(id) ON DELETE RESTRICT"
                )
            conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_batches_location_id ON batches(location_id)")
            if conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError("Foreign key violations; rollback")
            conn.commit()
            engine._phase_c_ready = True
        except Exception:
            conn.rollback()
            raise
