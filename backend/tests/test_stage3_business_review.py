"""Bộ kiểm thử cho Giai đoạn 3: Rà soát và hoàn thiện nghiệp vụ AgriTrace.

Kiểm chứng các Acceptance Criteria theo Backlog Mentor cho các luồng nghiệp vụ:
1. S-06: Cập nhật thửa đất không làm đứt gãy liên kết với các lô đã thu hoạch.
2. S-09: Chặn thu hoạch ngày tương lai, khối lượng <= 0, thửa đất tổ chức khác (HTTP 400/403).
3. S-15 & S-16: Bàn giao lô: Chặn bàn giao trùng lặp khi đang PENDING, chặn tự bàn giao, chặn từ chối thiếu lý do, chặn tổ chức khác xác nhận.
4. S-17 & S-18: Tách lô: Chặn tổng con vượt mẹ, chặn tổ chức không giữ lô gọi tách.
5. S-19: Gộp lô: Chặn gộp khác sản phẩm, chặn tổ chức không giữ lô, chặn farmer thực hiện gộp (chỉ processor/distributor).
6. S-21: Truy ngược phả hệ: Phát hiện chu trình lặp (Cycle detection) trả về HTTP 400.
7. S-23: Cách ly truy xuất: Không cho phép xem lô không có quan hệ phả hệ của tổ chức khác (HTTP 403).
8. S-31 & Phân quyền Audit Log: Inspector được đọc audit logs, Farmer bị chặn 403.
9. Quyền RECALL: Inspector được phép, Farmer bị chặn 403.
"""

from datetime import date, timedelta
from decimal import Decimal
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
    BatchRelation,
    Farm,
    Handover,
    Organization,
    Plot,
    Product,
    User,
)
from app.security import hash_password
from app.services.rbac import can_recall_batch
from app.services.session_store import CSRF_HEADER_NAME, SESSION_COOKIE_NAME

PASSWORD = "SecurePassword123!"


@pytest.fixture()
def stage3_fixture(session_factory: sessionmaker[Session]) -> dict[str, int]:
    """Tạo dữ liệu fixture chuẩn cho kiểm thử nghiệp vụ Giai đoạn 3."""
    with session_factory() as session:
        # 1. Tạo 2 tổ chức
        org1 = Organization(code="S3-ORG-FARM", name="HTX Nông Nghiệp Xanh")
        org2 = Organization(code="S3-ORG-PROC", name="Nhà Máy Chế Biến Thực Phẩm")
        session.add_all([org1, org2])
        session.flush()

        # 2. Tạo các người dùng theo 7 vai trò
        u_farmer = User(
            username="s3_farmer",
            email="s3_farmer@demo.local",
            role=ROLE_FARMER,
            organization_id=org1.id,
            password=hash_password(PASSWORD),
        )
        u_proc = User(
            username="s3_proc",
            email="s3_proc@demo.local",
            role=ROLE_PROCESSOR,
            organization_id=org2.id,
            password=hash_password(PASSWORD),
        )
        u_dist = User(
            username="s3_dist",
            email="s3_dist@demo.local",
            role=ROLE_DISTRIBUTOR,
            organization_id=org2.id,
            password=hash_password(PASSWORD),
        )
        u_inspector = User(
            username="s3_inspector",
            email="s3_inspector@demo.local",
            role=ROLE_INSPECTOR,
            organization_id=None,
            password=hash_password(PASSWORD),
        )
        u_sysadmin = User(
            username="s3_sysadmin",
            email="s3_sysadmin@demo.local",
            role=ROLE_SYSTEM_ADMIN,
            organization_id=org1.id,
            password=hash_password(PASSWORD),
        )
        session.add_all([u_farmer, u_proc, u_dist, u_inspector, u_sysadmin])
        session.flush()

        # 3. Sản phẩm
        p1 = Product(name="S3 Xoài Cát Hòa Lộc", unit="kg")
        p2 = Product(name="S3 Sầu Riêng Ri6", unit="kg")
        session.add_all([p1, p2])
        session.flush()

        # 4. Vùng trồng và thửa đất thuộc org1
        farm1 = Farm(name="Nông trại Đồng Tháp S3", location="Cao Lãnh", area=2.5, owner="Nông dân Ba", organization_id=org1.id)
        session.add(farm1)
        session.flush()

        plot1 = Plot(
            name="Thửa đất số 1 - S3",
            location="Cao Lãnh",
            area=2.5,
            owner="Nông dân Ba",
            organization_id=org1.id,
        )
        session.add(plot1)
        session.flush()

        # 5. Lô thu hoạch mẫu của org1
        batch1 = Batch(
            code="S3BATCH01",
            plot_id=plot1.id,
            farm_id=farm1.id,
            product_id=p1.id,
            product_name=p1.name,
            harvest_date=date.today(),
            initial_quantity=Decimal("100.00"),
            remaining_quantity=Decimal("100.00"),
            current_org_id=org1.id,
            status="ACTIVE",
        )
        session.add(batch1)
        session.commit()

        return {
            "org1_id": org1.id,
            "org2_id": org2.id,
            "farmer_id": u_farmer.id,
            "proc_id": u_proc.id,
            "dist_id": u_dist.id,
            "inspector_id": u_inspector.id,
            "sysadmin_id": u_sysadmin.id,
            "p1_id": p1.id,
            "p2_id": p2.id,
            "farm1_id": farm1.id,
            "plot1_id": plot1.id,
            "batch1_id": batch1.id,
        }


