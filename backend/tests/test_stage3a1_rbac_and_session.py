"""Kiểm thử Giai đoạn 3A.1: Đồng bộ giao diện RBAC và Xử lý Session.

Bao quát:
1. Farmer: Có quyền thu hoạch (HARVEST), không có quyền gộp (MERGE -> 403).
2. Processor: Có quyền gộp (MERGE), không có quyền thu hoạch (HARVEST -> 403).
3. Distributor: Không có quyền thu hoạch (HARVEST -> 403), không có quyền gộp (MERGE -> 403).
4. Inspector: Đọc được audit log (200), không có quyền thu hoạch/tạo vùng trồng (403).
5. System Admin: Không có quyền thao tác nghiệp vụ thu hoạch (HARVEST -> 403), gộp (MERGE -> 403).
6. Xử lý HTTP 401 khi session hết hạn: Trả về 401, frontend thu hồi session và thông báo tiếng Việt.
7. Xử lý HTTP 403 khi bị từ chối quyền: Trả về 403, không làm mất session đăng nhập.
"""

from datetime import date
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    ROLE_DISTRIBUTOR,
    ROLE_FARMER,
    ROLE_INSPECTOR,
    ROLE_ORG_ADMIN,
    ROLE_PROCESSOR,
    ROLE_SYSTEM_ADMIN,
    Batch,
    Farm,
    Organization,
    Plot,
    Product,
    User,
)
from app.security import hash_password
from app.services.session_store import CSRF_HEADER_NAME, SESSION_COOKIE_NAME

PASSWORD = "SecurePassword123!"


@pytest.fixture()
def stage3a1_fixture(session_factory: sessionmaker[Session]) -> dict[str, int]:
    """Khởi tạo các tổ chức và người dùng đại diện 7 vai trò cho Stage 3A.1."""
    with session_factory() as session:
        org_farm = Organization(code="S3A-FARM", name="Hợp tác xã Nông trại S3A")
        org_proc = Organization(code="S3A-PROC", name="Nhà máy Chế biến S3A")
        org_dist = Organization(code="S3A-DIST", name="Công ty Phân phối S3A")
        session.add_all([org_farm, org_proc, org_dist])
        session.flush()

        u_farmer = User(
            username="s3a_farmer",
            email="farmer@s3a.local",
            role=ROLE_FARMER,
            organization_id=org_farm.id,
            password=hash_password(PASSWORD),
        )
        u_proc = User(
            username="s3a_proc",
            email="proc@s3a.local",
            role=ROLE_PROCESSOR,
            organization_id=org_proc.id,
            password=hash_password(PASSWORD),
        )
        u_dist = User(
            username="s3a_dist",
            email="dist@s3a.local",
            role=ROLE_DISTRIBUTOR,
            organization_id=org_dist.id,
            password=hash_password(PASSWORD),
        )
        u_inspector = User(
            username="s3a_inspector",
            email="inspector@s3a.local",
            role=ROLE_INSPECTOR,
            organization_id=None,
            password=hash_password(PASSWORD),
        )
        u_sysadmin = User(
            username="s3a_sysadmin",
            email="sysadmin@s3a.local",
            role=ROLE_SYSTEM_ADMIN,
            organization_id=None,
            password=hash_password(PASSWORD),
        )
        u_orgadmin = User(
            username="s3a_orgadmin",
            email="orgadmin@s3a.local",
            role=ROLE_ORG_ADMIN,
            organization_id=org_farm.id,
            password=hash_password(PASSWORD),
        )
        session.add_all([u_farmer, u_proc, u_dist, u_inspector, u_sysadmin, u_orgadmin])
        session.flush()

        prod = Product(name="S3A Xoài Cát Chu", unit="kg")
        session.add(prod)
        session.flush()

        farm = Farm(name="Vùng trồng Xoài Cao Lãnh", location="Đồng Tháp", area=3.0, owner="Nông dân Ba", organization_id=org_farm.id)
        session.add(farm)
        session.flush()

        plot = Plot(name="Thửa 1 - Vườn Xoài", location="Đồng Tháp", area=3.0, owner="Nông dân Ba", organization_id=org_farm.id)
        session.add(plot)
        session.flush()

        b1 = Batch(
            code="S3AB01",
            plot_id=plot.id,
            farm_id=farm.id,
            product_id=prod.id,
            product_name=prod.name,
            harvest_date=date.today(),
            initial_quantity=Decimal("100.00"),
            remaining_quantity=Decimal("100.00"),
            current_org_id=org_farm.id,
            status="ACTIVE",
        )
        b2 = Batch(
            code="S3AB02",
            plot_id=plot.id,
            farm_id=farm.id,
            product_id=prod.id,
            product_name=prod.name,
            harvest_date=date.today(),
            initial_quantity=Decimal("100.00"),
            remaining_quantity=Decimal("100.00"),
            current_org_id=org_proc.id,
            status="ACTIVE",
        )
        b3 = Batch(
            code="S3AB03",
            plot_id=plot.id,
            farm_id=farm.id,
            product_id=prod.id,
            product_name=prod.name,
            harvest_date=date.today(),
            initial_quantity=Decimal("100.00"),
            remaining_quantity=Decimal("100.00"),
            current_org_id=org_proc.id,
            status="ACTIVE",
        )
        session.add_all([b1, b2, b3])
        session.commit()

        return {
            "org_farm_id": org_farm.id,
            "org_proc_id": org_proc.id,
            "org_dist_id": org_dist.id,
            "prod_id": prod.id,
            "plot_id": plot.id,
            "farm_id": farm.id,
            "b1_id": b1.id,
            "b2_id": b2.id,
            "b3_id": b3.id,
        }


