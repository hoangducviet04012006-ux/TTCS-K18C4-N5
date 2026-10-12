"""Regression tests cho các bản sửa lỗi phân quyền vai trò (Sprint 123 RBAC Fixes).

Bao gồm:
1. GET /events trả đầy đủ sự kiện cho Inspector (truyền user_role vào can_view_batch).
2. GET /api/batches/{id}/events cho phép Inspector đọc (200), giữ nguyên kiểm tra quyền với org khác (403) và chưa xác thực (401).
3. redact_event phân cấp quyền chính xác:
   - Cùng tổ chức: Xem toàn bộ.
   - Inspector & System Admin: Xem dữ liệu kỹ thuật, thanh tra (event_data, username, notes), ẩn PII/payload nhạy cảm.
   - Tổ chức khác: Ẩn theo whitelist public, event_data chung, ẩn username, notes.
4. GET /users: Org Admin chỉ được xem nhân viên tổ chức mình (403 nếu truy cập org khác), System Admin lọc toàn hệ thống.
"""

from decimal import Decimal
from datetime import date
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker, Session

from app.models import (
    ROLE_SYSTEM_ADMIN,
    ROLE_ORG_ADMIN,
    ROLE_FARMER,
    ROLE_PROCESSOR,
    ROLE_INSPECTOR,
    Batch,
    BatchEvent,
    Plot,
    Organization,
    Product,
    User,
)
from app.security import hash_password

PASSWORD = "TestPassword123!"


@pytest.fixture()
def rbac_fixture(session_factory: sessionmaker[Session]):
    """Chuẩn bị 2 tổ chức, sản phẩm, thửa đất, 2 lô và các tài khoản thuộc các vai trò."""
    with session_factory() as session:
        org_a = Organization(id=10, name="Hợp tác xã Farm A", code="HTX-A", description="Org A")
        org_b = Organization(id=20, name="Công ty Chế biến B", code="CT-B", description="Org B")
        session.add_all([org_a, org_b])
        session.flush()

        farmer_a = User(
            username="farmer_a",
            email="farmer_a@test.vn",
            password=hash_password(PASSWORD),
            role=ROLE_FARMER,
            organization_id=org_a.id,
            is_active=True,
        )
        org_admin_a = User(
            username="org_admin_a",
            email="org_admin_a@test.vn",
            password=hash_password(PASSWORD),
            role=ROLE_ORG_ADMIN,
            organization_id=org_a.id,
            is_active=True,
        )
        processor_b = User(
            username="proc_b",
            email="proc_b@test.vn",
            password=hash_password(PASSWORD),
            role=ROLE_PROCESSOR,
            organization_id=org_b.id,
            is_active=True,
        )
        inspector_user = User(
            username="insp_test",
            email="insp@test.vn",
            password=hash_password(PASSWORD),
            role=ROLE_INSPECTOR,
            organization_id=None,
            is_active=True,
        )
        sys_admin_user = User(
            username="sys_admin_test",
            email="sysadmin@test.vn",
            password=hash_password(PASSWORD),
            role=ROLE_SYSTEM_ADMIN,
            organization_id=None,
            is_active=True,
        )
        session.add_all([farmer_a, org_admin_a, processor_b, inspector_user, sys_admin_user])
        session.flush()

        plot_a = Plot(id=10, organization_id=org_a.id, name="Vườn A", location="Đồng Tháp", area=1.5, owner="Nguyễn Văn A")
        prod = Product(id=10, name="Xoài Cát Chu", unit="kg")
        session.add_all([plot_a, prod])
        session.flush()

        batch_a = Batch(
            id=101,
            code="BATCH-A-01",
            plot_id=plot_a.id,
            product_id=prod.id,
            initial_quantity=Decimal("100.0"),
            remaining_quantity=Decimal("100.0"),
            harvest_date=date(2026, 3, 1),
            status="ACTIVE",
            current_org_id=org_a.id,
        )
        batch_b = Batch(
            id=102,
            code="BATCH-B-01",
            plot_id=plot_a.id,
            product_id=prod.id,
            initial_quantity=Decimal("50.0"),
            remaining_quantity=Decimal("50.0"),
            harvest_date=date(2026, 3, 2),
            status="ACTIVE",
            current_org_id=org_b.id,
        )
        session.add_all([batch_a, batch_b])
        session.flush()

        # Tạo sự kiện cho lô A với thông tin kỹ thuật và thông tin nhạy cảm/PII
        event_a = BatchEvent(
            id=1001,
            batch_id=batch_a.id,
            organization_id=org_a.id,
            created_by_user_id=farmer_a.id,
            event_type="HARVEST",
            event_data="Thu hoạch đợt 1 tại vườn A",
            payload={
                "batch_code": "BATCH-A-01",
                "quantity": 100.0,
                "temperature": 18.5,
                "humidity": 75.0,
                "driver_phone": "0912345678",
                "id_card": "079123456789",
                "bank_account": "9999888877",
                "price": 25000000,
                "email": "driver@farm-a.vn",
            },
            notes="Kiểm tra chất lượng ban đầu tốt",
            prev_hash="0" * 64,
            current_hash="a" * 64,
        )
        # Tạo sự kiện cho lô B
        event_b = BatchEvent(
            id=1002,
            batch_id=batch_b.id,
            organization_id=org_b.id,
            created_by_user_id=processor_b.id,
            event_type="PROCESS_PACKAGE",
            event_data="Đóng gói xoài sấy B",
            payload={"batch_code": "BATCH-B-01", "quantity": 50.0, "clean_agent": "Ozone"},
            notes="Đạt tiêu chuẩn xuất khẩu",
            prev_hash="0" * 64,
            current_hash="b" * 64,
        )
        session.add_all([event_a, event_b])
        session.commit()

        return {
            "org_a_id": org_a.id,
            "org_b_id": org_b.id,
            "batch_a_id": batch_a.id,
            "batch_b_id": batch_b.id,
            "event_a_id": event_a.id,
            "event_b_id": event_b.id,
            "farmer_a_auth": ("farmer_a", PASSWORD),
            "org_admin_a_auth": ("org_admin_a", PASSWORD),
            "proc_b_auth": ("proc_b", PASSWORD),
            "insp_auth": ("insp_test", PASSWORD),
            "sys_admin_auth": ("sys_admin_test", PASSWORD),
        }


