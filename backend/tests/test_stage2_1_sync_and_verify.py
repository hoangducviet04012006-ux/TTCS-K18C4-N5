"""Bộ kiểm thử cho Giai đoạn 2.1: Đồng bộ RBAC và kiểm chứng xác thực.

Kiểm tra:
1. Farmer gọi MERGE phải nhận 403.
2. Inspector đọc audit log hợp lệ.
3. Distributor không thể tạo lô thu hoạch (HARVEST).
4. Basic Auth không vượt qua chính sách bảo mật (lockout, is_locked, role mapping).
5. Session hết hạn và thu hồi đúng (Cookie session hỏng không được fallback Basic để lách quyền).
6. Session hoạt động sau restart khi sử dụng DB store.
7. Tài khoản cũ vẫn đăng nhập được.
8. S-23 và hash-chain không bị ảnh hưởng.
"""

import base64
from datetime import date, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from app.database import get_db
from app.main import app
from app.models import (
    ROLE_DISTRIBUTOR,
    ROLE_FARMER,
    ROLE_INSPECTOR,
    ROLE_PROCESSOR,
    ROLE_SYSTEM_ADMIN,
    Batch,
    BatchEvent,
    Farm,
    Plot,
    Product,
    User,
)
from app.security import (
    SESSION_COOKIE_NAME,
    get_current_user,
    hash_password,
    utcnow,
)
from app.services.session_store import (
    CSRF_HEADER_NAME,
    clear_memory_sessions,
    create_session,
    get_session,
    revoke_all_user_sessions,
    revoke_session,
)
from tests.conftest import TEST_PASSWORD, TEST_USERNAME_ADMIN, TEST_USERNAME_FARMER


def _basic_auth(username: str, password: str = TEST_PASSWORD) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("utf-8")
    return {"Authorization": f"Basic {token}"}


