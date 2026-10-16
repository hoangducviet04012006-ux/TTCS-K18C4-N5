"""Main entrypoint runner for AgriTrace application.
Starts unified FastAPI backend with embedded frontend static files,
connecting strictly to data/agritrace.db with zero auto-seeding or migrations.
"""
import argparse
import os
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "agritrace.db"
if str((ROOT / "backend").resolve()) not in sys.path:
    sys.path.insert(0, str((ROOT / "backend").resolve()))


def validate_database(path: Path) -> Path:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Database file not found: {path}")

    # Forbid original unmigrated database
    original = (ROOT / "backend" / "ttcs.db").resolve()
    if path == original or (path.exists() and original.exists() and path.samefile(original)):
        raise ValueError("Original database backend/ttcs.db is forbidden. Use data/agritrace.db.")

    # Integrity & structural validation
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as conn:
        conn.execute("PRAGMA query_only=ON")
        integrity = conn.execute("PRAGMA integrity_check").fetchone()
        if integrity != ("ok",):
            raise ValueError(f"Database integrity check failed: {integrity}")

        # Check essential canonical tables of unified AgriTrace
        expected_tables = (
            "users", "user_sessions", "batches", "batch_events", "batch_relations",
            "handovers", "recalls", "recall_acknowledgments", "locations", "audit_logs",
            "farms", "plots", "products", "organizations"
        )
        for tbl in expected_tables:
            conn.execute(f'SELECT 1 FROM "{tbl}" LIMIT 0')

        batch_count = conn.execute("SELECT COUNT(*) FROM batches").fetchone()[0]
        if batch_count < 58:
            raise ValueError(f"Unified database must contain all batches (expected >= 58, found {batch_count}).")

        # Check marker
        marker = conn.execute(
            "SELECT value FROM sprint_demo_marker WHERE name='scope'"
        ).fetchone()
        if not marker or marker[0] != "sprint123":
            raise ValueError("Invalid database marker; scope must be 'sprint123'.")

    return path


def main():
    parser = argparse.ArgumentParser(description="AgriTrace Main Runner")
    parser.add_argument("--db", type=str, default=str(DEFAULT_DB), help="Path to unified SQLite database")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host interface")
    parser.add_argument("--port", type=int, default=8765, help="Port to listen on")
    args = parser.parse_args()

    db_path = validate_database(Path(args.db))

    # Configure environment
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ["TTCS_ENV"] = "production"
    os.environ["TTCS_SEED_DEFAULTS"] = "0"

    from app.main import app
    from fastapi.responses import HTMLResponse, FileResponse
    from fastapi.staticfiles import StaticFiles
    import uvicorn

    @app.get("/system-info", include_in_schema=False)
    @app.get("/demo-scope", include_in_schema=False)
    def system_info():
        return {
            "app": "AgriTrace",
            "scope": "sprint123",
            "database_name": db_path.name,
            "database_path": str(db_path),
            "code_root": str(ROOT),
            "multi_dataset": True,
        }

    @app.get("/", include_in_schema=False)
    def index():
        html_file = ROOT / "frontend" / "index.html"
        html = html_file.read_text(encoding="utf-8")
        config = (
            '<script>'
            'window.AGRITRACE_CONFIG={'
            'apiBase:window.location.origin,'
            'maxSprint:4,'
            'practiceMode:false,'
            'recallEnabled:true,'
            'multiDatasetEnabled:true'
            '};'
            '</script>'
        )
        html = html.replace('<script src="js/app.js', config + '<script src="js/app.js')
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    # Static mounts
    frontend_dir = ROOT / "frontend"
    app.mount("/js", StaticFiles(directory=frontend_dir / "js"), name="agritrace-js")
    app.mount("/css", StaticFiles(directory=frontend_dir / "css"), name="agritrace-css")
    app.mount("/assets", StaticFiles(directory=frontend_dir / "assets"), name="agritrace-assets")

    docs_dir = ROOT / "docs"
    guide_path = docs_dir / "practice-guide.html"
    if guide_path.exists():
        @app.get("/practice-guide", include_in_schema=False)
        def practice_guide():
            return FileResponse(guide_path)

    print(f"[*] AgriTrace starting on http://{args.host}:{args.port}/")
    print(f"[*] Unified Database: {db_path}")
    uvicorn.run(app, host=args.host, port=args.port, lifespan="off")


if __name__ == "__main__":
    main()
