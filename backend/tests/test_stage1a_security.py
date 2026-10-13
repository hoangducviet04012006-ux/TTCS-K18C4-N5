"""Kiểm thử bổ sung cho Giai đoạn 1A: Vá bảo mật và phân quyền mặc định từ chối (Deny by Default).

Chứng minh:
1. Người dùng không thuộc tổ chức không được tự động xem toàn bộ dữ liệu.
2. Người dùng không có quyền không được xóa hoặc can thiệp lô của tổ chức khác.
3. Các tài khoản hợp lệ vẫn thực hiện đầy đủ các nghiệp vụ được phép.
"""

from datetime import date
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    ROLE_ADMIN,
    ROLE_FARMER,
    Batch,
    Farm,
    Organization,
    Product,
    User,
)
from app.security import hash_password

PASSWORD = "test-password-123"


@pytest.fixture()
def stage1a_setup(session_factory: sessionmaker[Session]) -> dict[str, int]:
    """Tạo 2 tổ chức, 1 user không tổ chức, 1 admin không tổ chức, và các tài khoản hợp lệ."""
    with session_factory() as session:
        # Tổ chức 1: HTX Đồng Tháp
        org_1 = session.scalar(select(Organization).where(Organization.code == "ORG-1"))
        if not org_1:
            org_1 = Organization(code="ORG-1", name="Hợp tác xã 1", description="Org 1")
            session.add(org_1)
            session.flush()

        # Tổ chức 2: HTX Tiền Giang
        org_2 = session.scalar(select(Organization).where(Organization.code == "ORG-2"))
        if not org_2:
            org_2 = Organization(code="ORG-2", name="Hợp tác xã 2", description="Org 2")
            session.add(org_2)
            session.flush()

        # Sản phẩm dùng chung
        prod = session.scalar(select(Product).where(Product.name == "Xoài Cát Chu Test"))
        if not prod:
            prod = Product(name="Xoài Cát Chu Test", unit="kg")
            session.add(prod)
            session.flush()

        # Trang trại của Org 1
        farm_1 = Farm(
            name="Nông trại Org 1",
            location="Đồng Tháp",
            area=5.0,
            owner="HTX 1",
            coordinates="10.1, 105.1",
            organization_id=org_1.id,
        )
        session.add(farm_1)
        session.flush()

        # Trang trại của Org 2
        farm_2 = Farm(
            name="Nông trại Org 2",
            location="Tiền Giang",
            area=3.0,
            owner="HTX 2",
            coordinates="10.2, 105.2",
            organization_id=org_2.id,
        )
        session.add(farm_2)
        session.flush()

        # Lô nông sản của Org 2
        batch_2 = Batch(
            code="BATCH-ORG2-001",
            plot_id=farm_2.id,
            farm_id=farm_2.id,
            product_id=prod.id,
            product_name=prod.name,
            harvest_date=date(2026, 10, 1),
            initial_quantity=1000.0,
            remaining_quantity=1000.0,
            quantity=1000.0,
            current_org_id=org_2.id,
            status="ACTIVE",
        )
        session.add(batch_2)
        session.flush()

        # Tạo các tài khoản kiểm thử
        users_data = [
            ("farmer_org1", ROLE_FARMER, org_1.id),
            ("admin_org1", ROLE_ADMIN, org_1.id),
            ("farmer_org2", ROLE_FARMER, org_2.id),
            ("admin_org2", ROLE_ADMIN, org_2.id),
            ("user_no_org", ROLE_FARMER, None),
            ("admin_no_org", ROLE_ADMIN, None),
        ]
        for username, role, org_id in users_data:
            existing = session.scalar(select(User).where(User.username == username))
            if not existing:
                session.add(
                    User(
                        username=username,
                        email=f"{username}@test.local",
                        password=hash_password(PASSWORD),
                        role=role,
                        organization_id=org_id,
                    )
                )

        session.commit()
        return {
            "org1_id": org_1.id,
            "org2_id": org_2.id,
            "farm1_id": farm_1.id,
            "farm2_id": farm_2.id,
            "batch2_id": batch_2.id,
            "product_id": prod.id,
        }


