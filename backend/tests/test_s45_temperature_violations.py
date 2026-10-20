"""Bộ kiểm thử toàn diện cho User Story S-45:
"Ghi sự kiện vi phạm nhiệt độ vào nhật ký sự kiện của từng lô và tích hợp hệ thống".

Bao phủ các ca kiểm thử:
1. Ghi nhận vi phạm nhiệt độ cho chuyến xe có nhiều lô -> tự động lan truyền sự kiện
   TEMPERATURE_VIOLATION vào Cryptographic Hash-Chain của mọi lô đang trên chuyến.
2. Xác minh tính toàn vẹn chuỗi khối (Cryptographic Hash Chain Integrity) của từng lô sau sự cố.
3. Cập nhật cờ cảnh báo `has_temperature_violation = True` và tăng `temperature_violation_count` trên Batch.
4. Ghi nhận đầy đủ nhật ký kiểm toán (AuditLog) cho cả chuyến xe và từng lô nông sản.
5. Hiển thị sự kiện vi phạm trên dòng thời gian Timeline của lô (GET /batches/{id}/events)
   kèm thời lượng (duration) và nhiệt độ đỉnh (peak temperature).
6. Bàn giao lô hàng có vi phạm (GET /handovers/pending) -> hiển thị cờ cảnh báo cho bên nhận trước khi nhận.
7. Phân quyền RBAC khi ghi nhận vi phạm (Transporter chuyến, Inspector, Admin; chặn tổ chức khác).
8. Thuật toán phát hiện vi phạm theo S-43: kéo dài >= 30 phút, gộp 2 lần vượt cách nhau < 5 phút.
9. Thu thập số đo cảm biến theo S-41: bỏ qua số đo cũ hơn hoặc trùng thời gian.
10. API tra cứu vi phạm của chuyến và của lô (GET /trips/{id}/violations, GET /batches/{id}/violations).
"""

import base64
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.hash_chain import verify_batch_chain
from app.models import (
    AuditLog,
    Batch,
    BatchEvent,
    Farm,
    Organization,
    Product,
    ROLE_DISTRIBUTOR,
    ROLE_FARMER,
    ROLE_INSPECTOR,
    ROLE_ORG_ADMIN,
    ROLE_SYSTEM_ADMIN,
    ROLE_TRANSPORTER,
    User,
)
from app.security import hash_password
from app.services.cold_chain import (
    detect_violations_from_readings,
    record_temperature_violation_for_trip,
)
from app.trip_models import (
    EVENT_TEMPERATURE_VIOLATION,
    TemperatureViolation,
    EVENT_TRIP_DISPATCH,
    TRIP_STATUS_IN_TRANSIT,
    ColdTrip,
    ColdTripBatch,
)

PASSWORD = "test-password-123"


def _auth_header(username: str) -> dict[str, str]:
    credentials = f"{username}:{PASSWORD}"
    encoded = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
    return {"Authorization": f"Basic {encoded}"}


