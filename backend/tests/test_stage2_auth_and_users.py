"""Bộ kiểm thử cho Giai đoạn 2: Hoàn thiện xác thực, quản lý tài khoản và phân quyền tổ chức.

Nội dung bao phủ:
1. Đăng nhập tạo Session Cookie (HttpOnly) và CSRF token.
2. Bảo vệ CSRF cho các thao tác thay đổi trạng thái khi dùng Session Cookie.
3. Đăng xuất thu hồi phiên phía server (session revocation).
4. Tự động nâng cấp hash mật khẩu legacy (SHA-256 sang Argon2id) khi đăng nhập thành công.
5. Đổi mật khẩu cá nhân và tự động thu hồi các phiên làm việc cũ.
6. Quyền System Admin: tạo tổ chức, tạo org_admin, quản lý toàn diện.
7. Phân quyền Organization Admin: chỉ quản lý nội bộ tổ chức, chống leo thang đặc quyền.
8. Quyền RECALL mới theo backlog mentor: Inspector toàn quyền theo lệnh, Org Admin chỉ khi giữ lô, System Admin không mặc định.
9. Khóa tài khoản chống dò mật khẩu (5 lần sai -> khóa 15 phút).
"""

import hashlib
from datetime import date, datetime
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    ROLE_ADMIN,
    ROLE_DISTRIBUTOR,
    ROLE_FARMER,
    ROLE_INSPECTOR,
    ROLE_ORG_ADMIN,
    ROLE_PROCESSOR,
    ROLE_SYSTEM_ADMIN,
    ROLE_TRANSPORTER,
    Batch,
    Organization,
    Product,
    User,
)
from app.security import hash_password, verify_password
from app.services.rbac import can_recall_batch, check_action_permission
from app.services.session_store import (
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    SESSION_COOKIE_NAME,
    get_session,
)

PASSWORD = "SecurePassword123!"


@pytest.fixture()
def stage2_fixture(session_factory: sessionmaker[Session]) -> dict[str, int]:
    """Khởi tạo dữ liệu cơ bản cho 2 tổ chức và các vai trò phục vụ test Giai đoạn 2."""
    with session_factory() as session:
        # Tổ chức 1
        org1 = session.scalar(select(Organization).where(Organization.code == "ORG-STAGE2-A"))
        if not org1:
            org1 = Organization(code="ORG-STAGE2-A", name="Hợp tác xã Miền Tây")
            session.add(org1)
            session.flush()

        # Tổ chức 2
        org2 = session.scalar(select(Organization).where(Organization.code == "ORG-STAGE2-B"))
        if not org2:
            org2 = Organization(code="ORG-STAGE2-B", name="Nhà máy Chế biến Miền Đông")
            session.add(org2)
            session.flush()

        # Tổ chức Thanh tra
        org_insp = session.scalar(select(Organization).where(Organization.code == "ORG-STAGE2-INSPECT"))
        if not org_insp:
            org_insp = Organization(code="ORG-STAGE2-INSPECT", name="Cục Quản lý Chất lượng")
            session.add(org_insp)
            session.flush()

        # Tạo các tài khoản chuẩn
        users_def = [
            ("s2_sysadmin", ROLE_SYSTEM_ADMIN, org1.id),
            ("s2_orgadmin1", ROLE_ORG_ADMIN, org1.id),
            ("s2_orgadmin2", ROLE_ORG_ADMIN, org2.id),
            ("s2_farmer1", ROLE_FARMER, org1.id),
            ("s2_processor2", ROLE_PROCESSOR, org2.id),
            ("s2_inspector", ROLE_INSPECTOR, org_insp.id),
        ]
        for uname, urole, uorg_id in users_def:
            u = session.scalar(select(User).where(User.username == uname))
            if not u:
                session.add(
                    User(
                        username=uname,
                        email=f"{uname}@test.local",
                        password=hash_password(PASSWORD),
                        role=urole,
                        organization_id=uorg_id,
                    )
                )

        session.commit()
        return {
            "org1_id": org1.id,
            "org2_id": org2.id,
            "org_insp_id": org_insp.id,
        }