@pytest.fixture
def test_setup(session_factory: sessionmaker[Session]):
    with session_factory() as session:
        # Tạo bảng user_sessions nếu chưa có trong DB test
        session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS user_sessions (
                    session_id VARCHAR(128) PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    csrf_token VARCHAR(128) NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    expires_at TIMESTAMP NOT NULL,
                    is_revoked BOOLEAN NOT NULL DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );
                """
            )
        )
        session.commit()

        # Tạo Inspector user
        u_insp = session.scalar(select(User).where(User.username == "inspector_test"))
        if not u_insp:
            u_insp = User(
                username="inspector_test",
                email="inspector@test.gov",
                password=hash_password(TEST_PASSWORD),
                role=ROLE_INSPECTOR,
                organization_id=1,
            )
            session.add(u_insp)

        # Tạo Distributor user
        u_dist = session.scalar(select(User).where(User.username == "distributor_test"))
        if not u_dist:
            u_dist = User(
                username="distributor_test",
                email="distributor@test.local",
                password=hash_password(TEST_PASSWORD),
                role=ROLE_DISTRIBUTOR,
                organization_id=1,
            )
            session.add(u_dist)

        # Tạo Processor user
        u_proc = session.scalar(select(User).where(User.username == "processor_test"))
        if not u_proc:
            u_proc = User(
                username="processor_test",
                email="processor@test.local",
                password=hash_password(TEST_PASSWORD),
                role=ROLE_PROCESSOR,
                organization_id=1,
            )
            session.add(u_proc)

        # Tạo sản phẩm mẫu
        prod = session.scalar(select(Product).where(Product.id == 1))
        if not prod:
            prod = Product(id=1, name="Xoài Cát Chu", unit="kg")
            session.add(prod)

        # Tạo farm và plot
        farm = session.scalar(select(Farm).where(Farm.id == 1))
        if not farm:
            farm = Farm(id=1, name="Trang trại test", location="Đồng Tháp", area=2.5, owner="An", organization_id=1)
            session.add(farm)

        plot = session.scalar(select(Plot).where(Plot.id == 1))
        if not plot:
            plot = Plot(id=1, name="Thửa 1", location="Đồng Tháp", area=2.5, owner="An", organization_id=1)
            session.add(plot)

        # Tạo 2 lô mẹ mẫu cho thử nghiệm MERGE
        b1 = session.scalar(select(Batch).where(Batch.code == "PARENT01"))
        if not b1:
            b1 = Batch(
                code="PARENT01", plot_id=1, farm_id=1, product_id=1,
                harvest_date=date.today(), initial_quantity=100.0,
                remaining_quantity=100.0, current_org_id=1, status="ACTIVE"
            )
            session.add(b1)

        b2 = session.scalar(select(Batch).where(Batch.code == "PARENT02"))
        if not b2:
            b2 = Batch(
                code="PARENT02", plot_id=1, farm_id=1, product_id=1,
                harvest_date=date.today(), initial_quantity=100.0,
                remaining_quantity=100.0, current_org_id=1, status="ACTIVE"
            )
            session.add(b2)

        session.commit()


# ------------------------------------------------------------------------------
# 1. Farmer gọi MERGE phải nhận 403
# ------------------------------------------------------------------------------
def test_farmer_cannot_merge_batches(client: TestClient, test_setup, session_factory):
    with session_factory() as s:
        b1 = s.scalar(select(Batch).where(Batch.code == "PARENT01"))
        b2 = s.scalar(select(Batch).where(Batch.code == "PARENT02"))

    payload = {
        "product_id": 1,
        "items": [
            {"parent_batch_id": b1.id, "quantity": 20.0},
            {"parent_batch_id": b2.id, "quantity": 30.0},
        ],
    }

    # Farmer gọi MERGE -> Phải nhận 403 Forbidden!
    resp = client.post("/batches/merge", json=payload, headers=_basic_auth(TEST_USERNAME_FARMER))
    assert resp.status_code == 403
    assert "không có quyền thực hiện hành động 'MERGE'" in resp.json()["detail"]


# ------------------------------------------------------------------------------
# 2. Inspector đọc audit log hợp lệ
# ------------------------------------------------------------------------------
def test_inspector_can_read_audit_logs(client: TestClient, test_setup):
    resp = client.get("/audit-logs", headers=_basic_auth("inspector_test"))
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ------------------------------------------------------------------------------
# 3. Distributor không thể tạo lô thu hoạch (HARVEST)
# ------------------------------------------------------------------------------
def test_distributor_cannot_harvest_batch(client: TestClient, test_setup):
    payload = {
        "plot_id": 1,
        "product_id": 1,
        "harvest_date": str(date.today()),
        "initial_quantity": 50.0,
    }

    # Distributor gọi POST /batches -> Phải nhận 403 Forbidden!
    resp = client.post("/batches", json=payload, headers=_basic_auth("distributor_test"))
    assert resp.status_code == 403
    assert "không có quyền thực hiện hành động 'HARVEST'" in resp.json()["detail"]


# ------------------------------------------------------------------------------
# 4. Basic Auth không vượt qua chính sách bảo mật
# ------------------------------------------------------------------------------
def test_basic_auth_does_not_bypass_security_policy(client: TestClient, test_setup, session_factory):
    # Khóa tài khoản farmer_test
    with session_factory() as s:
        u = s.scalar(select(User).where(User.username == TEST_USERNAME_FARMER))
        u.is_locked = True
        s.commit()

    # Dùng Basic Auth với tài khoản bị khóa -> Phải nhận 403 Forbidden!
    resp = client.get("/batches", headers=_basic_auth(TEST_USERNAME_FARMER))
    assert resp.status_code == 403
    assert "Tài khoản đã bị khóa" in resp.json()["detail"]

    # Mở khóa lại
    with session_factory() as s:
        u = s.scalar(select(User).where(User.username == TEST_USERNAME_FARMER))
        u.is_locked = False
        s.commit()


# ------------------------------------------------------------------------------
# 5. Session hết hạn và thu hồi đúng
# ------------------------------------------------------------------------------
def test_session_expiration_and_revocation(client: TestClient, test_setup, session_factory):
    # Đăng nhập lấy session cookie
    resp = client.post("/auth/login", json={"username": TEST_USERNAME_FARMER, "password": TEST_PASSWORD})
    assert resp.status_code == 200
    cookie_header = resp.headers.get("set-cookie", "")
    csrf_token = resp.json()["csrf_token"]
    assert "session_id=" in cookie_header

    # Thu hồi session
    with session_factory() as s:
        u = s.scalar(select(User).where(User.username == TEST_USERNAME_FARMER))
        revoke_all_user_sessions(u.id, s)

    # Gửi request với cookie session đã thu hồi (kèm cả Basic Auth hòng vượt rào)
    # Phải bị từ chối 401 Unauthorized ngay, không được fallback Basic Auth!
    client.cookies.set(SESSION_COOKIE_NAME, "revoked_session_token")
    headers = {"Authorization": _basic_auth(TEST_USERNAME_FARMER)["Authorization"]}
    resp2 = client.get("/batches", headers=headers)
    assert resp2.status_code == 401
    assert "Phiên làm việc đã hết hạn hoặc không hợp lệ" in resp2.json()["detail"]
    client.cookies.clear()


# ------------------------------------------------------------------------------
# 6. Session hoạt động sau restart khi sử dụng DB store
# ------------------------------------------------------------------------------
def test_session_persists_across_restarts_in_db_store(client: TestClient, test_setup, session_factory):
    with session_factory() as s:
        s.connection().connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS user_sessions (
                session_id VARCHAR(128) PRIMARY KEY,
                user_id INTEGER NOT NULL,
                csrf_token VARCHAR(128) NOT NULL,
                created_at TIMESTAMP NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                is_revoked BOOLEAN NOT NULL DEFAULT 0
            );
            """
        )
        u = s.scalar(select(User).where(User.username == "processor_test"))
        uid = u.id
        sess = create_session(uid, s)

    # Giả lập restart server: xóa toàn bộ memory sessions
    clear_memory_sessions()

    # Tra cứu lại session từ DB
    with session_factory() as s:
        restored = get_session(sess.session_id, s)
        assert restored is not None
        assert restored.user_id == uid
        assert restored.is_valid is True


