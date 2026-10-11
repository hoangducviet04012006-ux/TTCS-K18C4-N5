"""Recall 3B.1B design trial. Reads a source snapshot; writes only SQLite memory.

No real migration is exposed. --apply remains refused. For an explicitly
authorized NEW test copy, use scripts.prepare_recall_test_database.
"""
from __future__ import annotations
import argparse
from contextlib import closing
import hashlib
import json
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ORIGINAL_DB_PATH = BASE_DIR / "ttcs.db"


def snapshot_state(conn: sqlite3.Connection) -> dict:
    """Logical fingerprints of every existing row and schema object (no raw data output)."""
    state = {}
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        quoted = '"' + name.replace('"', '""') + '"'
        rows = conn.execute(f"SELECT * FROM {quoted} ORDER BY rowid").fetchall()
        state[name] = {"count": len(rows), "sha256": hashlib.sha256(repr(rows).encode()).hexdigest()}
    schema = conn.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()
    state["schema_sha256"] = hashlib.sha256(repr(schema).encode()).hexdigest()
    return state


def open_readonly(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
    conn.execute("PRAGMA query_only=ON")
    return conn


def run_migration_on_connection(conn: sqlite3.Connection) -> None:
    """Thực thi câu lệnh DDL tạo bảng và index trong transaction."""
    # Design trial only: even an explicit caller cannot migrate a file database.
    if any(row[2] for row in conn.execute("PRAGMA database_list")):
        raise ValueError("Stage 3B.1B only permits an in-memory trial")
    if conn.in_transaction or not conn.execute("PRAGMA foreign_keys").fetchone()[0]:
        raise ValueError("Enable foreign_keys before starting the trial")
    required = {"batches", "users", "organizations", "batch_events"}
    present = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not required <= present:
        raise ValueError("Missing base schema")
    cur = conn.cursor()
    cur.execute("BEGIN")

    # 1. Bảng recalls
    cur.execute("""
    CREATE TABLE IF NOT EXISTS recalls (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        recall_code VARCHAR(50) NOT NULL UNIQUE,
        root_batch_id INTEGER NOT NULL,
        reason TEXT NOT NULL,
        created_by_user_id INTEGER NOT NULL,
        created_by_org_id INTEGER NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','COMPLETED')),
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        completed_at DATETIME NULL,
        CHECK ((status='OPEN' AND completed_at IS NULL) OR (status='COMPLETED' AND completed_at IS NOT NULL)),
        CONSTRAINT fk_recall_root_batch FOREIGN KEY (root_batch_id) REFERENCES batches(id) ON DELETE RESTRICT,
        CONSTRAINT fk_recall_user FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE RESTRICT,
        CONSTRAINT fk_recall_org FOREIGN KEY (created_by_org_id) REFERENCES organizations(id) ON DELETE RESTRICT,
        CONSTRAINT check_recall_reason_len CHECK (LENGTH(TRIM(reason)) >= 20)
    );
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS ix_recalls_recall_code ON recalls(recall_code);")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_recalls_root_batch_id ON recalls(root_batch_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_recalls_status ON recalls(status);")

    # Partial Unique Index: Mỗi lô gốc chỉ được có tối đa 1 lệnh thu hồi ở trạng thái 'OPEN'
    cur.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS uq_recall_open_per_root_batch 
    ON recalls(root_batch_id) 
    WHERE status = 'OPEN';
    """)

    # Design prohibits reopening even after completion.
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_recall_root_lifetime ON recalls(root_batch_id)")

    # 2. Bảng recall_acknowledgments
    cur.execute("""
    CREATE TABLE IF NOT EXISTS recall_acknowledgments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        recall_id INTEGER NOT NULL,
        organization_id INTEGER NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','ACKNOWLEDGED')),
        acknowledged_by_user_id INTEGER NULL,
        acknowledged_at DATETIME NULL,
        notes TEXT NULL,
        CHECK ((status='PENDING' AND acknowledged_by_user_id IS NULL AND acknowledged_at IS NULL) OR (status='ACKNOWLEDGED' AND acknowledged_by_user_id IS NOT NULL AND acknowledged_at IS NOT NULL)),
        CONSTRAINT fk_ack_recall FOREIGN KEY (recall_id) REFERENCES recalls(id) ON DELETE RESTRICT,
        CONSTRAINT fk_ack_org FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE RESTRICT,
        CONSTRAINT fk_ack_user FOREIGN KEY (acknowledged_by_user_id) REFERENCES users(id) ON DELETE RESTRICT,
        CONSTRAINT uq_recall_org_ack UNIQUE (recall_id, organization_id)
    );
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS ix_ack_recall_id ON recall_acknowledgments(recall_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_ack_org_id ON recall_acknowledgments(organization_id);")

    # 3. Bảng idempotency_records
    cur.execute("""
    CREATE TABLE IF NOT EXISTS idempotency_records (
        key VARCHAR(128) NOT NULL CHECK (length(key) BETWEEN 1 AND 128),
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        endpoint VARCHAR(100) NOT NULL,
        request_hash VARCHAR(64) NOT NULL,
        response_code INTEGER NOT NULL,
        response_body TEXT NOT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (user_id, endpoint, key)
    );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS ix_idempotency_created_at ON idempotency_records(created_at);")



def trial(source: Path) -> dict:
    """SQLite backup captures committed WAL contents without copying an active file."""
    with closing(open_readonly(source)) as original:
        before = snapshot_state(original)
        memory = sqlite3.connect(":memory:")
        try:
            original.backup(memory)
            preserved = snapshot_state(memory)
            memory.execute("PRAGMA foreign_keys=ON")
            try:
                run_migration_on_connection(memory)
                if memory.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("Integrity check failed")
                after = snapshot_state(memory)
                # Existing orphan references are reported, never repaired.
                for table, fingerprint in preserved.items():
                    if table != "schema_sha256" and fingerprint != after[table]:
                        raise RuntimeError(f"Existing table changed: {table}")
                memory.commit()
            except Exception:
                memory.rollback()
                raise
            return {"source_unchanged": before == snapshot_state(original),
                    "existing_tables_preserved": True,
                    "trial_counts": {t: after[t]["count"] for t in ("recalls", "recall_acknowledgments", "idempotency_records")},
                    "existing_foreign_key_violations": len(memory.execute("PRAGMA foreign_key_check").fetchall()),
                    "integrity": "ok", "mode": "memory_only"}
        finally:
            memory.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Memory-only trial (default)")
    parser.add_argument("--apply", action="store_true", help="Refused in Stage 3B.1B")
    parser.add_argument("--source-db", type=Path, default=ORIGINAL_DB_PATH)
    parser.add_argument("--target-db", type=Path, help="Legacy option; refused to prevent writes")
    args = parser.parse_args()
    if args.apply or args.target_db:
        parser.error("Real/file migration is disabled in Stage 3B.1B; use --source-db for a read-only trial")
    result = trial(args.source_db)
    print(json.dumps(result, indent=2))
    return 0 if result["source_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