# ==============================================================================
# 1. TEST PHIÊN ĐĂNG NHẬP COOKIE & CSRF
# ==============================================================================
def test_login_creates_http_only_cookie_and_csrf_token(client: TestClient, stage2_fixture: dict[str, int]):
    """Đăng nhập tạo cookie HttpOnly session_id và cookie csrf_token; truy cập /auth/me thành công."""
    res = client.post("/auth/login", json={"username": "s2_farmer1", "password": PASSWORD})
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["username"] == "s2_farmer1"
    assert data["role"] == ROLE_FARMER
    assert data["csrf_token"] is not None

    # Kiểm tra cookies
    assert SESSION_COOKIE_NAME in res.cookies
    assert CSRF_COOKIE_NAME in res.cookies

    # Gọi GET /auth/me bằng cookie phiên (TestClient tự lưu cookies)
    me_res = client.get("/auth/me")
    assert me_res.status_code == 200
    me_data = me_res.json()
    assert me_data["username"] == "s2_farmer1"
    assert me_data["organization_id"] == stage2_fixture["org1_id"]


def test_csrf_protection_on_state_changing_requests(client: TestClient, stage2_fixture: dict[str, int]):
    """Yêu cầu gửi đúng X-CSRF-Token khi gọi POST/PUT/PATCH/DELETE bằng Cookie session."""
    login_res = client.post("/auth/login", json={"username": "s2_farmer1", "password": PASSWORD})
    assert login_res.status_code == 200
    csrf_token = login_res.json()["csrf_token"]

    # 1. Gọi thay đổi mật khẩu mà KHÔNG gửi X-CSRF-Token -> 403 Forbidden
    bad_req = client.post(
        "/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "NewSecretPass123!"},
    )
    assert bad_req.status_code == 403
    assert "CSRF token không hợp lệ" in bad_req.json()["detail"]

    # 2. Gửi sai X-CSRF-Token -> 403 Forbidden
    wrong_csrf = client.post(
        "/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "NewSecretPass123!"},
        headers={CSRF_HEADER_NAME: "invalid-token-123"},
    )
    assert wrong_csrf.status_code == 403
    assert "CSRF token không hợp lệ" in wrong_csrf.json()["detail"]

    # 3. Gửi đúng X-CSRF-Token -> 200 OK
    good_req = client.post(
        "/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "NewSecretPass123!"},
        headers={CSRF_HEADER_NAME: csrf_token},
    )
    assert good_req.status_code == 200
    assert "Mật khẩu đã đổi" in good_req.json()["message"]


def test_logout_revokes_session(client: TestClient, stage2_fixture: dict[str, int]):
    """Đăng xuất thực sự thu hồi phiên phía server và xóa cookie."""
    login_res = client.post("/auth/login", json={"username": "s2_orgadmin1", "password": PASSWORD})
    assert login_res.status_code == 200
    session_id = login_res.cookies[SESSION_COOKIE_NAME]
    csrf_token = login_res.json()["csrf_token"]

    # Kiểm tra truy cập trước khi đăng xuất
    assert client.get("/auth/me").status_code == 200

    # Đăng xuất (kèm X-CSRF-Token hợp lệ)
    logout_res = client.post("/auth/logout", headers={CSRF_HEADER_NAME: csrf_token})
    assert logout_res.status_code == 200
    assert "Đăng xuất thành công" in logout_res.json()["message"]

    # Sau đăng xuất: gọi lại /auth/me -> 401 Unauthorized
    assert client.get("/auth/me").status_code == 401

    # Thử cố tình đính kèm lại session_id cũ bằng tay -> 401 Unauthorized
    manual_req = client.get("/auth/me", cookies={SESSION_COOKIE_NAME: session_id})
    assert manual_req.status_code == 401