@pytest.fixture()
def setup_s45_data(session_factory: sessionmaker[Session]) -> dict[str, Any]:
    """Khởi tạo môi trường dữ liệu chuẩn cho S-45:

    - Org 1: Nông trại (Farmer)
    - Org 2: Vận tải Logistics (Transporter, Transporter Admin)
    - Org 3: Nhà phân phối (Distributor)
    - Org 4: Đơn vị vận tải khác (Other Transporter)
    - Inspector (Thanh tra viên) & System Admin
    - 2 Lô nông sản thuộc Org 2 (đang chở trên chuyến xe TRIP-01, thùng CONT-COLD-01)
    - 1 Lô nông sản độc lập thuộc Org 1 (ở kho trang trại)
    """
    with session_factory() as session:
        org_farm = Organization(name="HTX Nông trại Xanh", code="ORG-FARM", description="Trang trại")
        org_trans = Organization(name="Logistics Lạnh Hà Nội", code="ORG-TRANS", description="Vận tải chuỗi lạnh")
        org_dist = Organization(name="Phân phối Thực phẩm An Toàn", code="ORG-DIST", description="Nhà phân phối")
        org_other_trans = Organization(name="Vận tải Miền Trung", code="ORG-TRANS2", description="Vận tải khác")
        session.add_all([org_farm, org_trans, org_dist, org_other_trans])
        session.flush()

        u_farmer = User(
            username="farmer_s45", password=hash_password(PASSWORD), role=ROLE_FARMER, organization_id=org_farm.id
        )
        u_transporter = User(
            username="trans_s45", password=hash_password(PASSWORD), role=ROLE_TRANSPORTER, organization_id=org_trans.id
        )
        u_trans_admin = User(
            username="trans_admin_s45", password=hash_password(PASSWORD), role=ROLE_ORG_ADMIN, organization_id=org_trans.id
        )
        u_other_trans = User(
            username="other_trans_s45",
            password=hash_password(PASSWORD),
            role=ROLE_TRANSPORTER,
            organization_id=org_other_trans.id,
        )
        u_distributor = User(
            username="dist_s45", password=hash_password(PASSWORD), role=ROLE_DISTRIBUTOR, organization_id=org_dist.id
        )
        u_inspector = User(
            username="inspector_s45", password=hash_password(PASSWORD), role=ROLE_INSPECTOR, organization_id=org_farm.id
        )
        u_sysadmin = User(
            username="sysadmin_s45", password=hash_password(PASSWORD), role=ROLE_SYSTEM_ADMIN, organization_id=org_trans.id
        )
        session.add_all([
            u_farmer, u_transporter, u_trans_admin, u_other_trans,
            u_distributor, u_inspector, u_sysadmin
        ])
        session.flush()

        prod = Product(name="Thịt bò mát cao cấp", unit="kg")
        farm = Farm(
            name="Trang trại chăn nuôi Thái Nguyên",
            location="Thái Nguyên",
            area=10.0,
            owner="HTX Xanh",
            organization_id=org_farm.id,
        )
        session.add_all([prod, farm])
        session.flush()

        batch_1 = Batch(
            code="BATCH-S45-A",
            plot_id=farm.id,
            product_id=prod.id,
            harvest_date=date.today(),
            initial_quantity=400.0,
            remaining_quantity=400.0,
            current_org_id=org_trans.id,
            status="ACTIVE",
        )
        batch_2 = Batch(
            code="BATCH-S45-B",
            plot_id=farm.id,
            product_id=prod.id,
            harvest_date=date.today(),
            initial_quantity=250.0,
            remaining_quantity=250.0,
            current_org_id=org_trans.id,
            status="ACTIVE",
        )
        batch_farm = Batch(
            code="BATCH-S45-FARM",
            plot_id=farm.id,
            product_id=prod.id,
            harvest_date=date.today(),
            initial_quantity=100.0,
            remaining_quantity=100.0,
            current_org_id=org_farm.id,
            status="ACTIVE",
        )
        session.add_all([batch_1, batch_2, batch_farm])
        session.flush()

        # Tạo chuyến xe lạnh đang chạy chở Batch 1 và Batch 2
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        trip = ColdTrip(
            trip_code="TRIP-S45-001",
            container_code="CONT-COLD-99",
            transporter_org_id=org_trans.id,
            status=TRIP_STATUS_IN_TRANSIT,
            driver_name="Nguyễn Văn Lái",
            vehicle_plate="29C-999.88",
            start_location="Kho Lạnh Thái Nguyên",
            destination_location="Siêu thị Hà Nội",
            start_time=now - timedelta(hours=3),
            created_by_user_id=u_transporter.id,
            created_at=now - timedelta(hours=3),
            updated_at=now - timedelta(hours=3),
        )
        session.add(trip)
        session.flush()

        tb1 = ColdTripBatch(trip_id=trip.id, batch_id=batch_1.id, attached_at=now - timedelta(hours=3))
        tb2 = ColdTripBatch(trip_id=trip.id, batch_id=batch_2.id, attached_at=now - timedelta(hours=3))
        session.add_all([tb1, tb2])

        # Ghi sự kiện TRIP_DISPATCH ban đầu cho 2 lô
        from app.hash_chain import record_event
        for b in (batch_1, batch_2):
            record_event(
                db=session,
                batch_id=b.id,
                event_type=EVENT_TRIP_DISPATCH,
                payload={
                    "trip_id": trip.id,
                    "trip_code": trip.trip_code,
                    "container_code": trip.container_code,
                    "action": EVENT_TRIP_DISPATCH,
                    "description": f"Khởi hành chuyến lạnh {trip.trip_code}",
                },
                org_id=org_trans.id,
                user_id=u_transporter.id,
                event_data=f"Khởi hành chuyến lạnh {trip.trip_code}",
            )

        u_transporter_id = u_transporter.id
        u_farmer_id = u_farmer.id
        u_trans_admin_id = u_trans_admin.id
        u_other_trans_id = u_other_trans.id
        u_distributor_id = u_distributor.id
        u_inspector_id = u_inspector.id
        u_sysadmin_id = u_sysadmin.id
        org_farm_id = org_farm.id
        org_trans_id = org_trans.id
        org_dist_id = org_dist.id
        org_other_trans_id = org_other_trans.id
        b1_id = batch_1.id
        b2_id = batch_2.id
        bf_id = batch_farm.id
        t_id = trip.id
        c_code = trip.container_code

        session.commit()

        return {
            "org_farm_id": org_farm_id,
            "org_trans_id": org_trans_id,
            "dist_org_id": org_dist_id,
            "org_other_trans_id": org_other_trans_id,
            "u_farmer_id": u_farmer_id,
            "u_transporter_id": u_transporter_id,
            "u_trans_admin_id": u_trans_admin_id,
            "u_other_trans_id": u_other_trans_id,
            "u_distributor_id": u_distributor_id,
            "u_inspector_id": u_inspector_id,
            "u_sysadmin_id": u_sysadmin_id,
            "batch_1_id": b1_id,
            "batch_2_id": b2_id,
            "batch_farm_id": bf_id,
            "trip_id": t_id,
            "container_code": c_code,
        }