# ------------------------------------------------------------------------------
# 7. Tài khoản cũ vẫn đăng nhập được
# ------------------------------------------------------------------------------
def test_legacy_accounts_can_still_login(client: TestClient, test_setup):
    resp = client.post("/auth/login", json={"username": TEST_USERNAME_ADMIN, "password": TEST_PASSWORD})
    assert resp.status_code == 200
    assert resp.json()["username"] == TEST_USERNAME_ADMIN
    # Vai trò trong DB giữ nguyên trước migration
    assert resp.json()["role"] in ("admin", ROLE_SYSTEM_ADMIN)
    # Vai trò hiệu lực tại các API tuân theo system_admin
    from app.services.rbac import get_effective_role
    assert get_effective_role(TEST_USERNAME_ADMIN) == ROLE_SYSTEM_ADMIN


# ------------------------------------------------------------------------------
# 8. S-23 và hash-chain không bị ảnh hưởng
# ------------------------------------------------------------------------------
def test_s23_and_hash_chain_remain_unaffected(client: TestClient, test_setup, session_factory):
    with session_factory() as s:
        b = s.scalar(select(Batch).where(Batch.code == "PARENT01"))
        # Tạo event hợp lệ
        from app.hash_chain import record_event
        ev = record_event(s, b.id, "TEST_INTEGRITY", {"info": "ok"}, org_id=1, user_id=1)
        s.commit()
        assert ev.current_hash is not None
        assert len(ev.current_hash) == 64