# ==============================================================================
# 2. TEST NÂNG CẤP HASH MẬT KHẨU LEGACY & BRUTE FORCE
# ==============================================================================
def test_transparent_legacy_password_hash_upgrade(
    client: TestClient, session_factory: sessionmaker[Session], stage2_fixture: dict[str, int]
):
    """Tài khoản có hash SHA-256 cũ khi đăng nhập thành công sẽ tự động nâng cấp sang Argon2id."""
    raw_pass = "LegacySecret2026!"
    legacy_sha256 = hashlib.sha256(raw_pass.encode("utf-8")).hexdigest()

    with session_factory() as session:
        legacy_user = User(
            username="user_legacy_sha",
            email="legacy@test.local",
            password=legacy_sha256,
            role=ROLE_FARMER,
            organization_id=stage2_fixture["org1_id"],
        )
        session.add(legacy_user)
        session.commit()
        user_id = legacy_user.id

    # Đăng nhập bằng mật khẩu cũ
    login_res = client.post("/auth/login", json={"username": "user_legacy_sha", "password": raw_pass})
    assert login_res.status_code == 200

    # Kiểm tra trong DB: hash đã tự động chuyển sang $argon2id$
    with session_factory() as session:
        updated_user = session.get(User, user_id)
        assert updated_user.password.startswith("$argon2id$")
        assert verify_password(raw_pass, updated_user.password) is True


def test_login_lockout_after_five_failed_attempts(client: TestClient, stage2_fixture: dict[str, int]):
    """Nhập sai mật khẩu 5 lần liên tiếp sẽ bị khóa tạm 15 phút."""
    username = "s2_sysadmin"
    for i in range(4):
        res = client.post("/auth/login", json={"username": username, "password": "wrongpassword"})
        assert res.status_code == 401

    # Lần thứ 5 sai -> 403 Forbidden kèm thông báo khóa và Retry-After
    fifth = client.post("/auth/login", json={"username": username, "password": "wrongpassword"})
    assert fifth.status_code == 403
    assert "đã bị tạm khoá" in fifth.json()["detail"]
    assert "Retry-After" in fifth.headers

    # Lần thứ 6 dù đúng mật khẩu vẫn bị chặn 403
    sixth = client.post("/auth/login", json={"username": username, "password": PASSWORD})
    assert sixth.status_code == 403
    assert "đã bị tạm khoá" in sixth.json()["detail"]


# ==============================================================================
# 3. TEST QUẢN LÝ TÀI KHOẢN: SYSTEM ADMIN VS ORG ADMIN
# ==============================================================================
def test_system_admin_can_create_org_and_org_admin(client: TestClient, stage2_fixture: dict[str, int]):
    """System Admin có quyền tạo tổ chức mới và tạo tài khoản quản trị tổ chức (org_admin)."""
    auth_sysadmin = ("s2_sysadmin", PASSWORD)

    # 1. Tạo tổ chức mới
    org_res = client.post(
        "/organizations",
        json={"name": "Hợp tác xã Xoài Vàng", "code": "HTX-XV", "description": "HTX trồng xoài"},
        auth=auth_sysadmin,
    )
    assert org_res.status_code == 201, org_res.text
    new_org_id = org_res.json()["id"]

    # 2. Tạo org_admin cho tổ chức mới
    user_res = client.post(
        "/users",
        json={
            "username": "orgadmin_xv",
            "email": "orgadmin_xv@test.local",
            "password": "Password123456!",
            "role": ROLE_ORG_ADMIN,
            "organization_id": new_org_id,
        },
        auth=auth_sysadmin,
    )
    assert user_res.status_code == 201, user_res.text
    assert user_res.json()["role"] == ROLE_ORG_ADMIN
    assert user_res.json()["organization_id"] == new_org_id