def test_tc_s45_01_record_trip_violation_propagates_to_all_batches(
    session_factory: sessionmaker[Session],
    setup_s45_data: dict[str, Any],
) -> None:
    """TC-S45-01: Ghi nhận vi phạm nhiệt độ cho chuyến xe có 2 lô:

    - Tự động ghi sự kiện TEMPERATURE_VIOLATION vào hash-chain của CẢ 2 LÔ.
    - Cập nhật cờ has_temperature_violation = True và tăng temperature_violation_count.
    - Ghi nhận AuditLog cho cả chuyến xe và 2 lô hàng.
    """
    trip_id = setup_s45_data["trip_id"]
    batch_1_id = setup_s45_data["batch_1_id"]
    batch_2_id = setup_s45_data["batch_2_id"]

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    start_time = now - timedelta(minutes=45)
    end_time = now

    with session_factory() as session:
        u_trans = session.get(User, setup_s45_data["u_transporter_id"])
        from app.schemas_trips import TemperatureViolationCreate

        payload = TemperatureViolationCreate(
            start_time=start_time,
            end_time=end_time,
            duration_minutes=45.0,
            peak_temperature=14.5,
            threshold_temperature=8.0,
            min_threshold=2.0,
            max_threshold=8.0,
            violation_type="PROLONGED_HEAT",
            notes="Hỏng dàn lạnh trên cao tốc, kéo dài 45 phút",
        )

        violation = record_temperature_violation_for_trip(session, trip_id, payload, user=u_trans)

        assert violation.id is not None
        assert violation.trip_id == trip_id
        assert violation.peak_temperature == 14.5
        assert violation.duration_minutes == 45.0
        assert violation.severity == "CRITICAL"  # >= 30 mins
        assert violation.status == "RESOLVED"
        assert set(violation.affected_batch_ids) == {batch_1_id, batch_2_id}

    # Kiểm tra trạng thái và hash-chain của từng lô
    with session_factory() as session:
        b1 = session.get(Batch, batch_1_id)
        b2 = session.get(Batch, batch_2_id)

        assert b1.has_temperature_violation is True
        assert b1.temperature_violation_count == 1
        assert b2.has_temperature_violation is True
        assert b2.temperature_violation_count == 1

        # Kiểm tra sự kiện TEMPERATURE_VIOLATION được ghi vào bảng batch_events
        ev1 = session.scalar(
            select(BatchEvent)
            .where(
                BatchEvent.batch_id == batch_1_id,
                BatchEvent.event_type == EVENT_TEMPERATURE_VIOLATION,
            )
        )
        assert ev1 is not None
        assert ev1.payload["peak_temperature"] == 14.5
        assert ev1.payload["duration_minutes"] == 45.0
        assert ev1.payload["threshold_temperature"] == 8.0
        assert ev1.payload["severity"] == "CRITICAL"
        assert ev1.payload["trip_code"] == "TRIP-S45-001"
        assert "vi phạm nhiệt độ" in ev1.payload["description"].lower()

        ev2 = session.scalar(
            select(BatchEvent)
            .where(
                BatchEvent.batch_id == batch_2_id,
                BatchEvent.event_type == EVENT_TEMPERATURE_VIOLATION,
            )
        )
        assert ev2 is not None
        assert ev2.payload["peak_temperature"] == 14.5
        assert ev2.payload["duration_minutes"] == 45.0

        # Kiểm tra AuditLog được ghi lại
        logs = list(
            session.scalars(
                select(AuditLog).where(
                    AuditLog.action == "update",
                    AuditLog.entity.in_(["batch", "cold_trip"]),
                )
            ).all()
        )
        assert len(logs) >= 3  # 1 cho cold_trip + 2 cho 2 batches


