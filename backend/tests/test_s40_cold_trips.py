"""Bộ kiểm thử toàn diện cho SCRUM-77 — S-40: Mở chuyến vận chuyển, gắn nhiều lô và một thùng lạnh.

Bao phủ các ca kiểm thử:
1. Mở chuyến thành công với 1 thùng lạnh và nhiều lô (Happy Path).
2. Kiểm tra tính toàn vẹn Hash-chain (sự kiện TRIP_DISPATCH trên từng lô).
3. Chặn mở chuyến nếu người gọi không có quyền Transporter (403 Forbidden).
4. Chặn mở chuyến nếu lô thuộc tổ chức khác (403 Forbidden).
5. Chặn mở chuyến nếu lô đang nằm trong một chuyến khác đang chạy (S-16 Constraint - 400 Bad Request).
6. Chặn mở chuyến nếu thùng lạnh đang được dùng bởi một chuyến khác đang chạy (400 Bad Request).
7. Chặn mở chuyến nếu lô đang có yêu cầu bàn giao chờ duyệt (PENDING - 400 Bad Request).
8. Hoàn thành chuyến xe (Xuống xe / TRIP_DELIVER) và giải phóng thùng lạnh / lô hàng.
9. Chặn hoàn thành chuyến xe của tổ chức khác (403 Forbidden).
10. Phân quyền xem danh sách chuyến: Transporter theo tổ chức, Inspector xem toàn hệ thống.
11. API tra cứu chuyến xe theo thùng lạnh hỗ trợ cảm biến nhiệt độ S-41.
"""

from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.hash_chain import verify_batch_chain
from app.models import (
    HANDOVER_ACCEPTED,
    HANDOVER_PENDING,
    ROLE_DISTRIBUTOR,
    ROLE_FARMER,
    ROLE_INSPECTOR,
    ROLE_ORG_ADMIN,
    ROLE_TRANSPORTER,
    Batch,
    BatchEvent,
    Farm,
    Handover,
    Organization,
    Product,
    User,
)
from app.security import hash_password
from app.trip_models import ColdTrip, ColdTripBatch

PASSWORD = "test-password-123"


@pytest.fixture()
def setup_s40_test_data(session_factory: sessionmaker[Session]) -> dict[str, Any]:
    """Khởi tạo môi trường dữ liệu kiểm thử cách ly cho S-40:

    - Org 1 (Nông trại Tân Cương): Có Farmer
    - Org 2 (Đơn vị vận chuyển Logistics Hà Nội): Có Transporter & Org Admin
    - Org 3 (Nhà phân phối): Có Distributor
    - Thanh tra viên (Inspector)
    - 3 Lô nông sản:
      + Batch 1: thuộc Org 2 (đã bàn giao sang Org 2)
      + Batch 2: thuộc Org 2 (đã bàn giao sang Org 2)
      + Batch 3: thuộc Org 1 (vẫn ở Org 1)
    """
    with session_factory() as session:
        # 1. Tạo 3 tổ chức
        org_farm = Organization(name="HTX Chè Tân Cương", code="HTX-TC", description="Trang trại")
        org_trans = Organization(name="Logistics Chuỗi Lạnh Hà Nội", code="LOG-HN", description="Vận chuyển lạnh")
        org_dist = Organization(name="Phân phối Miền Bắc", code="DIST-MB", description="Nhà phân phối")
        session.add_all([org_farm, org_trans, org_dist])
        session.flush()

        # 2. Tạo users cho từng vai trò
        u_farmer = User(
            username="farmer_tc", password=hash_password(PASSWORD), role=ROLE_FARMER, organization_id=org_farm.id
        )
        u_transporter = User(
            username="trans_hn", password=hash_password(PASSWORD), role=ROLE_TRANSPORTER, organization_id=org_trans.id
        )
        u_trans_admin = User(
            username="orgadmin_trans", password=hash_password(PASSWORD), role=ROLE_ORG_ADMIN, organization_id=org_trans.id
        )
        u_distributor = User(
            username="dist_mb", password=hash_password(PASSWORD), role=ROLE_DISTRIBUTOR, organization_id=org_dist.id
        )
        u_inspector = User(
            username="inspector_s40", password=hash_password(PASSWORD), role=ROLE_INSPECTOR, organization_id=org_farm.id
        )
        session.add_all([u_farmer, u_transporter, u_trans_admin, u_distributor, u_inspector])
        session.flush()

        # 3. Tạo sản phẩm & thửa đất
        product = Product(name="Chè búp Tân Cương Đặc Biệt", unit="kg")
        farm = Farm(name="Đồi chè số 1", location="Tân Cương", area=5.0, owner="HTX-TC", organization_id=org_farm.id)
        session.add_all([product, farm])
        session.flush()

        # 4. Tạo các lô hàng
        # Batch 1 & 2 do Org 2 (Transporter) nắm giữ
        batch_1 = Batch(
            code="BATCH-01",
            plot_id=farm.id,
            product_id=product.id,
            harvest_date=date.today(),
            initial_quantity=500.0,
            remaining_quantity=500.0,
            current_org_id=org_trans.id,
            status="ACTIVE",
        )
        batch_2 = Batch(
            code="BATCH-02",
            plot_id=farm.id,
            product_id=product.id,
            harvest_date=date.today(),
            initial_quantity=300.0,
            remaining_quantity=300.0,
            current_org_id=org_trans.id,
            status="ACTIVE",
        )
        # Batch 3 do Org 1 (Farmer) nắm giữ
        batch_3 = Batch(
            code="BATCH-03",
            plot_id=farm.id,
            product_id=product.id,
            harvest_date=date.today(),
            initial_quantity=200.0,
            remaining_quantity=200.0,
            current_org_id=org_farm.id,
            status="ACTIVE",
        )
        session.add_all([batch_1, batch_2, batch_3])
        session.flush()

        # Ghi nhận genesis event cho các lô để hash-chain sẵn sàng
        from app.hash_chain import record_event
        for b in (batch_1, batch_2, batch_3):
            record_event(
                db=session,
                batch_id=b.id,
                event_type="HARVEST",
                payload={"quantity": float(b.initial_quantity), "unit": "kg"},
                org_id=b.current_org_id,
                user_id=u_farmer.id,
            )

        session.commit()

        return {
            "org_trans_id": org_trans.id,
            "org_farm_id": org_farm.id,
            "batch_1_id": batch_1.id,
            "batch_2_id": batch_2.id,
            "batch_3_id": batch_3.id,
            "u_transporter": u_transporter.username,
            "u_trans_id": u_transporter.id,
            "u_trans_admin": u_trans_admin.username,
            "u_farmer": u_farmer.username,
            "u_distributor": u_distributor.username,
            "u_inspector": u_inspector.username,
        }


