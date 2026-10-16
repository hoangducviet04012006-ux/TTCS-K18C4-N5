"""Synthetic Sprint 1-3 demo: same-origin UI/API and an isolated new database.
No original DB copy or migration. Existing lineage fixture is built in memory.
"""
import argparse
import os
from pathlib import Path
import sqlite3
import json
import secrets
import subprocess

ROOT = Path(__file__).resolve().parents[2]
TRIAL = ROOT / ".sprint123-trial"
CREDENTIALS = TRIAL / "credentials.local"
ACCOUNTS = {
    "admin": ("system_admin", "HTX-TC"),
    "farm": ("farmer", "HTX-TC"),
    "packing": ("processor", "HTX-TC"),
    "receiver": ("processor", "LOG-HN"),
    "transport": ("transporter", "LOG-HN"),
    "distribution": ("distributor", "NPP-BN"),
    "inspector": ("inspector", None),
    "org_admin": ("org_admin", "HTX-TC"),
}


def validate_target(path):
    path = Path(path).resolve()
    original = ROOT / "backend" / "ttcs.db"
    if path == original.resolve() or (path.exists() and original.exists() and path.samefile(original)):
        raise ValueError("Original database is forbidden")
    if not path.is_relative_to(TRIAL.resolve()) or path.suffix != ".db":
        raise ValueError("Use a .db file inside .sprint123-trial")
    return path


def check_database(path):
    path = validate_target(path)
    if not path.is_file():
        raise ValueError("Demo database missing: explicitly run --prepare-only once. Startup never seeds.")
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as conn:
        conn.execute("PRAGMA query_only=ON")
        if conn.execute("SELECT value FROM sprint_demo_marker WHERE name='scope'").fetchone() != ("sprint123",):
            raise ValueError("Not an isolated Sprint 1-3 demo")
        for table in ("users", "user_sessions", "batch_events", "batch_relations", "handovers"):
            conn.execute(f'SELECT * FROM "{table}" LIMIT 0')
        conn.execute("SELECT username,email,password,role,organization_id,is_active,failed_login_attempts,locked_until FROM users LIMIT 0")
        conn.execute("SELECT remaining_quantity,status,current_org_id,product_id,plot_id FROM batches LIMIT 0")
        conn.execute("SELECT session_id,user_id,csrf_token,created_at,expires_at,is_revoked FROM user_sessions LIMIT 0")
        if conn.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise ValueError("Demo integrity check failed; no automatic repair/migration")
    return path


def local_credentials():
    """Create private, Git-ignored credentials once; never print their contents."""
    if CREDENTIALS.exists():
        data = json.loads(CREDENTIALS.read_text(encoding="utf-8"))
        if set(data) != set(ACCOUNTS) or any(len(p) < 16 for p in data.values()):
            raise ValueError("Invalid local credentials; no automatic overwrite")
        return data
    CREDENTIALS.parent.mkdir(parents=True, exist_ok=True)
    with CREDENTIALS.open("x", encoding="utf-8") as stream:
        if os.name == "nt":
            user = subprocess.check_output(["whoami"], text=True).strip()
            subprocess.run(["icacls", str(CREDENTIALS), "/inheritance:r", "/grant:r", user + ":F"],
                           check=True, stdout=subprocess.DEVNULL)
        else:
            os.chmod(CREDENTIALS, 0o600)
        data = {name: secrets.token_urlsafe(24) for name in ACCOUNTS}
        json.dump(data, stream, indent=2)
    return data