def login_helper(client: TestClient, username: str) -> dict[str, str]:
    """Helper đăng nhập lưu session vào TestClient và trả về CSRF headers."""
    res = client.post("/auth/login", json={"username": username, "password": PASSWORD})
    assert res.status_code == 200, f"Đăng nhập thất bại: {res.text}"
    csrf = res.json().get("csrf_token")
    return {CSRF_HEADER_NAME: csrf} if csrf else {}


# ==============================================================================
# 1. FARMER: Có quyền thu hoạch, bị chặn Gộp lô (MERGE -> 403)
# ==============================================================================
def test_farmer_harvest_allowed_but_merge_forbidden(client: TestClient, stage3a1_fixture: dict):
    headers = login_helper(client, "s3a_farmer")
    plot_id = stage3a1_fixture["plot_id"]
    prod_id = stage3a1_fixture["prod_id"]
    b1_id = stage3a1_fixture["b1_id"]

    # 1. Thu hoạch hợp lệ -> HTTP 201
    res_harvest = client.post(
        "/batches",
        json={
            "plot_id": plot_id,
            "product_id": prod_id,
            "initial_quantity": 50.0,
            "harvest_date": str(date.today()),
        },
        headers=headers,
    )
    assert res_harvest.status_code == 201

    # 2. Cố tình gọi API Gộp lô (MERGE) -> Bị chặn HTTP 403 Forbidden
    res_merge = client.post(
        "/batches/merge",
        json={
            "product_id": prod_id,
            "items": [
                {"parent_batch_id": b1_id, "quantity": 10.0},
                {"parent_batch_id": b1_id, "quantity": 10.0},
            ],
        },
        headers=headers,
    )
    assert res_merge.status_code == 403


# ==============================================================================
# 2. PROCESSOR: Có quyền gộp lô (MERGE), bị chặn thu hoạch (HARVEST -> 403)
# ==============================================================================
def test_processor_merge_allowed_but_harvest_forbidden(client: TestClient, stage3a1_fixture: dict):
    headers = login_helper(client, "s3a_proc")
    plot_id = stage3a1_fixture["plot_id"]
    prod_id = stage3a1_fixture["prod_id"]
    b2_id = stage3a1_fixture["b2_id"]
    b3_id = stage3a1_fixture["b3_id"]

    # 1. Cố tình gọi API Thu hoạch -> Bị chặn HTTP 403 Forbidden
    res_harvest = client.post(
        "/batches",
        json={
            "plot_id": plot_id,
            "product_id": prod_id,
            "initial_quantity": 50.0,
            "harvest_date": str(date.today()),
        },
        headers=headers,
    )
    assert res_harvest.status_code == 403

    # 2. Gọi API Gộp lô do mình nắm giữ -> HTTP 201
    res_merge = client.post(
        "/batches/merge",
        json={
            "product_id": prod_id,
            "items": [
                {"parent_batch_id": b2_id, "quantity": 10.0},
                {"parent_batch_id": b3_id, "quantity": 10.0},
            ],
        },
        headers=headers,
    )
    assert res_merge.status_code == 201