# ==============================================================================
# TEST CASES
# ==============================================================================

def test_create_cold_trip_success(
    client: TestClient, setup_s40_test_data: dict[str, Any], session_factory: sessionmaker[Session]
):
    """TC-S40-01: Mở chuyến thành công với 1 thùng lạnh và nhiều lô (Happy Path)."""
    data = setup_s40_test_data
    b1 = data["batch_1_id"]
    b2 = data["batch_2_id"]

    payload = {
        "trip_code": "TRIP-20261019-TEST01",
        "container_code": "CONT-COLD-01",
        "batch_ids": [b1, b2],
        "driver_name": "Trần Văn Vận",
        "vehicle_plate": "29B-999.88",
        "start_location": "Kho Thái Nguyên",
        "destination_location": "Kho Hà Nội",
        "notes": "Chuyến thử nghiệm đạt chuẩn chuỗi lạnh",
    }

    res = client.post(
        "/trips",
        json=payload,
        auth=(data["u_transporter"], PASSWORD),
    )

    assert res.status_code == 201, res.text
    trip_data = res.json()
    assert trip_data["trip_code"] == "TRIP-20261019-TEST01"
    assert trip_data["container_code"] == "CONT-COLD-01"
    assert trip_data["status"] == "IN_TRANSIT"
    assert trip_data["batch_count"] == 2
    assert len(trip_data["batches"]) == 2

    # Kiểm tra tính toàn vẹn hash-chain của từng lô
    with session_factory() as session:
        v1 = verify_batch_chain(session, b1)
        assert v1["is_valid"] is True, v1
        assert v1["total_events"] == 2  # HARVEST + TRIP_DISPATCH

        v2 = verify_batch_chain(session, b2)
        assert v2["is_valid"] is True, v2
        assert v2["total_events"] == 2


def test_create_trip_with_auto_generated_code(client: TestClient, setup_s40_test_data: dict[str, Any]):
    """TC-S40-02: Mở chuyến không truyền trip_code -> Hệ thống tự sinh TRIP-YYYYMMDD-XXXX."""
    data = setup_s40_test_data
    payload = {
        "container_code": "BOX-COLD-99",
        "batch_ids": [data["batch_1_id"]],
    }

    res = client.post(
        "/trips",
        json=payload,
        auth=(data["u_transporter"], PASSWORD),
    )
    assert res.status_code == 201
    res_data = res.json()
    assert res_data["trip_code"].startswith("TRIP-")
    assert len(res_data["trip_code"]) >= 15


def test_create_trip_forbidden_for_non_transporter(client: TestClient, setup_s40_test_data: dict[str, Any]):
    """TC-S40-03: Chặn mở chuyến nếu người gọi không có quyền Transporter (403 Forbidden)."""
    data = setup_s40_test_data
    payload = {
        "container_code": "CONT-TEST",
        "batch_ids": [data["batch_1_id"]],
    }

    # Farmer gọi -> 403
    res_farmer = client.post("/trips", json=payload, auth=(data["u_farmer"], PASSWORD))
    assert res_farmer.status_code == 403

    # Distributor gọi -> 403
    res_dist = client.post("/trips", json=payload, auth=(data["u_distributor"], PASSWORD))
    assert res_dist.status_code == 403

    # Inspector gọi -> 403
    res_insp = client.post("/trips", json=payload, auth=(data["u_inspector"], PASSWORD))
    assert res_insp.status_code == 403