def test_tc_s45_02_hash_chain_integrity_preserved(
    session_factory: sessionmaker[Session],
    setup_s45_data: dict[str, Any],
) -> None:
    """TC-S45-02: Xác thực tính toàn vẹn Cryptographic Hash Chain sau khi ghi vi phạm:

    - Hàm verify_batch_chain trả về is_valid = True.
    - prev_hash của sự kiện vi phạm liên kết chính xác với current_hash của sự kiện TRIP_DISPATCH trước đó.
    """
    trip_id = setup_s45_data["trip_id"]
    batch_1_id = setup_s45_data["batch_1_id"]

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with session_factory() as session:
        u_trans = session.get(User, setup_s45_data["u_transporter_id"])
        from app.schemas_trips import TemperatureViolationCreate

        payload = TemperatureViolationCreate(
            start_time=now - timedelta(minutes=35),
            end_time=now,
            duration_minutes=35.0,
            peak_temperature=12.0,
            threshold_temperature=8.0,
        )
        record_temperature_violation_for_trip(session, trip_id, payload, user=u_trans)

        # Kiểm tra tính toàn vẹn hash chain
        res = verify_batch_chain(session, batch_1_id)
        assert res["is_valid"] is True
        assert res["batch_id"] == batch_1_id

        # Kiểm tra chi tiết 2 sự kiện: TRIP_DISPATCH -> TEMPERATURE_VIOLATION
        events = list(
            session.scalars(
                select(BatchEvent)
                .where(BatchEvent.batch_id == batch_1_id)
                .order_by(BatchEvent.id.asc())
            ).all()
        )
        assert len(events) == 2
        assert events[0].event_type == EVENT_TRIP_DISPATCH
        assert events[1].event_type == EVENT_TEMPERATURE_VIOLATION
        assert events[1].prev_hash == events[0].current_hash


def test_tc_s45_03_api_create_trip_violation(
    client: TestClient,
    setup_s45_data: dict[str, Any],
) -> None:
    """TC-S45-03: Kiểm thử endpoint POST /trips/{trip_id}/violations:

    - Ghi nhận thành công qua HTTP API, trả về HTTP 201 Created.
    - Response đầy đủ thông tin: id, duration_minutes, peak_temperature, affected_batch_ids.
    """
    trip_id = setup_s45_data["trip_id"]
    headers = _auth_header("trans_s45")

    start_str = (datetime.now(timezone.utc) - timedelta(minutes=40)).isoformat()
    end_str = datetime.now(timezone.utc).isoformat()

    res = client.post(
        f"/trips/{trip_id}/violations",
        json={
            "start_time": start_str,
            "end_time": end_str,
            "duration_minutes": 40.0,
            "peak_temperature": 15.0,
            "threshold_temperature": 8.0,
            "min_threshold": 2.0,
            "max_threshold": 8.0,
            "violation_type": "PROLONGED_HEAT",
            "notes": "Mất nguồn điện máy phát của thùng lạnh",
        },
        headers=headers,
    )
    assert res.status_code == 201
    data = res.json()
    assert data["id"] is not None
    assert data["trip_id"] == trip_id
    assert data["peak_temperature"] == 15.0
    assert data["duration_minutes"] == 40.0
    assert data["severity"] == "CRITICAL"
    assert len(data["affected_batch_ids"]) == 2


def test_tc_s45_04_batch_detail_shows_violation_flag(
    client: TestClient,
    session_factory: sessionmaker[Session],
    setup_s45_data: dict[str, Any],
) -> None:
    """TC-S45-04: API GET /batches/{batch_id} trả về đầy đủ cờ vi phạm:

    - has_temperature_violation = True
    - temperature_violation_count = 1
    """
    trip_id = setup_s45_data["trip_id"]
    batch_1_id = setup_s45_data["batch_1_id"]

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with session_factory() as session:
        u_trans = session.get(User, setup_s45_data["u_transporter_id"])
        from app.schemas_trips import TemperatureViolationCreate
        payload = TemperatureViolationCreate(
            start_time=now - timedelta(minutes=32),
            end_time=now,
            duration_minutes=32.0,
            peak_temperature=11.5,
            threshold_temperature=8.0,
        )
        record_temperature_violation_for_trip(session, trip_id, payload, user=u_trans)

    # Đơn vị vận chuyển hoặc thanh tra xem chi tiết lô
    headers = _auth_header("trans_s45")
    res = client.get(f"/batches/{batch_1_id}", headers=headers)
    assert res.status_code == 200
    batch_data = res.json()
    assert batch_data["has_temperature_violation"] is True
    assert batch_data["temperature_violation_count"] == 1