def test_inspector_can_view_all_events_via_get_events(client: TestClient, rbac_fixture):
    """Lỗi 1: GET /events không trả sự kiện cho Inspector do thiếu user_role trong can_view_batch."""
    insp_auth = rbac_fixture["insp_auth"]
    farmer_a_auth = rbac_fixture["farmer_a_auth"]

    # Inspector gọi GET /events -> Phải thấy sự kiện của cả 2 lô thuộc 2 tổ chức khác nhau
    resp = client.get("/events", auth=insp_auth)
    assert resp.status_code == 200
    events = resp.json()
    batch_ids = {e["batch_id"] for e in events}
    assert rbac_fixture["batch_a_id"] in batch_ids
    assert rbac_fixture["batch_b_id"] in batch_ids

    # Farmer Org A chỉ thấy sự kiện thuộc lô của tổ chức mình
    resp_farmer = client.get("/events", auth=farmer_a_auth)
    assert resp_farmer.status_code == 200
    farmer_batch_ids = {e["batch_id"] for e in resp_farmer.json()}
    assert rbac_fixture["batch_a_id"] in farmer_batch_ids
    assert rbac_fixture["batch_b_id"] not in farmer_batch_ids


def test_inspector_legacy_batch_events_api_dependency(client: TestClient, rbac_fixture):
    """Lỗi 2: GET /api/batches/{id}/events cho phép Inspector đọc, bảo lưu 403 cho org khác và 401 unauthenticated."""
    insp_auth = rbac_fixture["insp_auth"]
    proc_b_auth = rbac_fixture["proc_b_auth"]
    farmer_a_auth = rbac_fixture["farmer_a_auth"]
    batch_a_id = rbac_fixture["batch_a_id"]

    # 1. Inspector đọc thành công (200)
    resp_insp = client.get(f"/api/batches/{batch_a_id}/events", auth=insp_auth)
    assert resp_insp.status_code == 200
    assert len(resp_insp.json()) >= 1

    # 2. Thành viên tổ chức sở hữu đọc thành công (200)
    resp_owner = client.get(f"/api/batches/{batch_a_id}/events", auth=farmer_a_auth)
    assert resp_owner.status_code == 200

    # 3. Thành viên tổ chức khác không có quyền truy cập lô -> 403 Forbidden
    resp_forbidden = client.get(f"/api/batches/{batch_a_id}/events", auth=proc_b_auth)
    assert resp_forbidden.status_code == 403

    # 4. Chưa đăng nhập -> 401 Unauthorized
    resp_unauth = client.get(f"/api/batches/{batch_a_id}/events")
    assert resp_unauth.status_code == 401