def test_create_trip_forbidden_for_batches_not_held_by_org(client: TestClient, setup_s40_test_data: dict[str, Any]):
    """TC-S40-04: Chặn mở chuyến nếu có lô thuộc tổ chức khác mà Transporter chưa nhận (403 Forbidden)."""
    data = setup_s40_test_data
    # batch_3 thuộc Org 1 (Farmer), Transporter thuộc Org 2
    payload = {
        "container_code": "CONT-FAIL-01",
        "batch_ids": [data["batch_1_id"], data["batch_3_id"]],
    }

    res = client.post("/trips", json=payload, auth=(data["u_transporter"], PASSWORD))
    assert res.status_code == 403
    assert "thuộc tổ chức khác" in res.json()["detail"]


def test_create_trip_duplicate_batch_in_running_trips(client: TestClient, setup_s40_test_data: dict[str, Any]):
    """TC-S40-05 (Ràng buộc S-16): Một lô không được nằm trong hai chuyến IN_TRANSIT đồng thời."""
    data = setup_s40_test_data
    b1 = data["batch_1_id"]

    # 1. Chuyến 1 mở thành công chở Batch 1
    res1 = client.post(
        "/trips",
        json={"container_code": "CONT-A", "batch_ids": [b1]},
        auth=(data["u_transporter"], PASSWORD),
    )
    assert res1.status_code == 201

    # 2. Chuyến 2 cố tình chở lại Batch 1 bằng thùng khác -> Chặn 400
    res2 = client.post(
        "/trips",
        json={"container_code": "CONT-B", "batch_ids": [b1]},
        auth=(data["u_transporter"], PASSWORD),
    )
    assert res2.status_code == 400
    assert "đang nằm trong một chuyến xe khác đang chạy" in res2.json()["detail"]


def test_create_trip_duplicate_container_in_running_trips(client: TestClient, setup_s40_test_data: dict[str, Any]):
    """TC-S40-06: Một thùng lạnh không được nằm trong hai chuyến IN_TRANSIT đồng thời."""
    data = setup_s40_test_data
    b1 = data["batch_1_id"]
    b2 = data["batch_2_id"]

    # 1. Chuyến 1 dùng thùng CONT-SHARED chở Batch 1
    res1 = client.post(
        "/trips",
        json={"container_code": "CONT-SHARED", "batch_ids": [b1]},
        auth=(data["u_transporter"], PASSWORD),
    )
    assert res1.status_code == 201

    # 2. Chuyến 2 chở Batch 2 nhưng lại tái sử dụng thùng CONT-SHARED khi Chuyến 1 chưa xong -> Chặn 400
    res2 = client.post(
        "/trips",
        json={"container_code": "CONT-SHARED", "batch_ids": [b2]},
        auth=(data["u_transporter"], PASSWORD),
    )
    assert res2.status_code == 400
    assert "chưa kết thúc" in res2.json()["detail"]


def test_complete_trip_lifecycle(
    client: TestClient, setup_s40_test_data: dict[str, Any], session_factory: sessionmaker[Session]
):
    """TC-S40-07: Hoàn thành chuyến xe (Xuống xe / TRIP_DELIVER) và tái sử dụng thùng/lô cho chuyến mới."""
    data = setup_s40_test_data
    b1 = data["batch_1_id"]

    # 1. Mở chuyến
    create_res = client.post(
        "/trips",
        json={"container_code": "CONT-LIFE", "batch_ids": [b1]},
        auth=(data["u_transporter"], PASSWORD),
    )
    assert create_res.status_code == 201
    trip_id = create_res.json()["id"]

    # 2. Hoàn thành chuyến
    comp_res = client.post(
        f"/trips/{trip_id}/complete",
        json={"notes": "Hàng dỡ xuống kho an toàn, kiểm tra không dập nát"},
        auth=(data["u_transporter"], PASSWORD),
    )
    assert comp_res.status_code == 200
    comp_data = comp_res.json()
    assert comp_data["status"] == "COMPLETED"
    assert comp_data["end_time"] is not None

    # Kiểm tra hash chain: phải có sự kiện TRIP_DELIVER
    with session_factory() as session:
        v = verify_batch_chain(session, b1)
        assert v["is_valid"] is True
        assert v["total_events"] == 3  # HARVEST + TRIP_DISPATCH + TRIP_DELIVER

    # 3. Sau khi kết thúc, thùng CONT-LIFE và lô b1 có thể mở chuyến mới bình thường
    new_res = client.post(
        "/trips",
        json={"container_code": "CONT-LIFE", "batch_ids": [b1]},
        auth=(data["u_transporter"], PASSWORD),
    )
    assert new_res.status_code == 201


