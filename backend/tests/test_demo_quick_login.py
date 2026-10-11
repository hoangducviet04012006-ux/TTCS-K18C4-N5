"""Kiểm thử tự động cho chức năng đăng nhập nhanh Demo (POST /auth/demo-login)."""
import os
import sqlite3
from datetime import date
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base, get_db
from app.main import app
from app.models import Organization, User
from app.security import hash_password
from app.services.session_store import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME

ALL_EIGHT_DEMO_ACCOUNTS = [
    ("s123_farm", "s123_farm@demo.local", "farmer", 1),
    ("s123_packing", "s123_packing@demo.local", "processor", 1),
    ("s123_receiver", "s123_receiver@demo.local", "processor", 2),
    ("s123_transport", "s123_transport@demo.local", "transporter", 2),
    ("s123_distribution", "s123_distribution@demo.local", "distributor", 3),
    ("s123_inspector", "s123_inspector@demo.local", "inspector", None),
    ("s123_admin", "s123_admin@demo.local", "system_admin", 1),
    ("s123_org_admin", "s123_org_admin@demo.local", "org_admin", 1),
]


@pytest.fixture
def demo_db_client(tmp_path, monkeypatch):
    """Tạo client với database demo Sprint 1–3 biệt lập trong thư mục tạm."""
    db_file = tmp_path / "demo_sprint123_test.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setattr("app.database.DATABASE_URL", db_url)
    monkeypatch.setattr("app.routers.auth.DATABASE_URL", db_url)

    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)

    # Thêm bảng sprint_demo_marker và user_sessions
    with engine.connect() as conn:
        conn.exec_driver_sql("CREATE TABLE IF NOT EXISTS sprint_demo_marker (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.exec_driver_sql("INSERT OR REPLACE INTO sprint_demo_marker VALUES ('scope', 'sprint123')")
        conn.exec_driver_sql("""
            CREATE TABLE IF NOT EXISTS user_sessions (
                session_id VARCHAR(128) PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                csrf_token VARCHAR(128) NOT NULL,
                created_at TIMESTAMP NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                is_revoked BOOLEAN NOT NULL DEFAULT 0
            )
        """)
        conn.commit()

    with Session(engine) as db:
        org_dt = Organization(id=1, code="HTX-DT", name="Hợp tác xã Đồng Tháp")
        org_tg = Organization(id=2, code="HTX-TG", name="Hợp tác xã Tiền Giang")
        org_xnk = Organization(id=3, code="DN-XNK", name="DN Xuất nhập khẩu")
        db.add_all([org_dt, org_tg, org_xnk])
        db.flush()

        pwd = hash_password("DemoPassword123!")
        for username, email, role, org_id in ALL_EIGHT_DEMOACCOUNTS if False else ALL_EIGHT_DEMO_ACCOUNTS:
            db.add(User(
                username=username,
                email=email,
                role=role,
                organization_id=org_id,
                password=pwd,
                is_active=True,
            ))
        db.commit()

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    yield client
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


@pytest.mark.parametrize("username,email,role,org_id", ALL_EIGHT_DEMO_ACCOUNTS)
def test_demo_quick_login_all_eight_accounts_by_email(demo_db_client, username, email, role, org_id):
    """Kiểm thử đăng nhập nhanh đủ 8 tài khoản bằng email không cần mật khẩu."""
    res = demo_db_client.post("/auth/demo-login", json={"username": email})
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["username"] == username
    assert data["email"] == email
    assert data["role"] == role
    assert data["organization_id"] == org_id
    assert "csrf_token" in data
    assert SESSION_COOKIE_NAME in res.cookies
    assert CSRF_COOKIE_NAME in res.cookies

    # Kiểm tra truy cập /auth/me bằng session vừa tạo
    me_res = demo_db_client.get("/auth/me")
    assert me_res.status_code == 200
    assert me_res.json()["username"] == username


@pytest.mark.parametrize("username,email,role,org_id", ALL_EIGHT_DEMO_ACCOUNTS)
def test_demo_quick_login_all_eight_accounts_by_username(demo_db_client, username, email, role, org_id):
    """Kiểm thử đăng nhập nhanh đủ 8 tài khoản bằng username không cần mật khẩu."""
    res = demo_db_client.post("/auth/demo-login", json={"username": username})
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["username"] == username
    assert data["role"] == role


def test_demo_quick_login_refuses_non_demo_accounts(demo_db_client):
    """Chỉ 8 tài khoản demo được phép đăng nhập nhanh; từ chối mọi tài khoản khác."""
    for invalid in ["admin", "farmer", "demo_admin", "hacker", "s123_other@demo.local"]:
        res = demo_db_client.post("/auth/demo-login", json={"username": invalid})
        assert res.status_code == 403
        assert "không thuộc danh sách 8 tài khoản demo" in res.json()["detail"]


def test_demo_quick_login_refuses_non_localhost(demo_db_client):
    """Từ chối nếu request đến từ địa chỉ IP bên ngoài không phải localhost."""
    headers = {"X-Forwarded-For": "203.0.113.195"}
    res = demo_db_client.post("/auth/demo-login", json={"username": "s123_farm@demo.local"}, headers=headers)
    assert res.status_code == 403
    assert "chỉ được phép truy cập từ localhost" in res.json()["detail"]


def test_demo_quick_login_refuses_original_database(tmp_path, monkeypatch):
    """Từ chối tuyệt đối khi DATABASE_URL trỏ vào backend/ttcs.db gốc."""
    from app.database import DATABASE_FILE
    fake_orig_url = f"sqlite:///{DATABASE_FILE.as_posix()}"
    monkeypatch.setattr("app.routers.auth.DATABASE_URL", fake_orig_url)

    client = TestClient(app)
    res = client.post("/auth/demo-login", json={"username": "s123_farm@demo.local"})
    assert res.status_code == 403
    assert "bị từ chối trên cơ sở dữ liệu gốc" in res.json()["detail"]


def test_demo_quick_login_refuses_database_without_marker(tmp_path, monkeypatch):
    """Từ chối nếu database không chứa marker scope=sprint123."""
    db_file = tmp_path / "plain.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    monkeypatch.setattr("app.database.DATABASE_URL", db_url)
    monkeypatch.setattr("app.routers.auth.DATABASE_URL", db_url)

    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        res = client.post("/auth/demo-login", json={"username": "s123_farm@demo.local"})
        assert res.status_code == 403
        assert "chỉ khả dụng với database demo Sprint 1–3" in res.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