def test_user_without_org_cannot_view_or_access_tenant_data(
    client: TestClient, stage1a_setup: dict[str, int]
):
    """Chứng minh: Người dùng không thuộc tổ chức không được tự động xem hay thao tác toàn bộ dữ liệu."""
    farm2_id = stage1a_setup["farm2_id"]
    batch2_id = stage1a_setup["batch2_id"]

    # 1. User không có tổ chức cố tình lấy danh sách vùng trồng
    res = client.get("/farms", auth=("user_no_org", PASSWORD))
    assert res.status_code == 403
    assert "chưa được liên kết với tổ chức" in res.json()["detail"]

    # 2. User không có tổ chức cố tình xem chi tiết vùng trồng của Org 2
    res = client.get(f"/farms/{farm2_id}", auth=("user_no_org", PASSWORD))
    assert res.status_code == 403

    # 3. User không có tổ chức cố tình lấy danh sách lô nông sản
    res = client.get("/batches", auth=("user_no_org", PASSWORD))
    assert res.status_code == 403
    assert "chưa được liên kết với tổ chức" in res.json()["detail"]

    # 4. User không có tổ chức cố tình xem chi tiết lô của Org 2
    res = client.get(f"/batches/{batch2_id}", auth=("user_no_org", PASSWORD))
    assert res.status_code == 403

    # 5. User không có tổ chức cố tình tạo vùng trồng mới
    res = client.post(
        "/farms",
        json={"name": "Farm Lậu", "location": "Vô định", "area": 1.0, "owner": "Ẩn danh"},
        auth=("user_no_org", PASSWORD),
    )
    assert res.status_code == 403


def test_unauthorized_user_cannot_delete_or_modify_other_org_batch(
    client: TestClient, stage1a_setup: dict[str, int]
):
    """Chứng minh: Người dùng không có quyền không được xóa hoặc can thiệp lô của tổ chức khác."""
    batch2_id = stage1a_setup["batch2_id"]

    # 1. Admin Org 1 cố xóa lô thuộc Org 2 -> Phải bị chặn 403
    res = client.delete(f"/batches/{batch2_id}", auth=("admin_org1", PASSWORD))
    assert res.status_code == 403
    assert "không có quyền xoá lô nông sản của tổ chức khác" in res.json()["detail"]

    # 2. Admin không thuộc tổ chức cố xóa lô thuộc Org 2 -> Phải bị chặn 403
    res = client.delete(f"/batches/{batch2_id}", auth=("admin_no_org", PASSWORD))
    assert res.status_code == 403
    assert "không có quyền xoá lô nông sản của tổ chức khác" in res.json()["detail"]

    # 3. Farmer Org 1 cố chỉnh sửa lô thuộc Org 2 -> Phải bị chặn 403
    res = client.put(
        f"/batches/{batch2_id}",
        json={"harvest_date": "2026-10-02", "initial_quantity": 500.0},
        auth=("farmer_org1", PASSWORD),
    )
    assert res.status_code == 403
    assert "không có quyền sửa lô nông sản của tổ chức khác" in res.json()["detail"]

    # 4. Farmer Org 1 cố tạo sự kiện bàn giao cho lô của Org 2 -> Phải bị chặn 403
    res = client.post(
        f"/batches/{batch2_id}/handover",
        json={"to_org_id": stage1a_setup["org1_id"], "note": "Bàn giao trái phép"},
        auth=("farmer_org1", PASSWORD),
    )
    assert res.status_code == 403


def test_valid_accounts_can_perform_allowed_business_operations(
    client: TestClient, stage1a_setup: dict[str, int]
):
    """Chứng minh: Các tài khoản hợp lệ vẫn thực hiện đầy đủ nghiệp vụ được phép."""
    farm1_id = stage1a_setup["farm1_id"]
    prod_id = stage1a_setup["product_id"]

    # 1. Farmer Org 1 xem danh sách vùng trồng của mình -> Thành công 200
    res = client.get("/farms", auth=("farmer_org1", PASSWORD))
    assert res.status_code == 200
    farms = res.json()
    assert len(farms) == 1
    assert farms[0]["name"] == "Nông trại Org 1"

    # 2. Farmer Org 1 tạo lô nông sản trên vùng trồng của mình -> Thành công 201
    res = client.post(
        "/batches",
        json={
            "farm_id": farm1_id,
            "product_id": prod_id,
            "initial_quantity": 500.0,
            "harvest_date": "2026-10-05",
        },
        auth=("farmer_org1", PASSWORD),
    )
    assert res.status_code == 201
    created_batch = res.json()
    created_id = created_batch["id"]
    assert created_batch["initial_quantity"] == 500.0

    # 3. Farmer Org 1 xem danh sách lô của mình -> Có lô vừa tạo
    res = client.get("/batches", auth=("farmer_org1", PASSWORD))
    assert res.status_code == 200
    batch_ids = [b["id"] for b in res.json()]
    assert created_id in batch_ids

    # 4. Admin Org 1 quản trị tài khoản hệ thống -> Thành công 200
    res = client.get("/users", auth=("admin_org1", PASSWORD))
    assert res.status_code == 200

    # 5. Admin Org 1 xem lịch sử audit log -> Thành công 200
    res = client.get("/audit-logs", auth=("admin_org1", PASSWORD))
    assert res.status_code == 200