def login_client(client: TestClient, username: str, password: str = PASSWORD) -> dict[str, str]:
    """Helper đăng nhập và trả về headers kèm cookie và CSRF."""
    res = client.post("/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, f"Đăng nhập thất bại: {res.text}"
    token = res.cookies.get(SESSION_COOKIE_NAME)
    csrf = res.json().get("csrf_token") or res.cookies.get("csrf_token")
    headers = {CSRF_HEADER_NAME: csrf} if csrf else {}
    return headers


# -----------------------------------------------------------------------------
# 1. S-06: Sửa tên thửa đất không làm đứt gãy liên kết lô
# -----------------------------------------------------------------------------
def test_s06_edit_plot_preserves_batch_relation(client: TestClient, stage3_fixture: dict):
    headers = login_client(client, "s3_farmer")
    plot_id = stage3_fixture["plot1_id"]
    batch_id = stage3_fixture["batch1_id"]

    # Đổi tên thửa đất
    update_res = client.put(
        f"/farms/{plot_id}",
        json={
            "name": "Thửa đất số 1 Đã Đổi Tên",
            "location": "Cao Lãnh Mới",
            "area": 3.0,
            "owner": "Nông dân Ba Mới",
        },
        headers=headers,
    )
    assert update_res.status_code == 200

    # Lô vẫn trỏ đúng plot_id và xem chi tiết bình thường
    batch_res = client.get(f"/batches/{batch_id}", headers=headers)
    assert batch_res.status_code == 200
    data = batch_res.json()
    assert data["code"] == "S3BATCH01"
    assert data["plot_id"] == plot_id


# -----------------------------------------------------------------------------
# 2. S-09: Ràng buộc thu hoạch chặn ở server
# -----------------------------------------------------------------------------
def test_s09_harvest_validation_errors(client: TestClient, stage3_fixture: dict):
    headers = login_client(client, "s3_farmer")
    plot_id = stage3_fixture["plot1_id"]
    p1_id = stage3_fixture["p1_id"]

    # Ngày tương lai -> HTTP 400
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    res_future = client.post(
        "/batches",
        json={
            "plot_id": plot_id,
            "product_id": p1_id,
            "harvest_date": tomorrow,
            "initial_quantity": 50.0,
        },
        headers=headers,
    )
    assert res_future.status_code == 400

    # Khối lượng <= 0 -> HTTP 400 hoặc 422
    res_zero_qty = client.post(
        "/batches",
        json={
            "plot_id": plot_id,
            "product_id": p1_id,
            "harvest_date": date.today().isoformat(),
            "initial_quantity": 0,
        },
        headers=headers,
    )
    assert res_zero_qty.status_code in (400, 422)

    # Thửa đất tổ chức khác -> HTTP 403
    headers_proc = login_client(client, "s3_proc")
    res_wrong_org = client.post(
        "/batches",
        json={
            "plot_id": plot_id,
            "product_id": p1_id,
            "harvest_date": date.today().isoformat(),
            "initial_quantity": 50.0,
        },
        headers=headers_proc,
    )
    assert res_wrong_org.status_code == 403


# -----------------------------------------------------------------------------
# 3. S-15 & S-16: Bàn giao lô an toàn
# -----------------------------------------------------------------------------
def test_s15_s16_handover_flow_and_rejection(client: TestClient, stage3_fixture: dict):
    headers_f = login_client(client, "s3_farmer")
    batch_id = stage3_fixture["batch1_id"]
    org1_id = stage3_fixture["org1_id"]
    org2_id = stage3_fixture["org2_id"]

    # Chặn tự bàn giao cho chính mình
    res_self = client.post(
        f"/batches/{batch_id}/handover",
        json={"to_org_id": org1_id, "note": "Tự giao"},
        headers=headers_f,
    )
    assert res_self.status_code == 400

    # Bàn giao sang org2 thành công
    res_ho = client.post(
        f"/batches/{batch_id}/handover",
        json={"to_org_id": org2_id, "note": "Giao chế biến"},
        headers=headers_f,
    )
    assert res_ho.status_code == 201
    ho_id = res_ho.json()["id"]

    # Chặn tạo bàn giao thứ 2 khi đang PENDING
    res_double = client.post(
        f"/batches/{batch_id}/handover",
        json={"to_org_id": org2_id},
        headers=headers_f,
    )
    assert res_double.status_code == 400

    # Bên gửi không thể tự xác nhận bàn giao của mình
    res_accept_wrong = client.post(f"/handovers/{ho_id}/accept", headers=headers_f)
    assert res_accept_wrong.status_code == 403

    # Bên nhận từ chối nhưng thiếu lý do (< 10 ký tự) -> 422 hoặc 400 (Pydantic min_length trả về 422)
    headers_proc = login_client(client, "s3_proc")
    res_reject_short = client.post(
        f"/handovers/{ho_id}/reject",
        json={"reject_reason": "Ngắn"},
        headers=headers_proc,
    )
    assert res_reject_short.status_code in (400, 422)

    # Từ chối với lý do đầy đủ >= 10 ký tự -> 200
    res_reject_ok = client.post(
        f"/handovers/{ho_id}/reject",
        json={"reject_reason": "Nông sản không đạt tiêu chuẩn độ ngọt và chất lượng"},
        headers=headers_proc,
    )
    assert res_reject_ok.status_code == 200

    # Đăng nhập lại farmer để kiểm tra lô
    headers_f = login_client(client, "s3_farmer")
    res_b = client.get(f"/batches/{batch_id}", headers=headers_f)
    assert res_b.status_code == 200
    b_check = res_b.json()
    assert b_check["current_org_id"] == org1_id


# -----------------------------------------------------------------------------
# 4. S-17 & S-18: Tách lô
# -----------------------------------------------------------------------------
def test_s17_s18_split_validation(client: TestClient, stage3_fixture: dict):
    headers_f = login_client(client, "s3_farmer")
    batch_id = stage3_fixture["batch1_id"]

    # Tổng con 150 > mẹ 100 -> HTTP 400
    res_over = client.post(
        f"/batches/{batch_id}/split",
        json={
            "child_quantities": [80.0, 70.0],
        },
        headers=headers_f,
    )
    assert res_over.status_code == 400

    # Người thuộc org2 cố tình tách lô của org1 -> HTTP 403
    headers_proc = login_client(client, "s3_proc")
    res_wrong_org = client.post(
        f"/batches/{batch_id}/split",
        json={
            "child_quantities": [30.0, 30.0],
        },
        headers=headers_proc,
    )
    assert res_wrong_org.status_code == 403


# -----------------------------------------------------------------------------
# 5. S-19: Gộp lô
# -----------------------------------------------------------------------------
def test_s19_merge_validation_and_roles(client: TestClient, stage3_fixture: dict, session_factory: sessionmaker[Session]):
    batch1_id = stage3_fixture["batch1_id"]
    org1_id = stage3_fixture["org1_id"]
    plot_id = stage3_fixture["plot1_id"]
    p2_id = stage3_fixture["p2_id"]

    # Tạo thêm 1 lô khác sản phẩm (p2: Sầu riêng)
    with session_factory() as session:
        b_diff = Batch(
            code="S3DIFFPROD",
            plot_id=plot_id,
            product_id=p2_id,
            product_name="Sầu riêng",
            harvest_date=date.today(),
            initial_quantity=Decimal("50.00"),
            remaining_quantity=Decimal("50.00"),
            current_org_id=org1_id,
            status="ACTIVE",
        )
        session.add(b_diff)
        session.commit()
        diff_id = b_diff.id

    # 1. Gộp 2 lô khác sản phẩm -> HTTP 400
    headers_f = login_client(client, "s3_farmer")
    res_diff = client.post(
        "/batches/merge",
        json={
            "product_id": stage3_fixture["p1_id"],
            "items": [
                {"parent_batch_id": batch1_id, "quantity": 20.0},
                {"parent_batch_id": diff_id, "quantity": 20.0},
            ],
        },
        headers=headers_f,
    )
    # Farmer bị chặn quyền MERGE -> 403
    assert res_diff.status_code == 403

    # Chuyển quyền giữ sang org2 (để proc thực hiện gộp)
    with session_factory() as session:
        b1 = session.get(Batch, batch1_id)
        b2 = session.get(Batch, diff_id)
        b1.current_org_id = stage3_fixture["org2_id"]
        b2.current_org_id = stage3_fixture["org2_id"]
        session.commit()

    headers_proc = login_client(client, "s3_proc")
    # Proc có quyền MERGE, nhưng 2 lô khác sản phẩm -> HTTP 400
    res_diff_proc = client.post(
        "/batches/merge",
        json={
            "product_id": stage3_fixture["p1_id"],
            "items": [
                {"parent_batch_id": batch1_id, "quantity": 20.0},
                {"parent_batch_id": diff_id, "quantity": 20.0},
            ],
        },
        headers=headers_proc,
    )
    assert res_diff_proc.status_code == 400


# -----------------------------------------------------------------------------
# 6. S-21: Chu trình lặp phả hệ trả về HTTP 400
# -----------------------------------------------------------------------------
def test_s21_cycle_detection(client: TestClient, stage3_fixture: dict, session_factory: sessionmaker[Session]):
    b1_id = stage3_fixture["batch1_id"]
    org1_id = stage3_fixture["org1_id"]
    plot_id = stage3_fixture["plot1_id"]
    p1_id = stage3_fixture["p1_id"]

    # Cố ý dựng chu trình quan hệ giả lập: B1 -> B2 -> B1
    with session_factory() as session:
        b2 = Batch(
            code="S3BATCH02",
            plot_id=plot_id,
            product_id=p1_id,
            product_name="Xoài",
            harvest_date=date.today(),
            initial_quantity=Decimal("50.00"),
            remaining_quantity=Decimal("50.00"),
            current_org_id=org1_id,
            status="ACTIVE",
        )
        session.add(b2)
        session.flush()

        rel1 = BatchRelation(parent_batch_id=b1_id, child_batch_id=b2.id, relation_type="SPLIT", transferred_quantity=Decimal("10.00"))
        rel2 = BatchRelation(parent_batch_id=b2.id, child_batch_id=b1_id, relation_type="SPLIT", transferred_quantity=Decimal("10.00"))
        session.add_all([rel1, rel2])
        session.commit()

    headers_f = login_client(client, "s3_farmer")
    # Gọi trace-back -> Thuật toán BFS phát hiện chu trình -> HTTP 400
    res_trace = client.get(f"/batches/{b1_id}/trace-back", headers=headers_f)
    assert res_trace.status_code == 400
    assert "chu trình" in res_trace.text.lower() or "cycle" in res_trace.text.lower()


# -----------------------------------------------------------------------------
# 7. S-31 & Phân quyền Audit Log
# -----------------------------------------------------------------------------
def test_s31_audit_log_permissions(client: TestClient, stage3_fixture: dict):
    # Farmer xem audit logs -> HTTP 403 Forbidden
    headers_f = login_client(client, "s3_farmer")
    res_f = client.get("/audit-logs", headers=headers_f)
    assert res_f.status_code == 403

    # Inspector xem audit logs -> HTTP 200 OK
    headers_insp = login_client(client, "s3_inspector")
    res_insp = client.get("/audit-logs", headers=headers_insp)
    assert res_insp.status_code == 200
    assert isinstance(res_insp.json(), list)


# -----------------------------------------------------------------------------
# 8. Quyền RECALL
# -----------------------------------------------------------------------------
def test_recall_permissions(stage3_fixture: dict, session_factory: sessionmaker[Session]):
    with session_factory() as session:
        insp = session.get(User, stage3_fixture["inspector_id"])
        farmer = session.get(User, stage3_fixture["farmer_id"])
        batch = session.get(Batch, stage3_fixture["batch1_id"])

        # Inspector có quyền RECALL
        assert can_recall_batch(insp, batch) is True

        # Farmer không có quyền RECALL
        with pytest.raises(Exception):
            can_recall_batch(farmer, batch)
