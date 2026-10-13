"""Kiểm thử bắt buộc Giai đoạn 3A.2: Forward Traceability BFS (S-26, S-27) và CONSUMED (S-29).

Bao quát toàn diện:
1. Lô không có hậu duệ.
2. Lô có nhiều tầng hậu duệ (F1, F2, F3).
3. Một lô có nhiều nhánh con.
4. Quan hệ hình thoi (Diamond relation) không bị duplicate node.
5. Dữ liệu có chu trình cố ý -> dừng và báo lỗi HTTP 400 (Cycle detected).
6. Lô gốc không tồn tại -> HTTP 404.
7. Người dùng không có quyền truy cập -> HTTP 403.
8. Hậu duệ thuộc tổ chức khác -> bảo mật thông tin nội bộ cho user thường.
9. Inspector truy xuôi theo đúng quyền (thấy đầy đủ thông tin liên tổ chức).
10. CONSUMED hợp lệ: status="CONSUMED", remaining_quantity=0, hash-chain ghi nhận sự kiện CONSUMED.
11. CONSUMED lần 2 bị chặn -> HTTP 400.
12. Role không hợp lệ hoặc sai tổ chức cố CONSUMED -> HTTP 403.
13. Lô đang pending handover cố CONSUMED -> HTTP 409.
14. Chặn các thao tác bàn giao, tách, gộp, sửa sau khi CONSUMED -> HTTP 400.
15. Truy xuôi phản ánh đúng trạng thái CONSUMED: status="CONSUMED", remaining_quantity=0, nằm trong terminal_batches.
16. Hash-chain trước và sau các thao tác vẫn đảm bảo toàn vẹn toán học (is_valid == True).
"""

from datetime import date, datetime, timezone
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.hash_chain import verify_batch_chain
from app.models import (
    BATCH_STATUS_ACTIVE,
    BATCH_STATUS_CONSUMED,
    EVENT_CONSUMED,
    EVENT_HARVEST,
    EVENT_SPLIT,
    HANDOVER_ACCEPTED,
    HANDOVER_PENDING,
    RELATION_MERGE,
    RELATION_SPLIT,
    ROLE_DISTRIBUTOR,
    ROLE_FARMER,
    ROLE_INSPECTOR,
    ROLE_ORG_ADMIN,
    ROLE_PROCESSOR,
    ROLE_TRANSPORTER,
    Batch,
    BatchEvent,
    BatchRelation,
    Farm,
    Handover,
    Organization,
    Plot,
    Product,
    User,
)
from app.security import hash_password
from app.services.session_store import CSRF_HEADER_NAME, SESSION_COOKIE_NAME
from app.services.traceability import clear_trace_cache

PASSWORD = "TestPassword123!"


@pytest.fixture(autouse=True)
def clean_traceability_cache():
    clear_trace_cache()
    yield
    clear_trace_cache()


@pytest.fixture()
def stage3a2_fixture(session_factory: sessionmaker[Session]) -> dict[str, int]:
    """Khởi tạo môi trường dữ liệu cho Stage 3A.2 với 3 tổ chức và các vai trò chuẩn."""
    with session_factory() as session:
        # 1. Các tổ chức
        org_farm = Organization(code="S3A2-FARM", name="Hợp tác xã Nông nghiệp S3A2")
        org_proc = Organization(code="S3A2-PROC", name="Nhà máy Chế biến S3A2")
        org_dist = Organization(code="S3A2-DIST", name="Công ty Phân phối S3A2")
        org_other = Organization(code="S3A2-OTHER", name="Tổ chức Khác Không Liên Quan")
        session.add_all([org_farm, org_proc, org_dist, org_other])
        session.flush()

        # 2. Người dùng
        u_farmer = User(
            username="s3a2_farmer",
            email="farmer@s3a2.local",
            role=ROLE_FARMER,
            organization_id=org_farm.id,
            password=hash_password(PASSWORD),
        )
        u_proc = User(
            username="s3a2_proc",
            email="proc@s3a2.local",
            role=ROLE_PROCESSOR,
            organization_id=org_proc.id,
            password=hash_password(PASSWORD),
        )
        u_dist = User(
            username="s3a2_dist",
            email="dist@s3a2.local",
            role=ROLE_DISTRIBUTOR,
            organization_id=org_dist.id,
            password=hash_password(PASSWORD),
        )
        u_dist_admin = User(
            username="s3a2_dist_admin",
            email="dist_admin@s3a2.local",
            role=ROLE_ORG_ADMIN,
            organization_id=org_dist.id,
            password=hash_password(PASSWORD),
        )
        u_trans = User(
            username="s3a2_trans",
            email="trans@s3a2.local",
            role=ROLE_TRANSPORTER,
            organization_id=org_dist.id,
            password=hash_password(PASSWORD),
        )
        u_inspector = User(
            username="s3a2_inspector",
            email="inspector@s3a2.local",
            role=ROLE_INSPECTOR,
            organization_id=None,
            password=hash_password(PASSWORD),
        )
        u_other = User(
            username="s3a2_other",
            email="other@s3a2.local",
            role=ROLE_DISTRIBUTOR,
            organization_id=org_other.id,
            password=hash_password(PASSWORD),
        )
        session.add_all([u_farmer, u_proc, u_dist, u_dist_admin, u_trans, u_inspector, u_other])
        session.flush()

        # 3. Sản phẩm và Thửa đất
        prod = Product(name="Xoài Cát Chu S3A2", unit="kg")
        session.add(prod)
        session.flush()

        farm = Farm(
            name="Vùng trồng Xoài Cao Lãnh",
            location="Đồng Tháp",
            area=Decimal("15.5"),
            owner="Nông dân Ba",
            organization_id=org_farm.id,
        )
        session.add(farm)
        session.flush()

        plot = Plot(
            name="Thửa đất số 01",
            location="Cao Lãnh, Đồng Tháp",
            area=5.0,
            owner="Nguyễn Văn Nông",
            organization_id=org_farm.id,
        )
        session.add(plot)
        session.flush()

        # 4. Lô thu hoạch gốc
        batch_root = Batch(
            code="ROOT-001",
            plot_id=plot.id,
            farm_id=farm.id,
            product_id=prod.id,
            product_name=prod.name,
            harvest_date=date(2026, 9, 1),
            initial_quantity=Decimal("1000.00"),
            remaining_quantity=Decimal("1000.00"),
            current_org_id=org_farm.id,
            status="ACTIVE",
        )
        session.add(batch_root)
        session.flush()

        session.commit()

        return {
            "org_farm_id": org_farm.id,
            "org_proc_id": org_proc.id,
            "org_dist_id": org_dist.id,
            "org_other_id": org_other.id,
            "farmer_id": u_farmer.id,
            "proc_id": u_proc.id,
            "dist_id": u_dist.id,
            "dist_admin_id": u_dist_admin.id,
            "inspector_id": u_inspector.id,
            "other_id": u_other.id,
            "product_id": prod.id,
            "plot_id": plot.id,
            "root_batch_id": batch_root.id,
        }