def test_tc_s45_05_timeline_reveals_violation_to_distributor(
    client: TestClient,
    session_factory: sessionmaker[Session],
    setup_s45_data: dict[str, Any],
) -> None:
    """TC-S45-05: Dòng thời gian sự kiện (GET /batches/{id}/events) hiển thị chi tiết vi phạm:

    - Nhà phân phối (Distributor) có quyền xem dòng thời gian của lô và thấy rõ:
      thời lượng (duration_minutes), đỉnh (peak_temperature), mã chuyến xe và mô tả vi phạm.
    """
    trip_id = setup_s45_data["trip_id"]
    batch_1_id = setup_s45_data["batch_1_id"]

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with session_factory() as session:
        u_trans = session.get(User, setup_s45_data["u_transporter_id"])
        from app.schemas_trips import TemperatureViolationCreate
        payload = TemperatureViolationCreate(
            start_time=now - timedelta(minutes=45),
            end_time=now,
            duration_minutes=45.0,
            peak_temperature=16.2,
            threshold_temperature=8.0,
            notes="Hỏng bộ làm lạnh",
        )
        record_temperature_violation_for_trip(session, trip_id, payload, user=u_trans)

    # Inspector xem dòng thời gian
    headers_insp = _auth_header("inspector_s45")
    res_insp = client.get(f"/batches/{batch_1_id}/events", headers=headers_insp)
    assert res_insp.status_code == 200
    events = res_insp.json()
    viol_ev = next((e for e in events if e["event_type"] == EVENT_TEMPERATURE_VIOLATION), None)
    assert viol_ev is not None
    assert viol_ev["payload"]["peak_temperature"] == 16.2
    assert viol_ev["payload"]["duration_minutes"] == 45.0
    assert "TRIP-S45-001" in viol_ev["payload"]["trip_code"]


def test_tc_s45_06_handover_displays_temperature_warning_to_receiver(
    client: TestClient,
    session_factory: sessionmaker[Session],
    setup_s45_data: dict[str, Any],
) -> None:
    """TC-S45-06: Bàn giao lô có vi phạm hiện cảnh báo cho bên nhận trước khi xác nhận (S-45):

    - Đơn vị vận chuyển tạo yêu cầu bàn giao sang Nhà phân phối (POST /batches/{id}/handover).
    - Nhà phân phối gọi GET /handovers/pending.
    - Cờ `has_temperature_violation: true` và `temperature_violation_count: 1` hiển thị rõ ràng.
    """
    trip_id = setup_s45_data["trip_id"]
    batch_1_id = setup_s45_data["batch_1_id"]
    dist_org_id = setup_s45_data["dist_org_id"]

    # 1. Ghi nhận vi phạm nhiệt độ trên chuyến xe
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with session_factory() as session:
        u_trans = session.get(User, setup_s45_data["u_transporter_id"])
        from app.schemas_trips import TemperatureViolationCreate
        payload = TemperatureViolationCreate(
            start_time=now - timedelta(minutes=50),
            end_time=now,
            duration_minutes=50.0,
            peak_temperature=18.0,
            threshold_temperature=8.0,
        )
        record_temperature_violation_for_trip(session, trip_id, payload, user=u_trans)

        # Hoàn thành chuyến xe để dỡ hàng xuống xe trước khi bàn giao
        trip = session.get(ColdTrip, trip_id)
        trip.status = "COMPLETED"
        for tb in trip.trip_batches:
            tb.detached_at = now
        session.commit()

    # 2. Transporter tạo yêu cầu bàn giao sang Distributor
    headers_trans = _auth_header("trans_s45")
    res_ho = client.post(
        f"/batches/{batch_1_id}/handover",
        json={
            "to_org_id": dist_org_id,
            "note": "Bàn giao lô thịt bò sau chuyến vận chuyển",
        },
        headers=headers_trans,
    )
    assert res_ho.status_code == 201

    # 3. Distributor kiểm tra danh sách chờ nhận (GET /handovers/pending)
    headers_dist = _auth_header("dist_s45")
    res_pending = client.get("/handovers/pending", headers=headers_dist)
    assert res_pending.status_code == 200
    pending_list = res_pending.json()
    assert len(pending_list) >= 1

    target_ho = next((h for h in pending_list if h["batch_id"] == batch_1_id), None)
    assert target_ho is not None
    # Xác minh cờ cảnh báo vi phạm nhiệt độ đã được bật cho bên nhận
    assert target_ho["has_temperature_violation"] is True
    assert target_ho["temperature_violation_count"] >= 1