def test_list_and_detail_cold_trips(client: TestClient, setup_s40_test_data: dict[str, Any]):
    """TC-S40-08: Danh sách chuyến và xem chi tiết theo phân quyền."""
    data = setup_s40_test_data
    b1 = data["batch_1_id"]

    # Tạo 1 chuyến
    c_res = client.post(
        "/trips",
        json={"trip_code": "TRIP-VIEW-01", "container_code": "BOX-VIEW", "batch_ids": [b1]},
        auth=(data["u_transporter"], PASSWORD),
    )
    trip_id = c_res.json()["id"]

    # Transporter xem danh sách -> Thấy 1 chuyến
    list_res = client.get("/trips", auth=(data["u_transporter"], PASSWORD))
    assert list_res.status_code == 200
    trips = list_res.json()
    assert any(t["id"] == trip_id for t in trips)

    # Inspector xem danh sách -> Thấy chuyến liên tổ chức
    insp_res = client.get("/trips", auth=(data["u_inspector"], PASSWORD))
    assert insp_res.status_code == 200
    assert any(t["id"] == trip_id for t in insp_res.json())

    # Xem chi tiết chuyến
    detail_res = client.get(f"/trips/{trip_id}", auth=(data["u_transporter"], PASSWORD))
    assert detail_res.status_code == 200
    d_data = detail_res.json()
    assert d_data["trip_code"] == "TRIP-VIEW-01"
    assert len(d_data["batches"]) == 1
    assert d_data["batches"][0]["batch_id"] == b1


def test_find_active_trip_by_container_api(client: TestClient, setup_s40_test_data: dict[str, Any]):
    """TC-S40-09: Endpoint tra cứu chuyến xe đang chạy theo thùng lạnh (Hỗ trợ S-41)."""
    data = setup_s40_test_data
    b2 = data["batch_2_id"]

    # Chưa có chuyến nào chạy thùng CONT-SENSOR-01 -> 404
    r404 = client.get("/trips/active-container/CONT-SENSOR-01", auth=(data["u_transporter"], PASSWORD))
    assert r404.status_code == 404

    # Tạo chuyến với thùng CONT-SENSOR-01
    client.post(
        "/trips",
        json={"container_code": "CONT-SENSOR-01", "batch_ids": [b2]},
        auth=(data["u_transporter"], PASSWORD),
    )

    # Tra cứu lại -> 200 OK
    r200 = client.get("/trips/active-container/CONT-SENSOR-01", auth=(data["u_transporter"], PASSWORD))
    assert r200.status_code == 200
    assert r200.json()["container_code"] == "CONT-SENSOR-01"
    assert r200.json()["status"] == "IN_TRANSIT"


def test_create_trip_batch_has_pending_handover(
    client: TestClient, setup_s40_test_data: dict[str, Any], session_factory: sessionmaker[Session]
):
    """TC-S40-10: Chặn mở chuyến nếu lô đang có yêu cầu bàn giao chờ xác nhận (PENDING)."""
    data = setup_s40_test_data
    b1 = data["batch_1_id"]

    with session_factory() as session:
        ho = Handover(
            batch_id=b1,
            from_org_id=data["org_trans_id"],
            to_org_id=data["org_farm_id"],
            status=HANDOVER_PENDING,
        )
        session.add(ho)
        session.commit()

    res = client.post(
        "/trips",
        json={"container_code": "BOX-HANDOVER-TEST", "batch_ids": [b1]},
        auth=(data["u_transporter"], PASSWORD),
    )
    assert res.status_code == 400
    assert "chờ duyệt" in res.json()["detail"] or "bàn giao" in res.json()["detail"]


def test_create_trip_batch_consumed(
    client: TestClient, setup_s40_test_data: dict[str, Any], session_factory: sessionmaker[Session]
):
    """TC-S40-11: Chặn mở chuyến nếu lô đã tiêu thụ hết (CONSUMED)."""
    data = setup_s40_test_data
    b1 = data["batch_1_id"]

    with session_factory() as session:
        batch = session.get(Batch, b1)
        batch.status = "CONSUMED"
        batch.remaining_quantity = 0.0
        session.commit()

    res = client.post(
        "/trips",
        json={"container_code": "BOX-CONSUMED", "batch_ids": [b1]},
        auth=(data["u_transporter"], PASSWORD),
    )
    assert res.status_code == 400
    assert "CONSUMED" in res.json()["detail"] or "tiêu thụ" in res.json()["detail"]