def login_client(client: TestClient, username: str) -> dict[str, str]:
    """Hỗ trợ đăng nhập và lấy cookie session kèm CSRF token."""
    res = client.post(
        "/auth/login",
        json={"username": username, "password": PASSWORD},
    )
    assert res.status_code == 200, f"Đăng nhập thất bại: {res.text}"
    csrf_token = res.cookies.get("csrf_token") or res.json().get("csrf_token", "")
    session_id = res.cookies.get(SESSION_COOKIE_NAME, "")
    headers = {}
    if csrf_token:
        headers[CSRF_HEADER_NAME] = csrf_token
    if session_id:
        headers["Cookie"] = f"{SESSION_COOKIE_NAME}={session_id}; csrf_token={csrf_token}"
    return headers


# ==============================================================================
# BỘ TEST FORWARD TRACEABILITY BFS (S-26, S-27)
# ==============================================================================


def test_trace_forward_no_descendants(client: TestClient, stage3a2_fixture: dict[str, int]):
    """Test 1: Lô không có hậu duệ nào."""
    headers = login_client(client, "s3a2_farmer")
    root_id = stage3a2_fixture["root_batch_id"]

    res = client.get(f"/batches/{root_id}/trace-forward", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["target_batch"]["id"] == root_id
    assert data["total_descendants"] == 0
    assert data["descendants_by_level"] == {}
    # Lô đích chính là terminal batch
    assert len(data["terminal_batches"]) == 1
    assert data["terminal_batches"][0]["batch_id"] == root_id


def test_trace_forward_multi_level_and_branches(
    client: TestClient, stage3a2_fixture: dict[str, int], session_factory: sessionmaker[Session]
):
    """Test 2 & 3: Lô có nhiều tầng hậu duệ (F1, F2, F3) và nhiều nhánh con."""
    root_id = stage3a2_fixture["root_batch_id"]
    plot_id = stage3a2_fixture["plot_id"]
    prod_id = stage3a2_fixture["product_id"]
    org_farm_id = stage3a2_fixture["org_farm_id"]

    # Dựng cây phả hệ:
    # ROOT (A) -> con B1, B2 (Tầng 1)
    # B1 -> con C1 (Tầng 2)
    # C1 -> con D1 (Tầng 3)
    with session_factory() as session:
        b1 = Batch(code="F1-B01", plot_id=plot_id, product_id=prod_id, harvest_date=date(2026, 9, 2),
                   initial_quantity=Decimal("300.00"), remaining_quantity=Decimal("300.00"),
                   current_org_id=org_farm_id, status="ACTIVE")
        b2 = Batch(code="F1-B02", plot_id=plot_id, product_id=prod_id, harvest_date=date(2026, 9, 2),
                   initial_quantity=Decimal("700.00"), remaining_quantity=Decimal("700.00"),
                   current_org_id=org_farm_id, status="ACTIVE")
        session.add_all([b1, b2])
        session.flush()

        rel_ab1 = BatchRelation(parent_batch_id=root_id, child_batch_id=b1.id,
                                transferred_quantity=Decimal("300.00"), relation_type=RELATION_SPLIT)
        rel_ab2 = BatchRelation(parent_batch_id=root_id, child_batch_id=b2.id,
                                transferred_quantity=Decimal("700.00"), relation_type=RELATION_SPLIT)
        session.add_all([rel_ab1, rel_ab2])
        session.flush()

        c1 = Batch(code="F2-C01", plot_id=plot_id, product_id=prod_id, harvest_date=date(2026, 9, 3),
                   initial_quantity=Decimal("200.00"), remaining_quantity=Decimal("200.00"),
                   current_org_id=org_farm_id, status="ACTIVE")
        session.add(c1)
        session.flush()

        rel_b1c1 = BatchRelation(parent_batch_id=b1.id, child_batch_id=c1.id,
                                 transferred_quantity=Decimal("200.00"), relation_type=RELATION_SPLIT)
        session.add(rel_b1c1)
        session.flush()

        d1 = Batch(code="F3-D01", plot_id=plot_id, product_id=prod_id, harvest_date=date(2026, 9, 4),
                   initial_quantity=Decimal("100.00"), remaining_quantity=Decimal("100.00"),
                   current_org_id=org_farm_id, status="ACTIVE")
        session.add(d1)
        session.flush()

        rel_c1d1 = BatchRelation(parent_batch_id=c1.id, child_batch_id=d1.id,
                                 transferred_quantity=Decimal("100.00"), relation_type=RELATION_SPLIT)
        session.add(rel_c1d1)
        session.commit()

    headers = login_client(client, "s3a2_farmer")
    res = client.get(f"/batches/{root_id}/trace-forward", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total_descendants"] == 4  # B1, B2, C1, D1

    # Kiểm tra phân tầng BFS
    assert "1" in data["descendants_by_level"]
    assert "2" in data["descendants_by_level"]
    assert "3" in data["descendants_by_level"]

    level1_codes = [n["code"] for n in data["descendants_by_level"]["1"]]
    assert "F1-B01" in level1_codes
    assert "F1-B02" in level1_codes

    level2_codes = [n["code"] for n in data["descendants_by_level"]["2"]]
    assert "F2-C01" in level2_codes

    level3_codes = [n["code"] for n in data["descendants_by_level"]["3"]]
    assert "F3-D01" in level3_codes

    # Terminal batches: B2 (không có con) và D1 (không có con)
    term_codes = [t["code"] for t in data["terminal_batches"]]
    assert "F1-B02" in term_codes
    assert "F3-D01" in term_codes


def test_trace_forward_diamond_relation(
    client: TestClient, stage3a2_fixture: dict[str, int], session_factory: sessionmaker[Session]
):
    """Test 4: Quan hệ hình thoi (Diamond Pattern) không bị duplicate node trong cùng một tầng."""
    root_id = stage3a2_fixture["root_batch_id"]
    plot_id = stage3a2_fixture["plot_id"]
    prod_id = stage3a2_fixture["product_id"]
    org_farm_id = stage3a2_fixture["org_farm_id"]

    # Đồ thị hình thoi:
    # ROOT (A) -> tách ra DIA-B1 và DIA-B2 (Tầng 1)
    # DIA-B1 và DIA-B2 cùng gộp vào DIA-C1 (Tầng 2)
    with session_factory() as session:
        b1 = Batch(code="DIA-B01", plot_id=plot_id, product_id=prod_id, harvest_date=date(2026, 9, 2),
                   initial_quantity=Decimal("400.00"), remaining_quantity=Decimal("400.00"),
                   current_org_id=org_farm_id, status="ACTIVE")
        b2 = Batch(code="DIA-B02", plot_id=plot_id, product_id=prod_id, harvest_date=date(2026, 9, 2),
                   initial_quantity=Decimal("600.00"), remaining_quantity=Decimal("600.00"),
                   current_org_id=org_farm_id, status="ACTIVE")
        session.add_all([b1, b2])
        session.flush()

        session.add_all([
            BatchRelation(parent_batch_id=root_id, child_batch_id=b1.id,
                          transferred_quantity=Decimal("400.00"), relation_type=RELATION_SPLIT),
            BatchRelation(parent_batch_id=root_id, child_batch_id=b2.id,
                          transferred_quantity=Decimal("600.00"), relation_type=RELATION_SPLIT),
        ])
        session.flush()

        c1 = Batch(code="DIA-C01", plot_id=plot_id, product_id=prod_id, harvest_date=date(2026, 9, 3),
                   initial_quantity=Decimal("1000.00"), remaining_quantity=Decimal("1000.00"),
                   current_org_id=org_farm_id, status="ACTIVE")
        session.add(c1)
        session.flush()

        session.add_all([
            BatchRelation(parent_batch_id=b1.id, child_batch_id=c1.id,
                          transferred_quantity=Decimal("400.00"), relation_type=RELATION_MERGE),
            BatchRelation(parent_batch_id=b2.id, child_batch_id=c1.id,
                          transferred_quantity=Decimal("600.00"), relation_type=RELATION_MERGE),
        ])
        session.commit()

    headers = login_client(client, "s3a2_farmer")
    res = client.get(f"/batches/{root_id}/trace-forward", headers=headers)
    assert res.status_code == 200
    data = res.json()

    # DIA-C01 chỉ được xuất hiện ĐÚNG 1 LẦN trong tầng 2, không bị duplicate!
    level2_nodes = data["descendants_by_level"]["2"]
    dia_c1_nodes = [n for n in level2_nodes if n["code"] == "DIA-C01"]
    assert len(dia_c1_nodes) == 1, "Lô gộp hình thoi bị duplicate trong cùng tầng!"


def test_trace_forward_cycle_detection(
    client: TestClient, stage3a2_fixture: dict[str, int], session_factory: sessionmaker[Session]
):
    """Test 5: Phát hiện chu trình phả hệ bất thường (Cycle detected) -> HTTP 400 Bad Request."""
    root_id = stage3a2_fixture["root_batch_id"]
    plot_id = stage3a2_fixture["plot_id"]
    prod_id = stage3a2_fixture["product_id"]
    org_farm_id = stage3a2_fixture["org_farm_id"]

    # Cố tình tạo chu trình: ROOT -> CHILD -> ROOT
    with session_factory() as session:
        child = Batch(code="CYC-01", plot_id=plot_id, product_id=prod_id, harvest_date=date(2026, 9, 2),
                      initial_quantity=Decimal("100.00"), remaining_quantity=Decimal("100.00"),
                      current_org_id=org_farm_id, status="ACTIVE")
        session.add(child)
        session.flush()

        rel1 = BatchRelation(parent_batch_id=root_id, child_batch_id=child.id,
                             transferred_quantity=Decimal("100.00"), relation_type=RELATION_SPLIT)
        rel2 = BatchRelation(parent_batch_id=child.id, child_batch_id=root_id,
                             transferred_quantity=Decimal("100.00"), relation_type=RELATION_SPLIT)
        session.add_all([rel1, rel2])
        session.commit()

    headers = login_client(client, "s3a2_farmer")
    res = client.get(f"/batches/{root_id}/trace-forward", headers=headers)
    assert res.status_code == 400
    assert "Cycle detected" in res.json()["detail"] or "chu trình" in res.json()["detail"].lower()


def test_trace_forward_not_found(client: TestClient, stage3a2_fixture: dict[str, int]):
    """Test 6: Lô không tồn tại -> HTTP 404."""
    headers = login_client(client, "s3a2_farmer")
    res = client.get("/batches/999999/trace-forward", headers=headers)
    assert res.status_code == 404


def test_trace_forward_permission_denied(client: TestClient, stage3a2_fixture: dict[str, int]):
    """Test 7: Tổ chức khác không có quyền xem lô gốc -> HTTP 403."""
    headers = login_client(client, "s3a2_other")
    root_id = stage3a2_fixture["root_batch_id"]

    res = client.get(f"/batches/{root_id}/trace-forward", headers=headers)
    assert res.status_code == 403
    assert "quyền" in res.json()["detail"].lower()


def test_trace_forward_cross_organization_masking_and_inspector(
    client: TestClient, stage3a2_fixture: dict[str, int], session_factory: sessionmaker[Session]
):
    """Test 8 & 9: Hậu duệ thuộc tổ chức khác bị che giấu cho user thường, nhưng Inspector thấy đủ."""
    root_id = stage3a2_fixture["root_batch_id"]
    plot_id = stage3a2_fixture["plot_id"]
    prod_id = stage3a2_fixture["product_id"]
    org_dist_id = stage3a2_fixture["org_dist_id"]

    # Tạo lô con thuộc Org Dist (qua handover hoặc split sang dist)
    with session_factory() as session:
        child_dist = Batch(
            code="DIST-CHILD-01",
            plot_id=plot_id,
            product_id=prod_id,
            harvest_date=date(2026, 9, 3),
            initial_quantity=Decimal("500.00"),
            remaining_quantity=Decimal("500.00"),
            current_org_id=org_dist_id,
            status="ACTIVE",
        )
        session.add(child_dist)
        session.flush()

        rel = BatchRelation(
            parent_batch_id=root_id,
            child_batch_id=child_dist.id,
            transferred_quantity=Decimal("500.00"),
            relation_type=RELATION_SPLIT,
        )
        session.add(rel)
        session.commit()

    # 1. User farmer (org_farm) truy xuôi từ root_id:
    # Lô child_dist thuộc org_dist mà farmer không có quyền xem nội bộ
    headers_farmer = login_client(client, "s3a2_farmer")
    res_farmer = client.get(f"/batches/{root_id}/trace-forward", headers=headers_farmer)
    assert res_farmer.status_code == 200
    data_f = res_farmer.json()
    desc_node = data_f["descendants_by_level"]["1"][0]
    assert desc_node["code"] == "DIST-CHILD-01"
    # Thông tin nội bộ bị che giấu
    assert desc_node["location"] == "[Bảo mật]"
    assert desc_node["owner"] is None
    assert desc_node["is_masked"] is True

    # 2. Inspector truy xuôi: Xem toàn bộ liên tổ chức, không bị che giấu
    headers_insp = login_client(client, "s3a2_inspector")
    res_insp = client.get(f"/batches/{root_id}/trace-forward", headers=headers_insp)
    assert res_insp.status_code == 200
    data_i = res_insp.json()
    desc_node_i = data_i["descendants_by_level"]["1"][0]
    assert desc_node_i["code"] == "DIST-CHILD-01"
    assert desc_node_i["location"] != "[Bảo mật]"
    assert desc_node_i["is_masked"] is False


# ==============================================================================
# BỘ TEST CONSUMED (S-29)
# ==============================================================================


def test_consumed_valid_distributor(
    client: TestClient, stage3a2_fixture: dict[str, int], session_factory: sessionmaker[Session]
):
    """Test 10: Distributor ghi nhận CONSUMED hợp lệ."""
    plot_id = stage3a2_fixture["plot_id"]
    prod_id = stage3a2_fixture["product_id"]
    org_dist_id = stage3a2_fixture["org_dist_id"]

    with session_factory() as session:
        batch_retail = Batch(
            code="RETAIL-01",
            plot_id=plot_id,
            product_id=prod_id,
            harvest_date=date(2026, 9, 5),
            initial_quantity=Decimal("250.00"),
            remaining_quantity=Decimal("250.00"),
            current_org_id=org_dist_id,
            status="ACTIVE",
        )
        session.add(batch_retail)
        session.commit()
        batch_id = batch_retail.id

    headers = login_client(client, "s3a2_dist")
    res = client.post(
        f"/batches/{batch_id}/consume",
        json={"notes": "Đã bán hết tại Siêu thị BigC"},
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["batch"]["status"] == "CONSUMED"
    assert data["batch"]["remaining_quantity"] == 0.0
    assert data["event"]["event_type"] == "CONSUMED"

    # Kiểm tra database thật
    with session_factory() as session:
        db_batch = session.get(Batch, batch_id)
        assert db_batch.status == "CONSUMED"
        assert db_batch.remaining_quantity == Decimal("0.00")
        assert db_batch.quantity == 0.0

        # Kiểm tra sự kiện hash-chain
        events = list(session.query(BatchEvent).filter_by(batch_id=batch_id).all())
        assert any(e.event_type == "CONSUMED" for e in events)

        # Toàn vẹn chuỗi
        integrity = verify_batch_chain(session, batch_id)
        assert integrity["is_valid"] is True


def test_consumed_second_time_blocked(
    client: TestClient, stage3a2_fixture: dict[str, int], session_factory: sessionmaker[Session]
):
    """Test 11: Cố tình ghi nhận CONSUMED lần 2 bị chặn -> HTTP 400."""
    plot_id = stage3a2_fixture["plot_id"]
    prod_id = stage3a2_fixture["product_id"]
    org_dist_id = stage3a2_fixture["org_dist_id"]

    with session_factory() as session:
        batch_consumed = Batch(
            code="ALREADY-CONSUMED",
            plot_id=plot_id,
            product_id=prod_id,
            harvest_date=date(2026, 9, 5),
            initial_quantity=Decimal("100.00"),
            remaining_quantity=Decimal("0.00"),
            current_org_id=org_dist_id,
            status="CONSUMED",
        )
        session.add(batch_consumed)
        session.commit()
        batch_id = batch_consumed.id

    headers = login_client(client, "s3a2_dist")
    res = client.post(
        f"/batches/{batch_id}/consume",
        json={"notes": "Cố tình bấm lại"},
        headers=headers,
    )
    assert res.status_code == 400
    assert "CONSUMED" in res.json()["detail"] or "đã tiêu thụ" in res.json()["detail"].lower()


def test_consumed_forbidden_roles_and_organizations(
    client: TestClient, stage3a2_fixture: dict[str, int], session_factory: sessionmaker[Session]
):
    """Test 12: Vai trò không hợp lệ (Farmer/Transporter/Inspector) hoặc sai tổ chức cố CONSUMED -> HTTP 403."""
    plot_id = stage3a2_fixture["plot_id"]
    prod_id = stage3a2_fixture["product_id"]
    org_dist_id = stage3a2_fixture["org_dist_id"]

    with session_factory() as session:
        b = Batch(
            code="DIST-CHECK-ROLE",
            plot_id=plot_id,
            product_id=prod_id,
            harvest_date=date(2026, 9, 5),
            initial_quantity=Decimal("100.00"),
            remaining_quantity=Decimal("100.00"),
            current_org_id=org_dist_id,
            status="ACTIVE",
        )
        session.add(b)
        session.commit()
        batch_id = b.id

    # 1. Farmer thuộc org_farm cố consume lô của org_dist -> 403 (sai tổ chức)
    h_farmer = login_client(client, "s3a2_farmer")
    res = client.post(f"/batches/{batch_id}/consume", json={}, headers=h_farmer)
    assert res.status_code == 403

    # 2. Transporter cùng org_dist nhưng không có vai trò BATCH_CONSUME -> 403
    h_trans = login_client(client, "s3a2_trans")
    res = client.post(f"/batches/{batch_id}/consume", json={}, headers=h_trans)
    assert res.status_code == 403

    # 3. Inspector (thanh tra chỉ xem) -> 403
    h_insp = login_client(client, "s3a2_inspector")
    res = client.post(f"/batches/{batch_id}/consume", json={}, headers=h_insp)
    assert res.status_code == 403

    # 4. Org Admin của org_dist thì ĐƯỢC PHÉP
    h_dist_admin = login_client(client, "s3a2_dist_admin")
    res = client.post(f"/batches/{batch_id}/consume", json={}, headers=h_dist_admin)
    assert res.status_code == 200


def test_consumed_pending_handover_blocked(
    client: TestClient, stage3a2_fixture: dict[str, int], session_factory: sessionmaker[Session]
):
    """Test 13: Lô đang có handover chờ duyệt (PENDING) cố CONSUMED -> HTTP 409 Conflict."""
    plot_id = stage3a2_fixture["plot_id"]
    prod_id = stage3a2_fixture["product_id"]
    org_dist_id = stage3a2_fixture["org_dist_id"]
    org_proc_id = stage3a2_fixture["org_proc_id"]

    with session_factory() as session:
        b = Batch(
            code="PENDING-BATCH",
            plot_id=plot_id,
            product_id=prod_id,
            harvest_date=date(2026, 9, 5),
            initial_quantity=Decimal("100.00"),
            remaining_quantity=Decimal("100.00"),
            current_org_id=org_dist_id,
            status="ACTIVE",
        )
        session.add(b)
        session.flush()

        ho = Handover(
            batch_id=b.id,
            from_org_id=org_dist_id,
            to_org_id=org_proc_id,
            status=HANDOVER_PENDING,
        )
        session.add(ho)
        session.commit()
        batch_id = b.id

    headers = login_client(client, "s3a2_dist")
    res = client.post(f"/batches/{batch_id}/consume", json={}, headers=headers)
    assert res.status_code == 409
    assert "chờ xác nhận" in res.json()["detail"].lower() or "bàn giao" in res.json()["detail"].lower()


def test_operations_blocked_after_consumed(
    client: TestClient, stage3a2_fixture: dict[str, int], session_factory: sessionmaker[Session]
):
    """Test 14: Chặn bàn giao, tách, gộp, sửa sau khi CONSUMED -> HTTP 400."""
    plot_id = stage3a2_fixture["plot_id"]
    prod_id = stage3a2_fixture["product_id"]
    org_dist_id = stage3a2_fixture["org_dist_id"]
    org_proc_id = stage3a2_fixture["org_proc_id"]

    with session_factory() as session:
        b = Batch(
            code="CONSUMED-BLOCK",
            plot_id=plot_id,
            product_id=prod_id,
            harvest_date=date(2026, 9, 5),
            initial_quantity=Decimal("100.00"),
            remaining_quantity=Decimal("0.00"),
            current_org_id=org_dist_id,
            status="CONSUMED",
        )
        session.add(b)
        session.commit()
        batch_id = b.id

    headers = login_client(client, "s3a2_dist")

    # 1. Chặn bàn giao
    res_ho = client.post(
        f"/batches/{batch_id}/handover",
        json={"to_org_id": org_proc_id, "note": "Thử bàn giao"},
        headers=headers,
    )
    assert res_ho.status_code == 400
    assert "CONSUMED" in res_ho.json()["detail"] or "hết khối lượng" in res_ho.json()["detail"]

    # 2. Chặn tách lô
    res_sp = client.post(
        f"/batches/{batch_id}/split",
        json={"items": [{"quantity": 10.0}]},
        headers=headers,
    )
    assert res_sp.status_code == 400
    assert "CONSUMED" in res_sp.json()["detail"]

    # 3. Chặn gộp lô
    # Dùng proc login để thử gộp
    headers_proc = login_client(client, "s3a2_proc")
    res_mg = client.post(
        "/batches/merge",
        json={"items": [{"parent_batch_id": batch_id, "quantity": 10.0}, {"parent_batch_id": stage3a2_fixture["root_batch_id"], "quantity": 10.0}],
              "product_id": prod_id},
        headers=headers_proc,
    )
    assert res_mg.status_code in (400, 403)

    # 4. Chặn sửa lô
    res_up = client.put(
        f"/batches/{batch_id}",
        json={"harvest_date": "2026-09-06"},
        headers=headers,
    )
    assert res_up.status_code == 400
    assert "CONSUMED" in res_up.json()["detail"] or "tiêu thụ" in res_up.json()["detail"].lower()


def test_trace_forward_reflects_consumed_state(
    client: TestClient, stage3a2_fixture: dict[str, int], session_factory: sessionmaker[Session]
):
    """Test 15: Truy xuôi phản ánh đúng hậu duệ đã CONSUMED (khối lượng=0, status=CONSUMED, nằm trong terminal)."""
    root_id = stage3a2_fixture["root_batch_id"]
    plot_id = stage3a2_fixture["plot_id"]
    prod_id = stage3a2_fixture["product_id"]
    org_dist_id = stage3a2_fixture["org_dist_id"]

    with session_factory() as session:
        b_cons = Batch(
            code="CONS-DESC-01",
            plot_id=plot_id,
            product_id=prod_id,
            harvest_date=date(2026, 9, 5),
            initial_quantity=Decimal("300.00"),
            remaining_quantity=Decimal("0.00"),
            current_org_id=org_dist_id,
            status="CONSUMED",
        )
        session.add(b_cons)
        session.flush()

        rel = BatchRelation(
            parent_batch_id=root_id,
            child_batch_id=b_cons.id,
            transferred_quantity=Decimal("300.00"),
            relation_type=RELATION_SPLIT,
        )
        session.add(rel)
        session.commit()

    headers = login_client(client, "s3a2_inspector")
    res = client.get(f"/batches/{root_id}/trace-forward", headers=headers)
    assert res.status_code == 200
    data = res.json()

    # Kiểm tra hậu duệ
    node = data["descendants_by_level"]["1"][0]
    assert node["code"] == "CONS-DESC-01"
    assert node["status"] == "CONSUMED"
    assert node["is_consumed"] is True
    assert node["remaining_quantity"] == 0.0

    # Lô CONSUMED là điểm cuối chuỗi cung ứng (terminal batch)
    term_codes = [t["code"] for t in data["terminal_batches"]]
    assert "CONS-DESC-01" in term_codes
    term_node = next(t for t in data["terminal_batches"] if t["code"] == "CONS-DESC-01")
    assert term_node["status"] == "CONSUMED"
    assert term_node["is_consumed"] is True
    assert term_node["remaining_quantity"] == 0.0


def test_batch_summary_can_consume_flag(
    client: TestClient, stage3a2_fixture: dict[str, int], session_factory: sessionmaker[Session]
):
    """Test 16: Endpoint GET /batches/{id}/summary trả về cờ can_consume chính xác."""
    plot_id = stage3a2_fixture["plot_id"]
    prod_id = stage3a2_fixture["product_id"]
    org_dist_id = stage3a2_fixture["org_dist_id"]

    with session_factory() as session:
        b = Batch(
            code="SUMM-CHECK-01",
            plot_id=plot_id,
            product_id=prod_id,
            harvest_date=date(2026, 9, 5),
            initial_quantity=Decimal("50.00"),
            remaining_quantity=Decimal("50.00"),
            current_org_id=org_dist_id,
            status="ACTIVE",
        )
        session.add(b)
        session.commit()
        batch_id = b.id

    # Distributor giữ lô -> can_consume == True
    h_dist = login_client(client, "s3a2_dist")
    res = client.get(f"/batches/{batch_id}/summary", headers=h_dist)
    assert res.status_code == 200
    assert res.json()["can_consume"] is True

    # Farmer không giữ lô -> 403 (không xem được)
    # Inspector xem được nhưng can_consume == False (chỉ xem, không bán hàng)
    h_insp = login_client(client, "s3a2_inspector")
    res = client.get(f"/batches/{batch_id}/summary", headers=h_insp)
    assert res.status_code == 200, f"Detail: {res.text}"
    assert res.json()["can_consume"] is False


def test_trace_forward_returns_independent_current_state_for_each_descendant(
    client: TestClient, stage3a2_fixture: dict[str, int], session_factory: sessionmaker[Session]
):
    """S-27: Each terminal descendant uses its own holder and persisted remaining quantity."""
    root_id = stage3a2_fixture["root_batch_id"]
    inspector_headers = login_client(client, "s3a2_inspector")
    cached = client.get(f"/batches/{root_id}/trace-forward", headers=inspector_headers)
    assert cached.status_code == 200
    assert cached.json()["total_descendants"] == 0

    split = client.post(
        f"/batches/{root_id}/split",
        json={"items": [{"quantity": 300}, {"quantity": 700}]},
        headers=login_client(client, "s3a2_farmer"),
    )
    assert split.status_code == 201, split.text
    split_children = split.json()["child_batches"]
    child_ids = [child["id"] for child in split_children]
    assert [child["initial_quantity"] for child in split_children] == [300.0, 700.0]

    with session_factory() as session:
        first, second = [session.get(Batch, child_id) for child_id in child_ids]
        assert first is not None and second is not None
        first.current_org_id = stage3a2_fixture["org_proc_id"]
        first.remaining_quantity = Decimal("75.00")
        second.current_org_id = stage3a2_fixture["org_dist_id"]
        second.remaining_quantity = Decimal("20.00")
        session.commit()

    response = client.get(
        f"/batches/{root_id}/trace-forward",
        headers=inspector_headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    descendants = {
        node["code"]: node
        for level in data["descendants_by_level"].values()
        for node in level
    }

    first_node = descendants[split_children[0]["code"]]
    second_node = descendants[split_children[1]["code"]]
    assert first_node["current_org_name"] == "Nhà máy Chế biến S3A2"
    assert first_node["current_holding_organization"] == "Nhà máy Chế biến S3A2"
    assert first_node["current_location"] is None
    assert first_node["remaining_quantity"] == 75.0
    assert second_node["current_org_name"] == "Công ty Phân phối S3A2"
    assert second_node["current_holding_organization"] == "Công ty Phân phối S3A2"
    assert second_node["current_location"] is None
    assert second_node["remaining_quantity"] == 20.0

    terminal_by_code = {node["code"]: node for node in data["terminal_batches"]}
    assert set(terminal_by_code) == {child["code"] for child in split_children}
    assert sum(node["remaining_quantity"] for node in terminal_by_code.values()) == 95.0
    assert terminal_by_code[split_children[0]["code"]]["current_location"] is None
    assert terminal_by_code[split_children[1]["code"]]["current_location"] is None
    assert data["target_batch"]["remaining_quantity"] == 0.0


def test_trace_forward_reflects_accepted_handover(
    client: TestClient, stage3a2_fixture: dict[str, int], session_factory: sessionmaker[Session]
):
    """S-27: An accepted handover changes the descendant holder without changing its quantity."""
    root_id = stage3a2_fixture["root_batch_id"]
    plot_id = stage3a2_fixture["plot_id"]
    product_id = stage3a2_fixture["product_id"]

    with session_factory() as session:
        root = session.get(Batch, root_id)
        assert root is not None
        root.remaining_quantity = Decimal("880.00")
        root.status = "SPLIT"
        child = Batch(
            code="S27-TRANSFER",
            plot_id=plot_id,
            product_id=product_id,
            harvest_date=date(2026, 9, 2),
            initial_quantity=Decimal("120.00"),
            remaining_quantity=Decimal("80.00"),
            current_org_id=stage3a2_fixture["org_farm_id"],
            status="ACTIVE",
        )
        session.add(child)
        session.flush()
        session.add(BatchRelation(
            parent_batch_id=root_id,
            child_batch_id=child.id,
            transferred_quantity=Decimal("120.00"),
            relation_type=RELATION_SPLIT,
        ))
        session.commit()
        child_id = child.id

    request = client.post(
        f"/api/batches/{child_id}/handover",
        json={"to_org_id": stage3a2_fixture["org_proc_id"], "note": "S-27 accepted transfer"},
        headers=login_client(client, "s3a2_farmer"),
    )
    assert request.status_code == 201, request.text
    accepted = client.post(
        f"/handovers/{request.json()['id']}/accept",
        headers=login_client(client, "s3a2_proc"),
    )
    assert accepted.status_code == 200, accepted.text

    response = client.get(
        f"/batches/{root_id}/trace-forward",
        headers=login_client(client, "s3a2_inspector"),
    )
    assert response.status_code == 200, response.text
    node = response.json()["descendants_by_level"]["1"][0]
    assert node["current_org_id"] == stage3a2_fixture["org_proc_id"]
    assert node["current_org_name"] == "Nhà máy Chế biến S3A2"
    assert node["current_holding_organization"] == "Nhà máy Chế biến S3A2"
    assert node["remaining_quantity"] == 80.0


def test_current_organization_name_does_not_fall_back_to_origin_owner(
    client: TestClient, stage3a2_fixture: dict[str, int], session_factory: sessionmaker[Session]
):
    """S-27: The API returns unknown for a missing holder relation, not the source plot owner."""
    root_id = stage3a2_fixture["root_batch_id"]
    with session_factory() as session:
        root = session.get(Batch, root_id)
        assert root is not None
        root.remaining_quantity = Decimal("950.00")
        root.status = "SPLIT"
        batch = Batch(
            code="S27-UNKNOWN-ORG",
            plot_id=stage3a2_fixture["plot_id"],
            product_id=stage3a2_fixture["product_id"],
            harvest_date=date(2026, 9, 2),
            initial_quantity=Decimal("50.00"),
            remaining_quantity=Decimal("50.00"),
            current_org_id=999999,
            status="ACTIVE",
        )
        session.add(batch)
        session.flush()
        session.add(BatchRelation(
            parent_batch_id=root_id,
            child_batch_id=batch.id,
            transferred_quantity=Decimal("50.00"),
            relation_type=RELATION_SPLIT,
        ))
        session.commit()
        child_id = batch.id

    response = client.get(
        f"/batches/{root_id}/trace-forward",
        headers=login_client(client, "s3a2_inspector"),
    )
    assert response.status_code == 200, response.text
    unknown = next(
        node
        for nodes in response.json()["descendants_by_level"].values()
        for node in nodes
        if node["batch_id"] == child_id
    )
    assert unknown["current_org_id"] == 999999
    assert unknown["current_org_name"] is None
    assert unknown["current_holding_organization"] is None
    assert unknown["current_location"] is None