def test_tc_s45_07_rbac_permission_checks(
    client: TestClient,
    setup_s45_data: dict[str, Any],
) -> None:
    """TC-S45-07: Kiểm thử phân quyền RBAC khi ghi nhận vi phạm:

    - Transporter của tổ chức khác -> 403 Forbidden.
    - Farmer -> 403 Forbidden.
    - Inspector -> 201 Created.
    - Org Admin của tổ chức vận chuyển -> 201 Created.
    """
    trip_id = setup_s45_data["trip_id"]

    now_iso = datetime.now(timezone.utc).isoformat()
    req_body = {
        "start_time": now_iso,
        "end_time": now_iso,
        "duration_minutes": 35.0,
        "peak_temperature": 13.0,
        "threshold_temperature": 8.0,
    }

    # 1. Transporter của tổ chức khác bị chặn 403
    headers_other_trans = _auth_header("other_trans_s45")
    res_forbidden = client.post(f"/trips/{trip_id}/violations", json=req_body, headers=headers_other_trans)
    assert res_forbidden.status_code == 403

    # 2. Farmer bị chặn 403
    headers_farmer = _auth_header("farmer_s45")
    res_farmer = client.post(f"/trips/{trip_id}/violations", json=req_body, headers=headers_farmer)
    assert res_farmer.status_code == 403

    # 3. Org Admin của tổ chức vận chuyển thành công 201
    headers_trans_admin = _auth_header("trans_admin_s45")
    res_admin = client.post(f"/trips/{trip_id}/violations", json=req_body, headers=headers_trans_admin)
    assert res_admin.status_code == 201

    # 4. Inspector thành công 201
    headers_insp = _auth_header("inspector_s45")
    res_insp = client.post(f"/trips/{trip_id}/violations", json=req_body, headers=headers_insp)
    assert res_insp.status_code == 201


def test_tc_s45_08_s43_continuous_breach_detection_algorithm() -> None:
    """TC-S45-08: Kiểm thử thuật toán phát hiện vi phạm theo S-43:

    - Không vượt / vượt ngắn 10 phút -> 0 vi phạm.
    - Vượt liên tục 45 phút -> 1 vi phạm.
    - Hai lần vượt cách nhau 3 phút (< 5 phút) -> gộp làm 1 vi phạm.
    - Hai lần vượt cách nhau 15 phút (>= 5 phút) -> 2 vi phạm độc lập.
    """
    base_time = datetime(2026, 10, 19, 8, 0, 0)

    # Kịch bản 1: Vượt ngắn 10 phút (không vi phạm vì < 30 phút)
    short_readings = [
        (base_time, 5.0),
        (base_time + timedelta(minutes=5), 10.0),
        (base_time + timedelta(minutes=15), 11.0),
        (base_time + timedelta(minutes=16), 5.0),
    ]
    v_short = detect_violations_from_readings(short_readings, threshold_max=8.0, min_duration_minutes=30.0)
    assert len(v_short) == 0

    # Kịch bản 2: Vượt liên tục 45 phút -> 1 vi phạm
    long_readings = [
        (base_time, 5.0),
        (base_time + timedelta(minutes=5), 10.0),
        (base_time + timedelta(minutes=25), 14.5),
        (base_time + timedelta(minutes=50), 12.0),
        (base_time + timedelta(minutes=55), 5.0),
    ]
    v_long = detect_violations_from_readings(long_readings, threshold_max=8.0, min_duration_minutes=30.0)
    assert len(v_long) == 1
    assert v_long[0]["duration_minutes"] == 45.0
    assert v_long[0]["peak_temperature"] == 14.5

    # Kịch bản 3: Hai lần vượt cách nhau 3 phút (< 5 phút) -> gộp thành 1 vi phạm
    # Đợt 1: phút 10 đến 30 (20 phút). Nghỉ: phút 30 đến 33 (3 phút). Đợt 2: phút 33 đến 50 (17 phút).
    # Tổng thời lượng gộp = 40 phút >= 30 phút
    merged_readings = [
        (base_time, 5.0),
        (base_time + timedelta(minutes=10), 11.0),
        (base_time + timedelta(minutes=30), 12.0),
        (base_time + timedelta(minutes=31), 6.0),
        (base_time + timedelta(minutes=32), 6.0),
        (base_time + timedelta(minutes=33), 13.0),
        (base_time + timedelta(minutes=50), 10.0),
        (base_time + timedelta(minutes=52), 4.0),
    ]
    v_merged = detect_violations_from_readings(
        merged_readings, threshold_max=8.0, min_duration_minutes=30.0, gap_merge_minutes=5.0
    )
    assert len(v_merged) == 1
    assert v_merged[0]["peak_temperature"] == 13.0
    assert v_merged[0]["duration_minutes"] == 40.0

    # Kịch bản 4: Hai lần vượt cách nhau 15 phút (>= 5 phút), mỗi lần 35 phút -> 2 vi phạm
    two_readings = [
        # Vi phạm 1: 35 phút
        (base_time, 10.0),
        (base_time + timedelta(minutes=35), 12.0),
        (base_time + timedelta(minutes=36), 5.0),
        # Nghỉ 14 phút
        (base_time + timedelta(minutes=50), 5.0),
        # Vi phạm 2: 35 phút
        (base_time + timedelta(minutes=55), 11.0),
        (base_time + timedelta(minutes=90), 13.5),
        (base_time + timedelta(minutes=92), 4.0),
    ]
    v_two = detect_violations_from_readings(
        two_readings, threshold_max=8.0, min_duration_minutes=30.0, gap_merge_minutes=5.0
    )
    assert len(v_two) == 2


