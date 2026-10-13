"""Create a NEW migrated test copy. Never apply DDL to an existing file.

Usage: python -m scripts.prepare_recall_test_database --source-db COPY.db --output-db NEW.db
Default is a memory dry-run. --create-test-copy must be explicitly supplied to
persist a new test database; --apply is not supported.
"""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from sqlalchemy import create_engine

from app.services.recall_database import is_protected_engine
from scripts.migrate_stage3b_recall import open_readonly, run_migration_on_connection, snapshot_state


def prepare(source, output=None):
    source = Path(source).resolve()
    if output is not None:
        output = Path(output).resolve()
        engine = create_engine("sqlite:///" + output.as_posix())
        try:
            if is_protected_engine(engine) or output.exists():
                raise ValueError("Output must be a new test file, never an existing database or ttcs.db")
        finally:
            engine.dispose()
    with closing(open_readonly(source)) as original, closing(sqlite3.connect(":memory:")) as memory:
        before = snapshot_state(original)
        original.backup(memory)
        preserved = snapshot_state(memory)
        memory.execute("PRAGMA foreign_keys=ON")
        try:
            run_migration_on_connection(memory)
            memory.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_recall_event_evidence
                ON batch_events(event_type, batch_id, json_extract(payload, '$.recall_id'),
                    coalesce(json_extract(payload, '$.organization_id'), -1))
                WHERE event_type IN ('RECALL_INIT','RECALL_AFFECTED','RECALL_ACKNOWLEDGED','RECALL_COMPLETED')
            """)
            after = snapshot_state(memory)
            assert all(after[t] == v for t, v in preserved.items() if t != "schema_sha256")
            assert memory.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            memory.commit()
        except Exception:
            memory.rollback()
            raise
        if before != snapshot_state(original):
            raise RuntimeError("Source changed during snapshot; retry while source is idle")
        if output is not None:
            # Exclusive creation prevents overwriting a concurrently created file.
            with output.open("xb"):
                pass
            with closing(sqlite3.connect(output)) as disk:
                memory.backup(disk)
        return {"mode": "new_test_copy" if output else "memory_dry_run", "source_unchanged": True,
                "existing_tables_preserved": True, "output": str(output) if output else None,
                "foreign_key_violations_preserved": len(memory.execute("PRAGMA foreign_key_check").fetchall())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--output-db", type=Path)
    parser.add_argument("--create-test-copy", action="store_true")
    args = parser.parse_args()
    if bool(args.output_db) != args.create_test_copy:
        parser.error("Specify both --output-db and --create-test-copy to create a new test copy")
    print(json.dumps(prepare(args.source_db, args.output_db), indent=2))


if __name__ == "__main__":
    main()