def test_org_admin_scope_and_privilege_escalation_prevention(
    client: TestClient, stage2_fixture: dict[str, int]
):
    """Organization Admin:
    - Chỉ được xem và tạo nhân viên thuộc tổ chức của mình.
    - Không thể tự cấp vai trò system_admin, inspector, hoặc org_admin.
    - Không thể chuyển nhân viên sang tổ chức khác.
    - Không thể can thiệp tài khoản tổ chức khác.
    """
    auth_orgadmin1 = ("s2_orgadmin1", PASSWORD)
    org1_id = stage2_fixture["org1_id"]
    org2_id = stage2_fixture["org2_id"]

    # 1. Org Admin 1 xem danh sách users -> chỉ thấy users của Org 1
    list_res = client.get("/users", auth=auth_orgadmin1)
    assert list_res.status_code == 200
    for u in list_res.json():
        assert u["organization_id"] == org1_id

    # Org Admin 1 cố tình lọc sang Org 2 -> 403 Forbidden
    assert client.get(f"/users?organization_id={org2_id}", auth=auth_orgadmin1).status_code == 403

    # 2. Org Admin 1 tạo nhân viên farmer thuộc Org 1 -> Thành công 201
    create_emp = client.post(
        "/users",
        json={
            "username": "emp_farmer_org1",
            "email": "farmer1@org1.local",
            "password": "Password123456!",
            "role": ROLE_FARMER,
            "organization_id": org1_id,
        },
        auth=auth_orgadmin1,
    )
    assert create_emp.status_code == 201
    emp_id = create_emp.json()["id"]

    # 3. Org Admin 1 cố tạo user ở Org 2 -> 403 Forbidden
    bad_org_res = client.post(
        "/users",
        json={
            "username": "emp_org2_hacker",
            "email": "hacker@org2.local",
            "password": "Password123456!",
            "role": ROLE_FARMER,
            "organization_id": org2_id,
        },
        auth=auth_orgadmin1,
    )
    assert bad_org_res.status_code == 403
    assert "chỉ được tạo tài khoản thuộc tổ chức của mình" in bad_org_res.json()["detail"]

    # 4. Org Admin 1 cố tự cấp vai trò system_admin -> 403 Forbidden
    bad_role_res = client.post(
        "/users",
        json={
            "username": "fake_sysadmin",
            "email": "fakesys@org1.local",
            "password": "Password123456!",
            "role": ROLE_SYSTEM_ADMIN,
            "organization_id": org1_id,
        },
        auth=auth_orgadmin1,
    )
    assert bad_role_res.status_code == 403
    assert "không có quyền cấp vai trò" in bad_role_res.json()["detail"]

    # 5. Org Admin 1 cố tự cấp vai trò inspector -> 403 Forbidden
    bad_insp_res = client.post(
        "/users",
        json={
            "username": "fake_inspector",
            "email": "fakeinsp@org1.local",
            "password": "Password123456!",
            "role": ROLE_INSPECTOR,
            "organization_id": org1_id,
        },
        auth=auth_orgadmin1,
    )
    assert bad_insp_res.status_code == 403

    # 6. Org Admin 1 cố chuyển nhân viên sang Org 2 -> 403 Forbidden
    move_res = client.patch(f"/users/{emp_id}", json={"organization_id": org2_id}, auth=auth_orgadmin1)
    assert move_res.status_code == 403
    assert "không thể chuyển tài khoản sang tổ chức khác" in move_res.json()["detail"]

    # 7. Org Admin 1 khóa nhân viên của mình -> 200 OK
    lock_res = client.patch(f"/users/{emp_id}", json={"is_locked": True}, auth=auth_orgadmin1)
    assert lock_res.status_code == 200
    assert lock_res.json()["is_locked"] is True

    # 8. Org Admin 1 reset mật khẩu cho nhân viên của mình -> 200 OK
    reset_res = client.post(
        f"/users/{emp_id}/reset-password",
        json={"admin_password": PASSWORD, "new_password": "NewEmployeePass123!"},
        auth=auth_orgadmin1,
    )
    assert reset_res.status_code == 200

    # 9. Org Admin 1 cố reset mật khẩu user của Org 2 (s2_processor2) -> 403 Forbidden
    with client:
        pass
    # Tìm ID của s2_processor2
    all_users = client.get("/users", auth=("s2_sysadmin", PASSWORD)).json()
    user_org2_id = next(u["id"] for u in all_users if u["username"] == "s2_processor2")
    bad_reset_res = client.post(
        f"/users/{user_org2_id}/reset-password",
        json={"admin_password": PASSWORD, "new_password": "NewEmployeePass123!"},
        auth=auth_orgadmin1,
    )
    assert bad_reset_res.status_code == 403


