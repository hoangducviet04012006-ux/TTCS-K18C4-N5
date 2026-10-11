"""Explicit synthetic Recall demo. Never imports the app before selecting its DB.

Run from backend: python -m scripts.run_recall_demo --db ../.recall-trial/demo_3b2b.db
No original DB backup, migration, reset, or implicit startup seed is performed.
"""
import argparse
import os
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[2]
TRIAL = ROOT / ".recall-trial"
PASSWORD = "RecallDemo!2026"
ACCOUNTS = {
    "inspector": ("inspector", None),
    "system_admin": ("system_admin", None),
    "org_admin": ("org_admin", "ORG-FARM"),
    "farmer": ("farmer", "ORG-FARM"),
    "processor": ("processor", "ORG-PROC"),
    "transporter": ("transporter", "ORG-DIST"),
    "distributor": ("distributor", "ORG-DIST"),
    "org_admin_proc": ("org_admin", "ORG-PROC"),
    "org_admin_dist": ("org_admin", "ORG-DIST"),
}


def validate_target(path):
    path = Path(path).resolve()
    original = ROOT / "backend" / "ttcs.db"
    if path == original.resolve() or (path.exists() and path.samefile(original)):
        raise ValueError("Original database is forbidden")
    if not path.is_relative_to(TRIAL.resolve()) or path.suffix != ".db":
        raise ValueError("Demo DB must be a .db inside .recall-trial")
    return path


def prepare(path):
    """Build only in memory; publish to a NEW, exclusively created trial file."""
    path = validate_target(path)
    if path.exists():
        # Read-only validation; refuse unrelated or previous-phase databases.
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as conn:
            if conn.execute("SELECT value FROM recall_demo_marker WHERE name='phase'").fetchone() != ("3B.2B",):
                raise ValueError("Not a Recall 3B.2B synthetic demo")
        return path
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import Session
    from app.database import Base
    from app.models import Organization, User
    from app.security import hash_password
    from scripts.seed_recall_s39 import seed_recall_s39

    memory = create_engine("sqlite:///:memory:")
    @event.listens_for(memory, "connect")
    def foreign_keys(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(memory)
    with Session(memory) as db:
        seed_recall_s39(db)
        orgs = {o.code: o.id for o in db.query(Organization).all()}
        hashed = hash_password(PASSWORD)
        for name, (role, org) in ACCOUNTS.items():
            db.add(User(username=f"recall_{name}", email=f"recall_{name}@demo.local", password=hashed, role=role, organization_id=orgs.get(org)))
        db.commit()
    with memory.connect() as conn:
        conn.exec_driver_sql("CREATE TABLE recall_demo_marker (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.exec_driver_sql("INSERT INTO recall_demo_marker VALUES ('phase','3B.2B')")
        conn.commit()
        path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation prevents overwriting even if a path appears concurrently.
        with path.open("xb"):
            pass
        with sqlite3.connect(path) as target:
            conn.connection.driver_connection.backup(target)
    memory.dispose()
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    target = validate_target(args.db)
    # Must precede app.database import; override inherited DATABASE_URL explicitly.
    os.environ["DATABASE_URL"] = "sqlite:///" + target.as_posix()
    os.environ["APP_ENV"] = "test"
    os.environ["SEED_DEFAULT_USERS"] = "0"
    prepare(target)
    print(f"Synthetic database: {target}")
    if args.prepare_only:
        return
    from app.main import app
    from fastapi.responses import HTMLResponse
    from fastapi.staticfiles import StaticFiles
    import uvicorn

    @app.get("/", include_in_schema=False)
    def demo_index():
        html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        config = '<script>window.AGRITRACE_CONFIG={apiBase:window.location.origin};</script>'
        banner = '<p class="recall-warning" role="status">DEMO RECALL 3B.2B · database tổng hợp riêng · tài khoản recall_&lt;vai trò&gt; · mật khẩu RecallDemo!2026</p>'
        html = html.replace('<script src="js/app.js', config + '<script src="js/app.js')
        html = html.replace('<body>', '<body>' + banner)
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    app.mount("/js", StaticFiles(directory=ROOT / "frontend" / "js"), name="recall-demo-js")
    app.mount("/css", StaticFiles(directory=ROOT / "frontend" / "css"), name="recall-demo-css")
    # Disable legacy startup entirely: the synthetic schema is already complete.
    uvicorn.run(app, host="127.0.0.1", port=args.port, lifespan="off")


if __name__ == "__main__":
    main()