def prepare(path, passwords=None):
    path = validate_target(path)
    if path.exists():
        return check_database(path)
    passwords = passwords or {name: secrets.token_urlsafe(24) for name in ACCOUNTS}
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from app.database import Base, create_event_immutability_triggers
    from app.models import Organization, User
    from app.security import hash_password
    from app.seeds.seed_lineage_graph import seed_lineage_graph

    memory = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(memory, tables=[t for t in Base.metadata.sorted_tables if not t.info.get("recall_trial")])
    with Session(memory) as db:
        # The fixture needs an actor for historical events. It cannot log in.
        os.environ["DEMO_PASSWORD"] = secrets.token_urlsafe(32)
        seed_lineage_graph(db)
        for fixture_user in db.scalars(select(User)):
            fixture_user.is_active = False
        orgs = {o.code: o.id for o in db.scalars(select(Organization))}
        fallback_map = {"HTX-TC": "HTX-DT", "LOG-HN": "HTX-TG", "NPP-BN": "DN-XNK"}
        for name, (role, org) in ACCOUNTS.items():
            org_id = orgs.get(org) if org in orgs else orgs.get(fallback_map.get(org))
            hashed = hash_password(passwords[name])
            db.add(User(username=f"s123_{name}", email=f"s123_{name}@demo.local", password=hashed, role=role, organization_id=org_id))
        db.commit()
    create_event_immutability_triggers(memory)
    with memory.connect() as conn:
        conn.exec_driver_sql("""CREATE TABLE user_sessions (
            session_id VARCHAR(128) PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            csrf_token VARCHAR(128) NOT NULL, created_at TIMESTAMP NOT NULL,
            expires_at TIMESTAMP NOT NULL, is_revoked BOOLEAN NOT NULL DEFAULT 0)""")
        conn.exec_driver_sql("CREATE INDEX ix_user_sessions_user_id ON user_sessions(user_id)")
        conn.exec_driver_sql("CREATE INDEX ix_user_sessions_expires_at ON user_sessions(expires_at)")
        conn.exec_driver_sql("CREATE TABLE sprint_demo_marker (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.exec_driver_sql("INSERT INTO sprint_demo_marker VALUES ('scope','sprint123')")
        conn.commit()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb"):
            pass
        with sqlite3.connect(path) as target:
            conn.connection.driver_connection.backup(target)
    memory.dispose()
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--enable-recall", action="store_true", help="QA only, requires migrated Recall schema")
    args = parser.parse_args()
    target = validate_target(args.db)
    os.environ["DATABASE_URL"] = "sqlite:///" + target.as_posix()
    os.environ["TTCS_ENV"] = "test"
    if args.prepare_only:
        if target.exists():
            check_database(target)
        else:
            prepare(target, local_credentials())
        print("Prepared synthetic Sprint 1-3 demo only.")
        return
    check_database(target)
    if args.enable_recall:
        if not target.name.startswith("qa_"):
            raise ValueError("Recall UI is enabled only on an explicit qa_*.db copy")
        with sqlite3.connect(target.as_uri() + "?mode=ro", uri=True) as db:
            for table in ("recalls", "recall_acknowledgments", "idempotency_records"):
                db.execute(f'SELECT * FROM "{table}" LIMIT 0')
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='uq_recall_event_evidence'").fetchone():
                raise ValueError("Recall event evidence index missing")
    from app.main import app
    from fastapi.responses import HTMLResponse
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles
    import uvicorn

    @app.get("/demo-scope", include_in_schema=False)
    def demo_scope():
        return {"scope": "sprint123", "synthetic": True, "database_name": target.name,
                "database_path": str(target), "code_root": str(ROOT)}

    @app.get("/", include_in_schema=False)
    def demo_index():
        html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        config = '<script>window.AGRITRACE_CONFIG={apiBase:window.location.origin,maxSprint:3,practiceMode:' + ("true" if target.parent.name == "practice" else "false") + ',recallEnabled:' + ("true" if args.enable_recall else "false") + '};</script>'
        if not args.enable_recall:
            config += '<style>#recall-card,a[href="#recall-card"]{display:none!important}</style>'
        html = html.replace('<script src="js/app.js', config + '<script src="js/app.js')
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    app.mount("/js", StaticFiles(directory=ROOT / "frontend" / "js"), name="sprint-demo-js")
    app.mount("/css", StaticFiles(directory=ROOT / "frontend" / "css"), name="sprint-demo-css")
    app.mount("/assets", StaticFiles(directory=ROOT / "frontend" / "assets"), name="sprint-demo-assets")
    if target.parent.name == "practice":
        @app.get("/practice-guide", include_in_schema=False)
        def practice_guide():
            return FileResponse(ROOT / "docs" / "practice-guide.html")

        @app.get("/practice-files/{filename}", include_in_schema=False)
        def practice_csv(filename: str):
            from fastapi import HTTPException
            allowed = {f"{prefix}-{kind}.csv" for prefix in ("TH1", "TH2") for kind in ("san-pham", "thua-dat")}
            if filename not in allowed:
                raise HTTPException(404, "Không tìm thấy tệp thực hành.")
            return FileResponse(target.parent / filename, filename=filename)
    # No init_db/migration/startup seed: current synthetic schema is ready.
    uvicorn.run(app, host="127.0.0.1", port=args.port, lifespan="off")


if __name__ == "__main__":
    main()