def test_complete_trip_forbidden_and_double_complete(client: TestClient, setup_s40_test_data: dict[str, Any]):
    """TC-S40-12: Chặn hoàn thành chuyến của tổ chức khác và chặn hoàn thành 2 lần."""
    data = setup_s40_test_data
    b2 = data["batch_2_id"]

    # 1. Mở chuyến bởi Org 2
    create_res = client.post(
        "/trips",
        json={"container_code": "CONT-DOUBLE", "batch_ids": [b2]},
        auth=(data["u_transporter"], PASSWORD),
    )
    assert create_res.status_code == 201
    trip_id = create_res.json()["id"]

    # 2. Distributor (Org 3) cố hoàn thành chuyến -> 403 Forbidden
    comp_other = client.post(
        f"/trips/{trip_id}/complete",
        json={"notes": "Thử hoàn thành trái phép"},
        auth=(data["u_distributor"], PASSWORD),
    )
    assert comp_other.status_code == 403

    # 3. Transporter (Org 2) hoàn thành lần 1 -> 200 OK
    comp_ok = client.post(
        f"/trips/{trip_id}/complete",
        auth=(data["u_transporter"], PASSWORD),
    )
    assert comp_ok.status_code == 200

    # 4. Transporter cố hoàn thành lần 2 -> 400 Bad Request
    comp_again = client.post(
        f"/trips/{trip_id}/complete",
        auth=(data["u_transporter"], PASSWORD),
    )
    assert comp_again.status_code == 400
    assert "COMPLETED" in comp_again.json()["detail"]


def test_batch_reusability_across_multiple_trips(
    client: TestClient,
    setup_s40_test_data: dict[str, Any],
    session_factory: sessionmaker[Session],
) -> None:
    """TC-S40-13: Lô A tham gia Chuyến 1 -> Hoàn thành -> Lô A tham gia Chuyến 2 thành công,

    lịch sử cả 2 chuyến tồn tại và Hash-Chain hợp lệ (Yêu cầu 4).
    """
    data = setup_s40_test_data
    b1 = data["batch_1_id"]

    # 1. Lô A tham gia chuyến 1
    res1 = client.post(
        "/trips",
        json={
            "container_code": "CONT-CYCLE-01",
            "trip_code": "TRIP-CYCLE-01",
            "batch_ids": [b1],
            "notes": "Chặng 1: Tân Cương đến Kho trung chuyển",
        },
        auth=(data["u_transporter"], PASSWORD),
    )
    assert res1.status_code == 201
    trip1_id = res1.json()["id"]

    # 2. Hoàn thành chuyến 1
    comp1 = client.post(
        f"/trips/{trip1_id}/complete",
        json={"notes": "Đã hạ hàng tại kho trung chuyển"},
        auth=(data["u_transporter"], PASSWORD),
    )
    assert comp1.status_code == 200
    assert comp1.json()["status"] == "COMPLETED"

    # 3. Lô A tiếp tục tham gia chuyến 2 (với thùng lạnh khác hoặc cùng thùng)
    res2 = client.post(
        "/trips",
        json={
            "container_code": "CONT-CYCLE-02",
            "trip_code": "TRIP-CYCLE-02",
            "batch_ids": [b1],
            "notes": "Chặng 2: Kho trung chuyển đến Điểm phân phối",
        },
        auth=(data["u_transporter"], PASSWORD),
    )
    assert res2.status_code == 201
    trip2_id = res2.json()["id"]
    assert res2.json()["status"] == "IN_TRANSIT"

    # 4. Xác minh lịch sử của cả 2 chuyến đều tồn tại độc lập
    with session_factory() as session:
        t1 = session.get(ColdTrip, trip1_id)
        t2 = session.get(ColdTrip, trip2_id)
        assert t1 is not None and t1.status == "COMPLETED"
        assert t2 is not None and t2.status == "IN_TRANSIT"

        # Lô A có 2 liên kết lịch sử trong cold_trip_batches
        links = session.query(ColdTripBatch).filter(ColdTripBatch.batch_id == b1).order_by(ColdTripBatch.id.asc()).all()
        assert len(links) == 2
        assert links[0].trip_id == trip1_id and links[0].detached_at is not None
        assert links[1].trip_id == trip2_id and links[1].detached_at is None

        # 5. Kiểm tra Hash-Chain của Lô A hoàn toàn hợp lệ
        chain_res = verify_batch_chain(session, b1)
        assert chain_res["is_valid"] is True

        # Kiểm tra 3 sự kiện vận chuyển theo thứ tự thời gian
        events = session.query(BatchEvent).filter(
            BatchEvent.batch_id == b1,
            BatchEvent.event_type.in_(["TRIP_DISPATCH", "TRIP_DELIVER"]),
        ).order_by(BatchEvent.id.asc()).all()
        assert len(events) == 3
        assert events[0].event_type == "TRIP_DISPATCH"
        assert events[1].event_type == "TRIP_DELIVER"
        assert events[2].event_type == "TRIP_DISPATCH"


def test_trip_cancellation_releases_batch_and_container(
    client: TestClient,
    setup_s40_test_data: dict[str, Any],
) -> None:
    """TC-S40-14: Hủy chuyến xe (CANCELLED) giải phóng thùng lạnh và lô hàng (Yêu cầu 3)."""
    data = setup_s40_test_data
    b2 = data["batch_2_id"]

    # 1. Tạo chuyến
    create_res = client.post(
        "/trips",
        json={"container_code": "CONT-CANCEL-TEST", "batch_ids": [b2]},
        auth=(data["u_transporter"], PASSWORD),
    )
    assert create_res.status_code == 201
    trip_id = create_res.json()["id"]

    # 2. Hủy chuyến
    cancel_res = client.post(
        f"/trips/{trip_id}/cancel",
        json={"notes": "Hủy chuyến do xe gặp sự cố kỹ thuật"},
        auth=(data["u_transporter"], PASSWORD),
    )
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "CANCELLED"

    # 3. Lô và thùng lạnh được giải phóng, có thể mở chuyến mới ngay lập tức
    reopen_res = client.post(
        "/trips",
        json={"container_code": "CONT-CANCEL-TEST", "batch_ids": [b2]},
        auth=(data["u_transporter"], PASSWORD),
    )
    assert reopen_res.status_code == 201
    assert reopen_res.json()["status"] == "IN_TRANSIT"


