"""The demo must never select or overwrite the user's original database."""
import sqlite3

import pytest

from scripts.run_sprint123_demo import ROOT, validate_target, prepare


def test_demo_refuses_original_and_outside_paths():
    for path in [ROOT / "backend" / "ttcs.db", ROOT / "unsafe.db", ROOT / ".sprint123-trial" / ".." / "unsafe.db"]:
        with pytest.raises(ValueError):
            validate_target(path)


def test_demo_refuses_existing_unmarked_database(tmp_path, monkeypatch):
    import scripts.run_sprint123_demo as demo
    monkeypatch.setattr(demo, "TRIAL", tmp_path)
    target = tmp_path / "other.db"
    with sqlite3.connect(target) as conn:
        conn.execute("CREATE TABLE preserve (value TEXT)")
        conn.execute("INSERT INTO preserve VALUES ('unchanged')")
    before = target.read_bytes()
    with pytest.raises(sqlite3.OperationalError):
        prepare(target)
    assert target.read_bytes() == before


def test_demo_new_schema_and_repeat_are_safe(tmp_path, monkeypatch):
    import scripts.run_sprint123_demo as demo
    monkeypatch.setattr(demo, "TRIAL", tmp_path)
    target = prepare(tmp_path / "demo.db")
    with sqlite3.connect(target) as conn:
        assert conn.execute("SELECT count(*) FROM batches").fetchone()[0] == 14
        assert conn.execute("SELECT count(*) FROM organizations").fetchone()[0] == 3
        assert conn.execute("SELECT count(*) FROM sqlite_master WHERE name='recalls'").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM users WHERE username LIKE 's123_%'").fetchone()[0] == 8
        assert conn.execute("SELECT count(*) FROM users WHERE is_active=1").fetchone()[0] == 8
        assert conn.execute("SELECT count(*) FROM sqlite_master WHERE type='trigger'").fetchone()[0] >= 2
    before = target.read_bytes()
    assert prepare(target) == target
    assert target.read_bytes() == before


def test_startup_missing_database_never_prepares(tmp_path, monkeypatch):
    import scripts.run_sprint123_demo as demo
    monkeypatch.setattr(demo, "TRIAL", tmp_path)
    target = tmp_path / "missing.db"
    monkeypatch.setattr("sys.argv", ["demo", "--db", str(target)])
    monkeypatch.setattr(demo, "prepare", lambda *args: pytest.fail("Startup seeded"))
    with pytest.raises(ValueError, match="Startup never seeds"):
        demo.main()
    assert not target.exists()


def test_readonly_validation_never_changes_rows_or_file(tmp_path, monkeypatch):
    import scripts.run_sprint123_demo as demo
    monkeypatch.setattr(demo, "TRIAL", tmp_path)
    target = demo.prepare(tmp_path / "existing.db")
    before = target.read_bytes()
    for _ in range(3):
        assert demo.check_database(target) == target
    assert target.read_bytes() == before


def test_each_demo_account_has_its_own_password(tmp_path, monkeypatch):
    import scripts.run_sprint123_demo as demo
    from app.security import verify_password
    monkeypatch.setattr(demo, "TRIAL", tmp_path)
    passwords = {name: "Test-only-" + name + "-unique-credential" for name in demo.ACCOUNTS}
    target = demo.prepare(tmp_path / "accounts.db", passwords)
    with sqlite3.connect(target) as conn:
        for name, (role, _) in demo.ACCOUNTS.items():
            row = conn.execute("SELECT role,password,is_active FROM users WHERE username=?", ("s123_" + name,)).fetchone()
            assert row[0] == role and row[2] == 1
            assert verify_password(passwords[name], row[1])
            assert not verify_password("wrong-password", row[1])


def test_denied_request_is_logged_without_credentials(client, caplog):
    import logging
    with caplog.at_level(logging.WARNING, logger="agritrace.security"):
        response = client.get("/users", auth=("farmer", "123456"))
    assert response.status_code == 403
    assert "access_denied method=GET path=/users" in caplog.text
    assert "123456" not in caplog.text


def test_summary_owner_uses_three_business_queries(tmp_path, monkeypatch):
    import scripts.run_sprint123_demo as demo
    from sqlalchemy import create_engine, event, select
    from sqlalchemy.orm import Session
    from app.models import Batch, User
    from app.routers.batches import get_batch_summary
    monkeypatch.setattr(demo, "TRIAL", tmp_path)
    target = prepare(tmp_path / "budget.db")
    engine = create_engine("sqlite:///" + target.as_posix())
    queries = []
    with Session(engine) as db:
        actor = db.scalar(select(User).where(User.username == "s123_farm"))
        batch_id = db.scalar(select(Batch.id).where(Batch.code == "B-MERGE-01"))
        @event.listens_for(engine, "before_cursor_execute")
        def count(*args):
            queries.append(args[2])
        summary = get_batch_summary(batch_id, actor, db)
        assert len(summary.direct_parents) == 2
        assert len(queries) == 3
    engine.dispose()


def test_browser_missing_session_gets_401_without_basic_prompt(client):
    browser = client.get("/auth/me", headers={"X-Requested-With": "XMLHttpRequest"})
    assert browser.status_code == 401
    assert "WWW-Authenticate" not in browser.headers
    basic = client.get("/auth/me")
    assert basic.status_code == 401
    assert basic.headers["WWW-Authenticate"] == "Basic"