# ==============================================================================
# 3. DISTRIBUTOR: Không có quyền HARVEST và không có quyền MERGE -> 403
# ==============================================================================
def test_distributor_harvest_and_merge_forbidden(client: TestClient, stage3a1_fixture: dict):
    headers = login_helper(client, "s3a_dist")
    plot_id = stage3a1_fixture["plot_id"]
    prod_id = stage3a1_fixture["prod_id"]
    b2_id = stage3a1_fixture["b2_id"]

    # 1. Cố tình Thu hoạch -> 403
    res_harvest = client.post(
        "/batches",
        json={
            "plot_id": plot_id,
            "product_id": prod_id,
            "initial_quantity": 50.0,
            "harvest_date": str(date.today()),
        },
        headers=headers,
    )
    assert res_harvest.status_code == 403

    # 2. Cố tình Gộp lô -> 403
    res_merge = client.post(
        "/batches/merge",
        json={
            "product_id": prod_id,
            "items": [
                {"parent_batch_id": b2_id, "quantity": 10.0},
                {"parent_batch_id": b2_id, "quantity": 10.0},
            ],
        },
        headers=headers,
    )
    assert res_merge.status_code == 403


# ==============================================================================
# 4. INSPECTOR: Xem được audit log (200), không có quyền thao tác nghiệp vụ (403)
# ==============================================================================
def test_inspector_can_view_audit_but_cannot_perform_operations(client: TestClient, stage3a1_fixture: dict):
    headers = login_helper(client, "s3a_inspector")
    plot_id = stage3a1_fixture["plot_id"]
    prod_id = stage3a1_fixture["prod_id"]

    # 1. Xem audit log -> HTTP 200 OK
    res_audit = client.get("/audit-logs", headers=headers)
    assert res_audit.status_code == 200

    # 2. Cố tình Thu hoạch -> 403
    res_harvest = client.post(
        "/batches",
        json={
            "plot_id": plot_id,
            "product_id": prod_id,
            "initial_quantity": 50.0,
            "harvest_date": str(date.today()),
        },
        headers=headers,
    )
    assert res_harvest.status_code == 403

    # 3. Cố tình Tạo thửa đất -> 403
    res_farm = client.post(
        "/farms",
        json={
            "name": "Thửa đất trái phép",
            "location": "Vị trí",
            "area": 2.0,
            "owner": "Chủ đất",
        },
        headers=headers,
    )
    assert res_farm.status_code == 403


# ==============================================================================
# 5. SYSTEM ADMIN: Không có quyền HARVEST và MERGE -> 403
# ==============================================================================
def test_system_admin_operational_actions_forbidden(client: TestClient, stage3a1_fixture: dict):
    headers = login_helper(client, "s3a_sysadmin")
    plot_id = stage3a1_fixture["plot_id"]
    prod_id = stage3a1_fixture["prod_id"]
    b2_id = stage3a1_fixture["b2_id"]

    # 1. Cố tình Thu hoạch -> 403
    res_harvest = client.post(
        "/batches",
        json={
            "plot_id": plot_id,
            "product_id": prod_id,
            "initial_quantity": 50.0,
            "harvest_date": str(date.today()),
        },
        headers=headers,
    )
    assert res_harvest.status_code == 403

    # 2. Cố tình Gộp lô -> 403
    res_merge = client.post(
        "/batches/merge",
        json={
            "product_id": prod_id,
            "items": [
                {"parent_batch_id": b2_id, "quantity": 10.0},
                {"parent_batch_id": b2_id, "quantity": 10.0},
            ],
        },
        headers=headers,
    )
    assert res_merge.status_code == 403


# ==============================================================================
# 6. HTTP 401 khi session hết hạn hoặc không hợp lệ
# ==============================================================================
def test_session_expired_returns_401(client: TestClient):
    # Gửi request với session cookie giả mạo / đã hết hạn
    client.cookies.set(SESSION_COOKIE_NAME, "expired_or_fake_token_value")
    res = client.get("/batches")
    assert res.status_code == 401


# ==============================================================================
# 7. HTTP 403 khi bị từ chối quyền KHÔNG làm mất session
# ==============================================================================
def test_forbidden_403_retains_valid_session(client: TestClient, stage3a1_fixture: dict):
    headers = login_helper(client, "s3a_farmer")
    prod_id = stage3a1_fixture["prod_id"]
    b1_id = stage3a1_fixture["b1_id"]

    # 1. Thao tác trái quyền -> 403
    res_403 = client.post(
        "/batches/merge",
        json={
            "product_id": prod_id,
            "items": [
                {"parent_batch_id": b1_id, "quantity": 10.0},
                {"parent_batch_id": b1_id, "quantity": 10.0},
            ],
        },
        headers=headers,
    )
    assert res_403.status_code == 403

    # 2. Gọi tiếp một API hợp lệ -> Vẫn 200 OK bình thường (session không bị mất)
    res_200 = client.get("/batches", headers=headers)
    assert res_200.status_code == 200
    assert len(res_200.json()) >= 1
