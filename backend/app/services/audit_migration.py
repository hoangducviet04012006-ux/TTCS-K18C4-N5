"""Explicit additive migration for audit metadata on QA only; never backfill."""

from pathlib import Path
from sqlalchemy import inspect
from app.services.audit_metadata import COLUMNS
from app.services.recall_database import is_protected_engine


def apply_audit_schema(engine):
    repo = Path(__file__).resolve().parents[3]
    official = repo / ".sprint123-trial/demo_sprint123_north.db"
    name = engine.url.database
    path = Path(name).resolve() if name and name != ":memory:" else None
    if is_protected_engine(engine) or (
        path and (path == official.resolve() or (path.exists() and official.exists() and path.samefile(official)))
    ):
        raise RuntimeError("Audit migration on official database is forbidden")
    with engine.connect() as conn:
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            found = {c["name"] for c in inspect(conn).get_columns("audit_logs")}
            for name, sql_type in COLUMNS.items():
                if name not in found:
                    conn.exec_driver_sql("ALTER TABLE audit_logs ADD COLUMN " + name + " " + sql_type)
            conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_audit_scope_id ON audit_logs(organization_id,id)")
            conn.commit()
            engine._audit_d_ready = True
        except Exception:
            conn.rollback()
            raise