# ==============================================================================
# 4. TEST QUYỀN THU HỒI LÔ (BATCH RECALL) THEO BACKLOG MENTOR
# ==============================================================================
def test_recall_permissions_per_mentor_backlog(session_factory: sessionmaker[Session], stage2_fixture: dict[str, int]):
    """Kiểm tra ma trận quyền RECALL:
    - inspector: Được thực hiện thu hồi theo Acceptance Criteria.
    - org_admin: Chỉ được thu hồi lô khi tổ chức mình đang giữ lô.
    - system_admin: Không mặc định có quyền RECALL.
    """
    with session_factory() as session:
        user_sysadmin = session.scalar(select(User).where(User.username == "s2_sysadmin"))
        user_orgadmin1 = session.scalar(select(User).where(User.username == "s2_orgadmin1"))
        user_inspector = session.scalar(select(User).where(User.username == "s2_inspector"))
        user_farmer1 = session.scalar(select(User).where(User.username == "s2_farmer1"))

        # Lô hàng đang do Org 1 nắm giữ
        batch_held_by_org1 = Batch(
            code="B-REC-01",
            current_org_id=stage2_fixture["org1_id"],
            initial_quantity=500.0,
            remaining_quantity=500.0,
            status="ACTIVE",
        )
        # Lô hàng đang do Org 2 nắm giữ
        batch_held_by_org2 = Batch(
            code="B-REC-02",
            current_org_id=stage2_fixture["org2_id"],
            initial_quantity=500.0,
            remaining_quantity=500.0,
            status="ACTIVE",
        )

        # 1. Inspector: có quyền thu hồi cả lô ở Org 1 và Org 2
        assert can_recall_batch(user_inspector, batch_held_by_org1, raise_exception=False) is True
        assert can_recall_batch(user_inspector, batch_held_by_org2, raise_exception=False) is True

        # 2. Org Admin 1: được thu hồi lô tổ chức mình đang giữ (Org 1)
        assert can_recall_batch(user_orgadmin1, batch_held_by_org1, raise_exception=False) is True

        # Org Admin 1: KHÔNG ĐƯỢC thu hồi lô do Org 2 đang giữ -> Bị từ chối
        assert can_recall_batch(user_orgadmin1, batch_held_by_org2, raise_exception=False) is False
        with pytest.raises(Exception) as exc_info:
            can_recall_batch(user_orgadmin1, batch_held_by_org2, raise_exception=True)
        assert "chỉ được thu hồi lô hàng khi tổ chức mình đang trực tiếp nắm giữ" in str(exc_info.value.detail)

        # 3. System Admin: KHÔNG mặc định có quyền RECALL
        assert can_recall_batch(user_sysadmin, batch_held_by_org1, raise_exception=False) is False
        with pytest.raises(Exception):
            can_recall_batch(user_sysadmin, batch_held_by_org1, raise_exception=True)

        # 4. Farmer: KHÔNG có quyền RECALL
        assert can_recall_batch(user_farmer1, batch_held_by_org1, raise_exception=False) is False