def test_tc_s45_09_s41_sensor_telemetry_and_duplicate_suppression(
    client: TestClient,
    setup_s45_data: dict[str, Any],
) -> None:
    """TC-S45-09: Ghi nhận số đo cảm biến (S-41) và bỏ qua số đo cũ hơn hoặc trùng:

    - Số đo mới -> lưu thành công HTTP 201.
    - Số đo cũ hơn -> bỏ qua và trả về số đo hợp lệ đã nhận.
    """
    trip_id = setup_s45_data["trip_id"]
    headers = _auth_header("trans_s45")

    t1 = datetime(2026, 10, 19, 10, 0, 0)
    t2 = datetime(2026, 10, 19, 10, 15, 0)
    t_old = datetime(2026, 10, 19, 9, 30, 0)

    # 1. Ghi nhận số đo mốc t1
    res1 = client.post(
        f"/trips/{trip_id}/readings",
        json={"temperature": 4.5, "recorded_at": t1.isoformat()},
        headers=headers,
    )
    assert res1.status_code == 201
    log1 = res1.json()
    assert log1["temperature"] == 4.5

    # 2. Ghi nhận số đo mốc t2 (mới hơn)
    res2 = client.post(
        f"/trips/{trip_id}/readings",
        json={"temperature": 5.0, "recorded_at": t2.isoformat()},
        headers=headers,
    )
    assert res2.status_code == 201
    log2 = res2.json()
    assert log2["temperature"] == 5.0

    # 3. Ghi nhận số đo mốc t_old (cũ hơn) -> bỏ qua không tạo bản ghi mới
    res_old = client.post(
        f"/trips/{trip_id}/readings",
        json={"temperature": 4.0, "recorded_at": t_old.isoformat()},
        headers=headers,
    )
    assert res_old.status_code == 201
    log_old = res_old.json()
    # Trả về số đo đã nhận mới nhất
    assert log_old["temperature"] == 5.0

    # 4. Lấy danh sách số đo của chuyến
    res_list = client.get(f"/trips/{trip_id}/readings", headers=headers)
    assert res_list.status_code == 200
    readings = res_list.json()
    assert len(readings) == 2


def test_tc_s45_10_batch_direct_violation_and_summary_api(
    client: TestClient,
    setup_s45_data: dict[str, Any],
) -> None:
    """TC-S45-10: Ghi nhận vi phạm trực tiếp cho một lô tại kho và tra cứu tổng hợp:

    - POST /batches/{batch_id}/violations -> ghi nhận vi phạm trực tiếp cho lô nông trại.
    - GET /batches/{batch_id}/violations -> trả về BatchViolationSummary đầy đủ.
    """
    batch_farm_id = setup_s45_data["batch_farm_id"]
    headers = _auth_header("inspector_s45")

    now = datetime.now(timezone.utc).isoformat()
    res_create = client.post(
        f"/batches/{batch_farm_id}/violations",
        json={
            "start_time": now,
            "end_time": now,
            "duration_minutes": 60.0,
            "peak_temperature": 25.0,
            "threshold_temperature": 15.0,
            "violation_type": "WAREHOUSE_OVERHEAT",
            "notes": "Mất điện kho lạnh bảo quản nông trại",
        },
        headers=headers,
    )
    assert res_create.status_code == 201
    data = res_create.json()
    assert data["batch_id"] == batch_farm_id
    assert data["peak_temperature"] == 25.0

    # Tra cứu tổng hợp vi phạm của lô
    res_summary = client.get(f"/batches/{batch_farm_id}/violations", headers=headers)
    assert res_summary.status_code == 200
    summary = res_summary.json()
    assert summary["batch_id"] == batch_farm_id
    assert summary["has_violation"] is True
    assert summary["violation_count"] >= 1
    assert len(summary["violations"]) >= 1