def test_redact_event_three_tier_permissions(client: TestClient, rbac_fixture):
    """Lỗi 3: redact_event phân cấp quyền: cùng tổ chức, Inspector & System Admin, tổ chức khác."""
    batch_a_id = rbac_fixture["batch_a_id"]
    farmer_a_auth = rbac_fixture["farmer_a_auth"]
    insp_auth = rbac_fixture["insp_auth"]
    sys_admin_auth = rbac_fixture["sys_admin_auth"]

    # --- Trường hợp 1: Cùng tổ chức (Farmer A xem sự kiện của Org A) ---
    resp_a = client.get(f"/batches/{batch_a_id}/events", auth=farmer_a_auth)
    assert resp_a.status_code == 200
    ev_a = next(e for e in resp_a.json() if e["id"] == rbac_fixture["event_a_id"])

    # Dữ liệu nội bộ được giữ nguyên toàn bộ
    assert ev_a["event_data"] == "Thu hoạch đợt 1 tại vườn A"
    assert ev_a["username"] == "farmer_a"
    assert ev_a["notes"] == "Kiểm tra chất lượng ban đầu tốt"
    assert ev_a["payload"]["driver_phone"] == "0912345678"
    assert ev_a["payload"]["id_card"] == "079123456789"
    assert ev_a["payload"]["bank_account"] == "9999888877"
    assert ev_a["payload"]["price"] == 25000000
    assert ev_a["payload"]["email"] == "driver@farm-a.vn"
    assert ev_a["payload"]["temperature"] == 18.5
    assert ev_a["payload"]["humidity"] == 75.0

    # --- Trường hợp 2: Inspector xem sự kiện ---
    resp_insp = client.get(f"/batches/{batch_a_id}/events", auth=insp_auth)
    assert resp_insp.status_code == 200
    ev_insp = next(e for e in resp_insp.json() if e["id"] == rbac_fixture["event_a_id"])

    # Phục vụ thanh tra: giữ event_data, username, notes và thông số kỹ thuật
    assert ev_insp["event_data"] == "Thu hoạch đợt 1 tại vườn A"
    assert ev_insp["username"] == "farmer_a"
    assert ev_insp["notes"] == "Kiểm tra chất lượng ban đầu tốt"
    assert ev_insp["payload"]["temperature"] == 18.5
    assert ev_insp["payload"]["humidity"] == 75.0

    # PII và thông tin nhạy cảm phải bị loại bỏ
    assert "driver_phone" not in ev_insp["payload"]
    assert "id_card" not in ev_insp["payload"]
    assert "bank_account" not in ev_insp["payload"]
    assert "price" not in ev_insp["payload"]
    assert "email" not in ev_insp["payload"]

    # ID người dùng nội bộ phải bị ẩn
    assert ev_insp["created_by_user_id"] is None
    assert ev_insp["user_id"] is None

    # --- Trường hợp 3: System Admin xem sự kiện ---
    resp_admin = client.get(f"/batches/{batch_a_id}/events", auth=sys_admin_auth)
    assert resp_admin.status_code == 200
    ev_admin = next(e for e in resp_admin.json() if e["id"] == rbac_fixture["event_a_id"])
    assert ev_admin["event_data"] == "Thu hoạch đợt 1 tại vườn A"
    assert "driver_phone" not in ev_admin["payload"]
    assert ev_admin["payload"]["temperature"] == 18.5

    # --- Trường hợp 4: Tổ chức khác (liên tổ chức) sau khi nhận bàn giao ---
    # Org A bàn giao Lô A cho Org B, Org B chấp nhận -> Org B có quyền xem Lô A
    ho_resp = client.post(
        f"/batches/{batch_a_id}/handover",
        json={"to_org_id": rbac_fixture["org_b_id"]},
        auth=farmer_a_auth,
    )
    assert ho_resp.status_code == 201
    ho_id = ho_resp.json()["id"]
    accept_resp = client.post(f"/handovers/{ho_id}/accept", auth=rbac_fixture["proc_b_auth"])
    assert accept_resp.status_code == 200

    # Bây giờ Org B (proc_b) xem sự kiện ev_a (sự kiện do Org A tạo)
    resp_b = client.get(f"/batches/{batch_a_id}/events", auth=rbac_fixture["proc_b_auth"])
    assert resp_b.status_code == 200
    ev_b = next(e for e in resp_b.json() if e["id"] == rbac_fixture["event_a_id"])

    # Phải bị che giấu nghiêm ngặt theo Tier 3
    assert ev_b["event_data"] == "Thông tin truy xuất liên tổ chức"
    assert ev_b["username"] is None
    assert ev_b["notes"] is None
    assert ev_b["created_by_user_id"] is None
    # Payload chỉ giữ trường public (batch_code, quantity...), các trường kỹ thuật và PII bị ẩn
    assert "temperature" not in ev_b["payload"]
    assert "driver_phone" not in ev_b["payload"]
    assert "batch_code" in ev_b["payload"]
    assert ev_b["payload"]["quantity"] == 100.0