def test_sqlite_partial_unique_index_active_container_engine_level(
    session_factory: sessionmaker[Session],
    setup_s40_test_data: dict[str, Any],
) -> None:
    """TC-S40-15: Xác nhận Partial Unique Index uq_cold_trips_active_container.

    Hoạt động ở tầng SQLite engine, ngăn chặn container trùng lặp (Yêu cầu 1 & 5).
    """
    data = setup_s40_test_data
    with session_factory() as session:
        # 1. Insert chuyến 1 IN_TRANSIT với container CONT-ENG-1
        session.execute(
            text(
                "INSERT INTO cold_trips (trip_code, container_code, transporter_org_id, status, "
                "created_by_user_id, start_time, created_at, updated_at) "
                "VALUES ('TRIP-ENG-1', 'CONT-ENG-1', :org, 'IN_TRANSIT', :user, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"org": data["org_trans_id"], "user": data["u_trans_id"]},
        )
        session.commit()

        # 2. Cố tình bypass Python checks, insert trực tiếp chuyến 2 cùng container CONT-ENG-1 ở trạng thái IN_TRANSIT
        with pytest.raises(IntegrityError) as exc_info:
            session.execute(
                text(
                    "INSERT INTO cold_trips (trip_code, container_code, transporter_org_id, status, "
                    "created_by_user_id, start_time, created_at, updated_at) "
                    "VALUES ('TRIP-ENG-2', 'CONT-ENG-1', :org, 'IN_TRANSIT', :user, "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"org": data["org_trans_id"], "user": data["u_trans_id"]},
            )
            session.commit()
        session.rollback()
        assert "UNIQUE constraint failed" in str(exc_info.value)
        assert "container_code" in str(exc_info.value) or "uq_cold_trips_active_container" in str(exc_info.value)

        # 3. Insert chuyến 3 cùng container CONT-ENG-1 nhưng COMPLETED -> Thành công
        session.execute(
            text(
                "INSERT INTO cold_trips (trip_code, container_code, transporter_org_id, status, "
                "created_by_user_id, start_time, created_at, updated_at) "
                "VALUES ('TRIP-ENG-3', 'CONT-ENG-1', :org, 'COMPLETED', :user, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"org": data["org_trans_id"], "user": data["u_trans_id"]},
        )
        session.commit()


def test_sqlite_partial_unique_index_active_batch_engine_level(
    session_factory: sessionmaker[Session],
    setup_s40_test_data: dict[str, Any],
) -> None:
    """TC-S40-16: Xác nhận Partial Unique Index uq_cold_trip_batches_active_batch.

    Hoạt động ở tầng SQLite engine, ngăn chặn batch đang trên xe bị gán chuyến khác (Yêu cầu 2 & 5).
    """
    data = setup_s40_test_data
    b1 = data["batch_1_id"]

    with session_factory() as session:
        # Tạo 2 trip khác nhau
        session.execute(
            text(
                "INSERT INTO cold_trips (id, trip_code, container_code, transporter_org_id, status, "
                "created_by_user_id, start_time, created_at, updated_at) "
                "VALUES (101, 'TRIP-BT-1', 'CONT-BT-1', :org, 'IN_TRANSIT', :user, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"org": data["org_trans_id"], "user": data["u_trans_id"]},
        )
        session.execute(
            text(
                "INSERT INTO cold_trips (id, trip_code, container_code, transporter_org_id, status, "
                "created_by_user_id, start_time, created_at, updated_at) "
                "VALUES (102, 'TRIP-BT-2', 'CONT-BT-2', :org, 'IN_TRANSIT', :user, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"org": data["org_trans_id"], "user": data["u_trans_id"]},
        )
        session.commit()

        # 1. Gán lô b1 vào trip 101 với detached_at IS NULL (đang trên xe)
        session.execute(
            text(
                "INSERT INTO cold_trip_batches (trip_id, batch_id, attached_at, detached_at) "
                "VALUES (101, :b, CURRENT_TIMESTAMP, NULL)"
            ),
            {"b": b1},
        )
        session.commit()

        # 2. Cố tình bypass Python checks, insert tiếp lô b1 vào trip 102 với detached_at IS NULL -> Bị SQLite chặn
        with pytest.raises(IntegrityError) as exc_info:
            session.execute(
                text(
                    "INSERT INTO cold_trip_batches (trip_id, batch_id, attached_at, detached_at) "
                    "VALUES (102, :b, CURRENT_TIMESTAMP, NULL)"
                ),
                {"b": b1},
            )
            session.commit()
        session.rollback()
        assert "UNIQUE constraint failed" in str(exc_info.value)
        assert "batch_id" in str(exc_info.value) or "uq_cold_trip_batches_active_batch" in str(exc_info.value)


def test_concurrent_trip_creation_race_condition(
    setup_s40_test_data: dict[str, Any],
    session_factory: sessionmaker[Session],
) -> None:
    """TC-S40-17: Giả lập 2 luồng đồng thời tạo chuyến trùng container/batch.

    Xác minh chỉ đúng 1 chuyến thành công và ràng buộc DB loại bỏ race condition (Yêu cầu 5).
    """
    from concurrent.futures import ThreadPoolExecutor
    from app.schemas_trips import TripCreate
    from app.services.trips import create_cold_trip

    data = setup_s40_test_data
    b1 = data["batch_1_id"]

    results = []

    def try_create(thread_id: int):
        with session_factory() as s:
            user = s.get(User, data["u_trans_id"])
            payload = TripCreate(
                container_code="CONT-RACE-TEST",
                trip_code=f"TRIP-RACE-{thread_id}",
                batch_ids=[b1],
            )
            try:
                trip = create_cold_trip(s, user, payload)
                return {"success": True, "trip_id": trip.id}
            except Exception as e:
                return {"success": False, "error": str(e)}

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(try_create, 1)
        f2 = executor.submit(try_create, 2)
        results = [f1.result(), f2.result()]

    successes = [r for r in results if r["success"]]
    failures = [r for r in results if not r["success"]]

    assert len(successes) == 1, f"Expected exactly 1 success, got {len(successes)}: {results}"
    assert len(failures) == 1, f"Expected exactly 1 failure, got {len(failures)}: {results}"


def test_security_active_container_rbac_and_org_scope(
    client: TestClient,
    setup_s40_test_data: dict[str, Any],
    session_factory: sessionmaker[Session],
) -> None:
    """TC-S40-18: Kiểm tra an toàn phân quyền tra cứu chuyến theo container (RBAC & Org Scope).

    - Transporter A mở chuyến với container CONT-ORG-A.
    - Transporter B tra cứu CONT-ORG-A -> Bị từ chối 403 Forbidden.
    - Farmer tra cứu CONT-ORG-A -> Bị từ chối 403 Forbidden.
    - Distributor tra cứu CONT-ORG-A -> Bị từ chối 403 Forbidden.
    - Inspector tra cứu CONT-ORG-A -> Thành công 200 OK.
    - Transporter A tra cứu CONT-ORG-A -> Thành công 200 OK.
    """
    data = setup_s40_test_data
    b1 = data["batch_1_id"]

    # 1. Tạo tổ chức vận chuyển thứ 2 (Org Trans B) và user Transporter B
    with session_factory() as session:
        org_trans_b = Organization(
            name="Logistics Nam Định (Transporter B)",
            code="LOG-ND",
            description="Đơn vị vận chuyển đối thủ",
        )
        session.add(org_trans_b)
        session.flush()

        u_trans_b = User(
            username="trans_nd",
            password=hash_password(PASSWORD),
            role=ROLE_TRANSPORTER,
            organization_id=org_trans_b.id,
        )
        session.add(u_trans_b)
        session.commit()

    # 2. Transporter A tạo chuyến xe với container CONT-ORG-A
    create_res = client.post(
        "/trips",
        json={"container_code": "CONT-ORG-A", "batch_ids": [b1]},
        auth=(data["u_transporter"], PASSWORD),
    )
    assert create_res.status_code == 201

    # 3. Transporter B tra cứu container của Transporter A -> Bị từ chối 403
    res_b = client.get("/trips/active-container/CONT-ORG-A", auth=("trans_nd", PASSWORD))
    assert res_b.status_code == 403
    assert "tổ chức khác" in res_b.json()["detail"]

    # 4. Farmer tra cứu container của Transporter A -> Bị từ chối 403
    res_farm = client.get("/trips/active-container/CONT-ORG-A", auth=(data["u_farmer"], PASSWORD))
    assert res_farm.status_code == 403

    # 5. Distributor tra cứu container của Transporter A -> Bị từ chối 403
    res_dist = client.get("/trips/active-container/CONT-ORG-A", auth=(data["u_distributor"], PASSWORD))
    assert res_dist.status_code == 403

    # 6. Inspector tra cứu container theo quyền thanh tra -> Thành công 200 OK
    res_insp = client.get("/trips/active-container/CONT-ORG-A", auth=(data["u_inspector"], PASSWORD))
    assert res_insp.status_code == 200
    assert res_insp.json()["container_code"] == "CONT-ORG-A"

    # 7. Transporter A chính chủ tra cứu -> Thành công 200 OK
    res_a = client.get("/trips/active-container/CONT-ORG-A", auth=(data["u_transporter"], PASSWORD))
    assert res_a.status_code == 200
    assert res_a.json()["container_code"] == "CONT-ORG-A"


def test_security_trip_detail_batch_scoping_and_data_masking(
    client: TestClient,
    setup_s40_test_data: dict[str, Any],
    session_factory: sessionmaker[Session],
) -> None:
    """TC-S40-19: Kiểm tra phân quyền dữ liệu trả về của get_cold_trip_detail.

    - Chuyến xe chở 2 lô: Batch 1 (Farmer có quyền phả hệ) và Batch 2 (lô độc quyền của Transporter).
    - Farmer gọi xem chuyến: Chỉ nhận thông tin Batch 1, Batch 2 bị lọc bỏ.
    - Thông tin tài xế, biển số xe, ghi chú nội bộ bị ẩn (None) với Farmer.
    - Tổ chức bên ngoài không có lô nào trên xe (Transporter B, Distributor) gọi xem: 403 Forbidden.
    - Đơn vị vận chuyển chuyến xe (Transporter A) và Inspector: Nhận đầy đủ 2 lô và dữ liệu chuyến.
    """
    data = setup_s40_test_data
    b1 = data["batch_1_id"]
    b2 = data["batch_2_id"]

    # Thiết lập quan hệ bàn giao để Farmer có quyền xem b1 (nhưng KHÔNG có quyền xem b2)
    with session_factory() as session:
        ho = Handover(
            batch_id=b1,
            from_org_id=data["org_farm_id"],
            to_org_id=data["org_trans_id"],
            status=HANDOVER_ACCEPTED,
        )
        session.add(ho)

        # Tạo thêm user Transporter B không có lô nào trên xe
        org_b = Organization(name="Vận tải B", code="TRANS-B", description="Bên thứ ba")
        session.add(org_b)
        session.flush()
        u_b = User(
            username="user_trans_b",
            password=hash_password(PASSWORD),
            role=ROLE_TRANSPORTER,
            organization_id=org_b.id,
        )
        session.add(u_b)
        session.commit()

    # Transporter A mở chuyến chở cả 2 lô kèm thông tin tài xế và ghi chú nội bộ
    trip_payload = {
        "trip_code": "TRIP-SEC-DETAIL-01",
        "container_code": "CONT-SEC-DETAIL",
        "batch_ids": [b1, b2],
        "driver_name": "Nguyễn Văn Bảo Mật",
        "vehicle_plate": "29C-888.99",
        "notes": "Thông tin điều phối nội bộ không được tiết lộ",
    }
    c_res = client.post("/trips", json=trip_payload, auth=(data["u_transporter"], PASSWORD))
    assert c_res.status_code == 201
    trip_id = c_res.json()["id"]

    # 1. Farmer (chỉ có quyền xem b1) gọi GET /trips/{id}
    farmer_res = client.get(f"/trips/{trip_id}", auth=(data["u_farmer"], PASSWORD))
    assert farmer_res.status_code == 200
    farmer_data = farmer_res.json()

    # Xác nhận: Chỉ chứa duy nhất lô b1, không tiết lộ lô b2
    returned_batch_ids = [b["batch_id"] for b in farmer_data["batches"]]
    assert returned_batch_ids == [b1]
    assert farmer_data["batch_count"] == 1

    # Xác nhận: Thông tin tài xế, biển số và ghi chú bị ẩn đối với bên ngoài
    assert farmer_data["driver_name"] is None
    assert farmer_data["vehicle_plate"] is None
    assert farmer_data["notes"] is None
    assert farmer_data["batches"][0]["notes"] is None

    # 2. Bên ngoài không có lô nào trên xe (Transporter B) gọi -> 403 Forbidden
    res_b = client.get(f"/trips/{trip_id}", auth=("user_trans_b", PASSWORD))
    assert res_b.status_code == 403

    # 3. Distributor không có lô nào trên xe gọi -> 403 Forbidden
    res_dist = client.get(f"/trips/{trip_id}", auth=(data["u_distributor"], PASSWORD))
    assert res_dist.status_code == 403

    # 4. Transporter A (đơn vị vận chuyển chuyến) gọi -> Nhận đầy đủ 2 lô và thông tin
    res_trans = client.get(f"/trips/{trip_id}", auth=(data["u_transporter"], PASSWORD))
    assert res_trans.status_code == 200
    trans_data = res_trans.json()
    assert len(trans_data["batches"]) == 2
    assert trans_data["driver_name"] == "Nguyễn Văn Bảo Mật"
    assert trans_data["vehicle_plate"] == "29C-888.99"
    assert trans_data["notes"] == "Thông tin điều phối nội bộ không được tiết lộ"

    # 5. Inspector gọi -> Nhận đầy đủ 2 lô và thông tin
    res_insp = client.get(f"/trips/{trip_id}", auth=(data["u_inspector"], PASSWORD))
    assert res_insp.status_code == 200
    insp_data = res_insp.json()
    assert len(insp_data["batches"]) == 2
    assert insp_data["driver_name"] == "Nguyễn Văn Bảo Mật"