def test_tc_s45_11_violation_idempotency_and_duplicate_request_suppression(
    client: TestClient,
    session_factory: sessionmaker[Session],
    setup_s45_data: dict[str, Any],
) -> None:
    """TC-S45-11: Ch?ng ghi nh?n tr?ng l?p vi ph?m khi h? th?ng nh?n l?i request ho?c x? l? l?i d? li?u (S-45):

    - G?i request vi ph?m chuy?n xe l?n 1 -> Th?nh c?ng (201 Created), t?o b?n ghi vi ph?m.
    - G?i l?i ch?nh x?c request l?n 2 (retry) -> B? qua, tr? v? b?n ghi vi ph?m c? m? kh?ng ghi ??p.
    - X?c minh: Kh?ng t?ng ??p c? temperature_violation_count tr?n l?, kh?ng th?m s? ki?n tr?ng trong hash-chain.
    - T??ng t? v?i endpoint ghi nh?n vi ph?m tr?c ti?p cho l? n?ng s?n.
    """
    trip_id = setup_s45_data["trip_id"]
    batch_1_id = setup_s45_data["batch_1_id"]
    batch_farm_id = setup_s45_data["batch_farm_id"]
    headers_trans = _auth_header("trans_s45")
    headers_insp = _auth_header("inspector_s45")

    start_time = datetime(2026, 10, 20, 8, 30, 0, tzinfo=timezone.utc).isoformat()
    end_time = datetime(2026, 10, 20, 9, 15, 0, tzinfo=timezone.utc).isoformat()

    trip_payload = {
        "start_time": start_time,
        "end_time": end_time,
        "duration_minutes": 45.0,
        "peak_temperature": 15.5,
        "threshold_temperature": 8.0,
        "min_threshold": 2.0,
        "max_threshold": 8.0,
        "violation_type": "PROLONGED_HEAT",
        "notes": "M?t ngu?n ?i?n ?i?u h?a th?ng xe",
    }

    # 1. G?i l?n 1: T?o m?i vi ph?m chuy?n xe
    res1 = client.post(f"/trips/{trip_id}/violations", json=trip_payload, headers=headers_trans)
    assert res1.status_code == 201
    v1_id = res1.json()["id"]

    with session_factory() as session:
        b1 = session.get(Batch, batch_1_id)
        assert b1.has_temperature_violation is True
        assert b1.temperature_violation_count == 1
        ev_count1 = len(
            list(
                session.scalars(
                    select(BatchEvent).where(
                        BatchEvent.batch_id == batch_1_id,
                        BatchEvent.event_type == EVENT_TEMPERATURE_VIOLATION,
                    )
                ).all()
            )
        )
        assert ev_count1 == 1

    # 2. G?i l?i l?n 2 (c?ng payload): Ph?i c? t?nh Idempotency, kh?ng t?o th?m b?n ghi m?i
    res2 = client.post(f"/trips/{trip_id}/violations", json=trip_payload, headers=headers_trans)
    assert res2.status_code in (200, 201)
    v2_id = res2.json()["id"]
    assert v2_id == v1_id  # Kh?p ID b?n ghi ?? t?n t?i

    # X?c minh trong database: S? l??ng b?n ghi, s? ki?n v? b? ??m vi ph?m KH?NG B? T?NG ??P
    with session_factory() as session:
        b1 = session.get(Batch, batch_1_id)
        assert b1.temperature_violation_count == 1  # Kh?ng b? t?ng l?n 2

        trip_violations = list(
            session.scalars(
                select(TemperatureViolation).where(TemperatureViolation.trip_id == trip_id)
            ).all()
        )
        assert len(trip_violations) == 1  # Ch? c? 1 b?n ghi duy nh?t

        ev_count2 = len(
            list(
                session.scalars(
                    select(BatchEvent).where(
                        BatchEvent.batch_id == batch_1_id,
                        BatchEvent.event_type == EVENT_TEMPERATURE_VIOLATION,
                    )
                ).all()
            )
        )
        assert ev_count2 == 1  # Hash-chain kh?ng b? ghi ??p s? ki?n

    # 3. Ki?m tra t?nh Idempotency ??i v?i vi ph?m tr?c ti?p c?a l? n?ng s?n (POST /batches/{id}/violations)
    batch_payload = {
        "start_time": start_time,
        "end_time": end_time,
        "duration_minutes": 45.0,
        "peak_temperature": 22.0,
        "threshold_temperature": 15.0,
        "violation_type": "WAREHOUSE_OVERHEAT",
    }

    res_b1 = client.post(f"/batches/{batch_farm_id}/violations", json=batch_payload, headers=headers_insp)
    assert res_b1.status_code == 201
    bv1_id = res_b1.json()["id"]

    res_b2 = client.post(f"/batches/{batch_farm_id}/violations", json=batch_payload, headers=headers_insp)
    assert res_b2.status_code in (200, 201)
    bv2_id = res_b2.json()["id"]
    assert bv2_id == bv1_id

    with session_factory() as session:
        bf = session.get(Batch, batch_farm_id)
        assert bf.temperature_violation_count == 1
        batch_viol_count = len(
            list(
                session.scalars(
                    select(TemperatureViolation).where(TemperatureViolation.batch_id == batch_farm_id)
                ).all()
            )
        )
        assert batch_viol_count == 1