def test_user_org_filter_backend_permissions(client: TestClient, rbac_fixture):
    """Lỗi 4: Org Admin chỉ được xem/lọc người dùng thuộc tổ chức của mình (403 với org khác).

    System Admin được lọc toàn bộ hoặc theo bất kỳ tổ chức nào.
    """
    org_admin_auth = rbac_fixture["org_admin_a_auth"]
    sys_admin_auth = rbac_fixture["sys_admin_auth"]
    org_a_id = rbac_fixture["org_a_id"]
    org_b_id = rbac_fixture["org_b_id"]

    # 1. Org Admin xem danh sách mặc định -> Chỉ trả về người dùng thuộc Org A
    resp_org_admin = client.get("/users", auth=org_admin_auth)
    assert resp_org_admin.status_code == 200
    users_a = resp_org_admin.json()
    assert all(u["organization_id"] == org_a_id for u in users_a)
    assert any(u["username"] == "farmer_a" for u in users_a)
    assert not any(u["username"] == "proc_b" for u in users_a)

    # 2. Org Admin cố tình lọc organization_id của tổ chức B -> Bị 403 Forbidden
    resp_forbidden = client.get(f"/users?organization_id={org_b_id}", auth=org_admin_auth)
    assert resp_forbidden.status_code == 403

    # 3. System Admin xem toàn bộ -> Thấy cả người dùng của Org A và Org B
    resp_sys_all = client.get("/users", auth=sys_admin_auth)
    assert resp_sys_all.status_code == 200
    sys_usernames = {u["username"] for u in resp_sys_all.json()}
    assert "farmer_a" in sys_usernames
    assert "proc_b" in sys_usernames

    # 4. System Admin lọc theo tổ chức B -> Thấy người dùng Org B
    resp_sys_b = client.get(f"/users?organization_id={org_b_id}", auth=sys_admin_auth)
    assert resp_sys_b.status_code == 200
    assert all(u["organization_id"] == org_b_id for u in resp_sys_b.json())
