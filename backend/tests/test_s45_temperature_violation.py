"""Bộ kiểm thử cho User Story S-45:
"Ghi sự kiện vi phạm nhiệt độ vào nhật ký sự kiện của từng lô và tích hợp hệ thống".

Bao gồm các kịch bản kiểm thử:
1. Ghi nhận sự cố vi phạm nhiệt độ cho 1 lô đơn lẻ:
   - Kiểm tra ghi vào Hash-Chain bất biến (batch_events, event_type='TEMPERATURE_VIOLATION').
   - Kiểm tra tính toàn vẹn mã băm SHA-256 (verify_batch_chain trả về is_valid=True).
   - Kiểm tra gắn cờ cảnh báo (has_temperature_violation=True, cold_chain_status='VIOLATED').
   - Kiểm tra ghi nhận vào nhật ký kiểm toán hệ thống (AuditLog).
2. Ghi nhận sự cố vi phạm nhiệt độ cho chuyến vận chuyển lạnh nhiều lô (Shipment - S-40):
   - Sự kiện vi phạm được tự động ghi vào chuỗi của TẤT CẢ các lô trên chuyến.
   - Từng chuỗi khối của mỗi lô đều độc lập và hợp lệ.
3. Tính bất biến (Immutability / S-11) của sự kiện TEMPERATURE_VIOLATION.
4. Thuật toán phát hiện vi phạm theo tiêu chuẩn S-43:
   - Vượt ngưỡng ngắn (< 30 phút) -> không sinh vi phạm.
   - Vượt ngưỡng liên tục > 30 phút -> tự động sinh vi phạm S-45 với đỉnh và thời lượng chính xác.
   - Hai lần vượt cách nhau dưới 5 phút -> gộp làm một đợt vi phạm.
   - Hai lần vượt cách nhau trên 5 phút -> tính làm hai vi phạm riêng biệt.
5. Cảnh báo vi phạm chuỗi lạnh trước khi bàn giao (Handover alert) cho bên nhận hàng.
6. Xử lý ngoại lệ và an toàn dữ liệu (404, 400).
7. Đảm bảo tính tương thích ngược, không làm ảnh hưởng đến các API hiện hữu.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.hash_chain import verify_batch_chain
from app.models import (
    AuditLog,
    Batch,
    BatchEvent,
    Organization,
    Plot,
    Product,
    ProductUnit,
    Shipment,
    TemperatureViolation,
    User,
)


@pytest.fixture()
def setup_cold_chain_data(session_factory) -> dict:
    """Khởi tạo dữ liệu mẫu phục vụ kiểm thử chuỗi lạnh."""
    with session_factory() as db:
        # Tổ chức
        org = db.scalar(select(Organization).where(Organization.id == 1))
        if not org:
            org = Organization(id=1, name="HTX Đồng Tháp", code="HTX-DT")
            db.add(org)
            db.flush()

        transporter_org = db.scalar(select(Organization).where(Organization.id == 2))
        if not transporter_org:
            transporter_org = Organization(id=2, name="Công ty Vận chuyển Lạnh Mekong", code="COLD-MEKONG")
            db.add(transporter_org)
            db.flush()

        # Người dùng
        admin = db.scalar(select(User).where(User.username == "admin"))
        farmer = db.scalar(select(User).where(User.username == "farmer"))

        # Sản phẩm
        product = db.scalar(select(Product).where(Product.name == "Xoài cát Chu"))
        if not product:
            product = Product(name="Xoài cát Chu", unit=ProductUnit.KG.value)
            db.add(product)
            db.flush()

        # Thửa đất
        plot = db.scalar(select(Plot).where(Plot.name == "Thửa xoài VietGAP 01"))
        if not plot:
            plot = Plot(
                name="Thửa xoài VietGAP 01",
                organization_id=org.id,
                location="Cao Lãnh, Đồng Tháp",
                area=2.5,
                owner="Nguyễn Văn A",
            )
            db.add(plot)
            db.flush()

        # Tạo Lô 1
        batch1 = Batch(
            code="LOT-COLD-01",
            plot_id=plot.id,
            product_id=product.id,
            harvest_date=datetime.now(timezone.utc).date(),
            initial_quantity=500.0,
            remaining_quantity=500.0,
            current_org_id=org.id,
            status="ACTIVE",
            cold_chain_status="NORMAL",
            has_temperature_violation=False,
        )
        db.add(batch1)

        # Tạo Lô 2
        batch2 = Batch(
            code="LOT-COLD-02",
            plot_id=plot.id,
            product_id=product.id,
            harvest_date=datetime.now(timezone.utc).date(),
            initial_quantity=800.0,
            remaining_quantity=800.0,
            current_org_id=org.id,
            status="ACTIVE",
            cold_chain_status="NORMAL",
            has_temperature_violation=False,
        )
        db.add(batch2)

        # Tạo Lô 3
        batch3 = Batch(
            code="LOT-COLD-03",
            plot_id=plot.id,
            product_id=product.id,
            harvest_date=datetime.now(timezone.utc).date(),
            initial_quantity=1000.0,
            remaining_quantity=1000.0,
            current_org_id=org.id,
            status="ACTIVE",
            cold_chain_status="NORMAL",
            has_temperature_violation=False,
        )
        db.add(batch3)

        db.commit()
        db.refresh(batch1)
        db.refresh(batch2)
        db.refresh(batch3)

        return {
            "org_id": org.id,
            "transporter_org_id": transporter_org.id,
            "batch1_id": batch1.id,
            "batch1_code": batch1.code,
            "batch2_id": batch2.id,
            "batch2_code": batch2.code,
            "batch3_id": batch3.id,
            "batch3_code": batch3.code,
        }


def test_record_temperature_violation_single_batch(
    client: TestClient,
    session_factory,
    setup_cold_chain_data: dict,
):
    """Kiểm tra ghi nhận sự cố vi phạm nhiệt độ cho 1 lô đơn lẻ (S-45)."""
    batch_id = setup_cold_chain_data["batch1_id"]

    # 1. Trước khi ghi nhận: kiểm tra lô ở trạng thái bình thường
    with session_factory() as db:
        batch = db.get(Batch, batch_id)
        assert batch.has_temperature_violation is False
        assert batch.cold_chain_status == "NORMAL"

    # 2. Gọi API ghi nhận sự cố vi phạm nhiệt độ
    violation_payload = {
        "batch_id": batch_id,
        "recorded_temperature": 18.5,
        "min_threshold": 2.0,
        "max_threshold": 8.0,
        "peak_temperature": 21.0,
        "duration_minutes": 45,
        "severity": "CRITICAL",
        "warning_flag": True,
        "sensor_id": "SENSOR-TMP-01",
        "container_code": "CONT-REEFER-01",
        "notes": "Máy làm lạnh gặp sự cố rò rỉ gas khiến nhiệt độ tăng cao.",
    }

    resp = client.post(
        "/cold-chain/violations",
        json=violation_payload,
        auth=("admin", "123456"),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1

    item = data[0]
    assert item["batch_id"] == batch_id
    assert item["recorded_temperature"] == 18.5
    assert item["peak_temperature"] == 21.0
    assert item["duration_minutes"] == 45
    assert item["severity"] == "CRITICAL"
    assert item["warning_flag"] is True
    assert item["event_id"] is not None
    assert item["event_hash"] is not None and len(item["event_hash"]) == 64

    # 3. Kiểm tra cơ sở dữ liệu: trạng thái lô nông sản đã cập nhật và gắn cờ
    with session_factory() as db:
        updated_batch = db.get(Batch, batch_id)
        assert updated_batch.has_temperature_violation is True
        assert updated_batch.cold_chain_status == "VIOLATED"

        # Kiểm tra sự kiện trong bảng batch_events
        event = db.get(BatchEvent, item["event_id"])
        assert event is not None
        assert event.batch_id == batch_id
        assert event.event_type == "TEMPERATURE_VIOLATION"
        assert event.payload["recorded_temperature"] == 18.5
        assert event.payload["peak_temperature"] == 21.0
        assert event.payload["duration_minutes"] == 45
        assert event.payload["has_temperature_violation"] is True
        assert event.payload["warning_flag"] is True

        # Kiểm tra tính toàn vẹn của chuỗi Hash-Chain (verify_batch_chain)
        integrity = verify_batch_chain(db, batch_id)
        assert integrity["is_valid"] is True, f"Hash chain bị đứt gãy: {integrity}"

        # Kiểm tra nhật ký kiểm toán hệ thống (AuditLog)
        audit_log = db.scalar(
            select(AuditLog)
            .where(AuditLog.entity == "batch", AuditLog.entity_id == batch_id)
            .order_by(AuditLog.id.desc())
        )
        assert audit_log is not None
        assert audit_log.action == "update"
        assert audit_log.entity == "batch"
        assert audit_log.entity_id == batch_id

        # Kiểm tra bản ghi trong bảng temperature_violations
        violation_rec = db.get(TemperatureViolation, item["id"])
        assert violation_rec is not None
        assert violation_rec.recorded_temperature == 18.5
        assert violation_rec.event_id == event.id


def test_record_temperature_violation_shipment_multiple_batches(
    client: TestClient,
    session_factory,
    setup_cold_chain_data: dict,
):
    """Kiểm tra ghi nhận sự cố vi phạm nhiệt độ cho chuyến xe có nhiều lô (S-40 & S-45).

    Yêu cầu S-45:
    'Khi vi phạm kết thúc, một sự kiện vi phạm được ghi vào chuỗi của mọi lô đang trên chuyến'.
    """
    batch1_id = setup_cold_chain_data["batch1_id"]
    batch2_id = setup_cold_chain_data["batch2_id"]
    batch3_id = setup_cold_chain_data["batch3_id"]

    # 1. Khai báo chuyến vận chuyển lạnh (S-40) gồm 3 lô
    shipment_payload = {
        "code": "SHP-COLD-2026-001",
        "container_code": "CONTAINER-40FT-09",
        "batch_ids": [batch1_id, batch2_id, batch3_id],
        "notes": "Chuyến xe đông lạnh vận chuyển từ Đồng Tháp về TP.HCM.",
    }

    shp_resp = client.post(
        "/cold-chain/shipments",
        json=shipment_payload,
        auth=("admin", "123456"),
    )
    assert shp_resp.status_code == 201, shp_resp.text
    shipment_data = shp_resp.json()
    shipment_id = shipment_data["id"]
    assert shipment_data["code"] == "SHP-COLD-2026-001"
    assert len(shipment_data["batch_ids"]) == 3

    # 2. Ghi nhận sự cố vi phạm nhiệt độ trên chuyến xe (bằng shipment_id)
    violation_payload = {
        "shipment_id": shipment_id,
        "recorded_temperature": 24.0,
        "min_threshold": 2.0,
        "max_threshold": 8.0,
        "peak_temperature": 26.5,
        "duration_minutes": 50,
        "severity": "CRITICAL",
        "warning_flag": True,
        "notes": "Mất nguồn điện máy phát của thùng container lạnh suốt 50 phút trên đường cao tốc.",
    }

    viol_resp = client.post(
        "/cold-chain/violations",
        json=violation_payload,
        auth=("admin", "123456"),
    )
    assert viol_resp.status_code == 201, viol_resp.text
    violations = viol_resp.json()

    # Phải có 3 bản ghi vi phạm trả về, tương ứng với cả 3 lô trên chuyến
    assert len(violations) == 3
    returned_batch_ids = {v["batch_id"] for v in violations}
    assert returned_batch_ids == {batch1_id, batch2_id, batch3_id}

    # 3. Kiểm tra tính toàn vẹn và cờ cảnh báo của từng lô trong DB
    with session_factory() as db:
        for b_id in (batch1_id, batch2_id, batch3_id):
            batch = db.get(Batch, b_id)
            assert batch.has_temperature_violation is True
            assert batch.cold_chain_status == "VIOLATED"

            # Kiểm tra sự kiện TEMPERATURE_VIOLATION riêng biệt trong chuỗi của từng lô
            events = list(
                db.scalars(
                    select(BatchEvent)
                    .where(BatchEvent.batch_id == b_id, BatchEvent.event_type == "TEMPERATURE_VIOLATION")
                ).all()
            )
            assert len(events) >= 1
            latest_ev = events[-1]
            assert latest_ev.payload["shipment_id"] == shipment_id
            assert latest_ev.payload["recorded_temperature"] == 24.0
            assert latest_ev.payload["peak_temperature"] == 26.5
            assert latest_ev.payload["duration_minutes"] == 50

            # Kiểm tra Hash-Chain của từng lô độc lập và hợp lệ
            integrity = verify_batch_chain(db, b_id)
            assert integrity["is_valid"] is True, f"Lô {b_id} bị hỏng hash chain!"


def test_temperature_violation_immutability(session_factory, setup_cold_chain_data: dict):
    """Kiểm tra tính bất biến (S-11 append-only): sự kiện vi phạm không thể bị sửa hoặc xóa."""
    batch_id = setup_cold_chain_data["batch1_id"]

    with session_factory() as db:
        # Ghi nhận vi phạm
        from app.services.cold_chain_service import record_temperature_violation
        from app.schemas import TemperatureViolationCreate

        payload = TemperatureViolationCreate(
            batch_id=batch_id,
            recorded_temperature=19.0,
            duration_minutes=35,
        )
        record_temperature_violation(db, payload)

        event = db.scalar(
            select(BatchEvent)
            .where(BatchEvent.batch_id == batch_id, BatchEvent.event_type == "TEMPERATURE_VIOLATION")
            .order_by(BatchEvent.id.desc())
        )
        assert event is not None

        # Cố tình cập nhật sự kiện -> Bắt buộc bị chặn bởi PermissionError (S-11)
        event.notes = "Cố tình giả mạo ghi chú sự kiện"
        with pytest.raises(PermissionError):
            db.flush()

        db.rollback()


def test_s43_algorithm_short_exceedance_not_violating(
    client: TestClient,
    session_factory,
    setup_cold_chain_data: dict,
):
    """Kiểm tra thuật toán S-43: Vượt ngưỡng ngắn (< 30 phút) KHÔNG tính là vi phạm."""
    batch_id = setup_cold_chain_data["batch1_id"]
    base_time = datetime(2026, 10, 19, 8, 0, 0)

    # Kịch bản 1: Mở cửa thùng hàng 10 phút (nhiệt độ tăng lên 12°C, ngưỡng 2-8°C), sau đó về 5°C
    readings = [
        {"temperature": 5.0, "timestamp": (base_time + timedelta(minutes=0)).isoformat()},
        {"temperature": 5.0, "timestamp": (base_time + timedelta(minutes=5)).isoformat()},
        # Vượt ngưỡng từ phút 10 đến phút 20 (kéo dài 10 phút < 30 phút)
        {"temperature": 12.0, "timestamp": (base_time + timedelta(minutes=10)).isoformat()},
        {"temperature": 13.5, "timestamp": (base_time + timedelta(minutes=15)).isoformat()},
        {"temperature": 12.0, "timestamp": (base_time + timedelta(minutes=20)).isoformat()},
        # Trở lại bình thường từ phút 25
        {"temperature": 5.0, "timestamp": (base_time + timedelta(minutes=25)).isoformat()},
        {"temperature": 4.5, "timestamp": (base_time + timedelta(minutes=30)).isoformat()},
    ]

    resp = client.post(
        "/cold-chain/readings/stream",
        json={
            "batch_id": batch_id,
            "min_threshold": 2.0,
            "max_threshold": 8.0,
            "latency_minutes": 30,
            "gap_tolerance_minutes": 5,
            "readings": readings,
        },
        auth=("admin", "123456"),
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()

    # Không sinh vi phạm nào
    assert result["violations_detected"] == 0
    assert len(result["violations"]) == 0

    # Lô nông sản không bị gắn cờ vi phạm
    with session_factory() as db:
        batch = db.get(Batch, batch_id)
        assert batch.has_temperature_violation is False
        assert batch.cold_chain_status == "NORMAL"


def test_s43_algorithm_long_exceedance_generates_s45_violation(
    client: TestClient,
    session_factory,
    setup_cold_chain_data: dict,
):
    """Kiểm tra thuật toán S-43: Vượt ngưỡng liên tục > 30 phút tự động ghi sự kiện S-45."""
    batch_id = setup_cold_chain_data["batch2_id"]
    base_time = datetime(2026, 10, 19, 10, 0, 0)

    # Kịch bản 2: Vượt ngưỡng liên tục từ phút 10 đến phút 55 (45 phút > 30 phút), đỉnh 16.5°C
    readings = [
        {"temperature": 4.0, "timestamp": (base_time + timedelta(minutes=0)).isoformat()},
        # Bắt đầu vượt ngưỡng tại phút 10 (11°C)
        {"temperature": 11.0, "timestamp": (base_time + timedelta(minutes=10)).isoformat()},
        {"temperature": 14.0, "timestamp": (base_time + timedelta(minutes=20)).isoformat()},
        {"temperature": 16.5, "timestamp": (base_time + timedelta(minutes=30)).isoformat()},  # Đỉnh 16.5°C
        {"temperature": 15.0, "timestamp": (base_time + timedelta(minutes=40)).isoformat()},
        {"temperature": 10.0, "timestamp": (base_time + timedelta(minutes=55)).isoformat()},
        # Kết thúc vi phạm, về lại 4.0°C tại phút 60
        {"temperature": 4.0, "timestamp": (base_time + timedelta(minutes=60)).isoformat()},
    ]

    resp = client.post(
        "/cold-chain/readings/stream",
        json={
            "batch_id": batch_id,
            "min_threshold": 2.0,
            "max_threshold": 8.0,
            "latency_minutes": 30,
            "gap_tolerance_minutes": 5,
            "readings": readings,
        },
        auth=("admin", "123456"),
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()

    # Phát hiện đúng 1 vi phạm
    assert result["violations_detected"] == 1
    assert len(result["violations"]) == 1

    v = result["violations"][0]
    assert v["batch_id"] == batch_id
    assert v["peak_temperature"] == 16.5
    assert v["duration_minutes"] == 45
    assert v["warning_flag"] is True

    # Kiểm tra lô trong DB đã được ghi vào Hash-Chain và cập nhật cờ
    with session_factory() as db:
        batch = db.get(Batch, batch_id)
        assert batch.has_temperature_violation is True
        assert batch.cold_chain_status == "VIOLATED"

        integrity = verify_batch_chain(db, batch_id)
        assert integrity["is_valid"] is True


def test_s43_algorithm_merging_two_exceedances_under_5_mins(
    client: TestClient,
    session_factory,
    setup_cold_chain_data: dict,
):
    """Kiểm tra S-43: Hai lần vượt cách nhau dưới 5 phút tính là MỘT đợt kéo dài."""
    batch_id = setup_cold_chain_data["batch3_id"]
    base_time = datetime(2026, 10, 19, 14, 0, 0)

    # Đợt 1: Vượt từ phút 0 đến phút 20 (20 phút, 12°C)
    # Khoảng nghỉ: phút 20 đến phút 23 (3 phút < 5 phút)
    # Đợt 2: Vượt tiếp từ phút 23 đến phút 40 (17 phút, 15°C)
    # Tổng thời lượng gộp = 40 phút (> 30 phút) -> Tính là 1 vi phạm!
    readings = [
        {"temperature": 12.0, "timestamp": (base_time + timedelta(minutes=0)).isoformat()},
        {"temperature": 13.0, "timestamp": (base_time + timedelta(minutes=10)).isoformat()},
        {"temperature": 12.0, "timestamp": (base_time + timedelta(minutes=20)).isoformat()},
        # Hạ nhiệt độ trong 3 phút (dưới 5 phút)
        {"temperature": 6.0, "timestamp": (base_time + timedelta(minutes=22)).isoformat()},
        # Vượt lại tại phút 23
        {"temperature": 14.0, "timestamp": (base_time + timedelta(minutes=23)).isoformat()},
        {"temperature": 15.0, "timestamp": (base_time + timedelta(minutes=30)).isoformat()},
        {"temperature": 12.0, "timestamp": (base_time + timedelta(minutes=40)).isoformat()},
        # Kết thúc đợt gộp
        {"temperature": 5.0, "timestamp": (base_time + timedelta(minutes=45)).isoformat()},
    ]

    resp = client.post(
        "/cold-chain/readings/stream",
        json={
            "batch_id": batch_id,
            "min_threshold": 2.0,
            "max_threshold": 8.0,
            "latency_minutes": 30,
            "gap_tolerance_minutes": 5,
            "readings": readings,
        },
        auth=("admin", "123456"),
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()

    # Gộp làm 1 vi phạm duy nhất
    assert result["violations_detected"] == 1
    v = result["violations"][0]
    assert v["duration_minutes"] == 40
    assert v["peak_temperature"] == 15.0


def test_s43_algorithm_two_separate_exceedances_over_5_mins(
    client: TestClient,
    session_factory,
    setup_cold_chain_data: dict,
):
    """Kiểm tra S-43: Hai lần vượt cách nhau trên 5 phút tính là HAI vi phạm riêng biệt."""
    batch_id = setup_cold_chain_data["batch1_id"]
    base_time = datetime(2026, 10, 19, 16, 0, 0)

    # Đợt 1: Vượt từ phút 0 đến phút 35 (35 phút > 30 phút) -> Vi phạm 1
    # Khoảng nghỉ: phút 35 đến phút 47 (12 phút > 5 phút)
    # Đợt 2: Vượt từ phút 47 đến phút 82 (35 phút > 30 phút) -> Vi phạm 2
    readings = [
        # Đợt 1
        {"temperature": 12.0, "timestamp": (base_time + timedelta(minutes=0)).isoformat()},
        {"temperature": 14.0, "timestamp": (base_time + timedelta(minutes=20)).isoformat()},
        {"temperature": 12.0, "timestamp": (base_time + timedelta(minutes=35)).isoformat()},
        # Khoảng nghỉ 12 phút bình thường
        {"temperature": 4.0, "timestamp": (base_time + timedelta(minutes=40)).isoformat()},
        # Đợt 2 bắt đầu tại phút 47
        {"temperature": 13.0, "timestamp": (base_time + timedelta(minutes=47)).isoformat()},
        {"temperature": 16.0, "timestamp": (base_time + timedelta(minutes=65)).isoformat()},
        {"temperature": 11.0, "timestamp": (base_time + timedelta(minutes=82)).isoformat()},
        {"temperature": 5.0, "timestamp": (base_time + timedelta(minutes=90)).isoformat()},
    ]

    resp = client.post(
        "/cold-chain/readings/stream",
        json={
            "batch_id": batch_id,
            "min_threshold": 2.0,
            "max_threshold": 8.0,
            "latency_minutes": 30,
            "gap_tolerance_minutes": 5,
            "readings": readings,
        },
        auth=("admin", "123456"),
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()

    # Tính là 2 vi phạm riêng biệt
    assert result["violations_detected"] == 2
    assert len(result["violations"]) == 2


def test_batch_cold_chain_status_and_handover_warning(
    client: TestClient,
    session_factory,
    setup_cold_chain_data: dict,
):
    """Kiểm tra API trạng thái chuỗi lạnh và cảnh báo vi phạm trước khi nhận bàn giao (S-45)."""
    batch_id = setup_cold_chain_data["batch1_id"]

    # 1. Ghi nhận vi phạm
    client.post(
        "/cold-chain/violations",
        json={
            "batch_id": batch_id,
            "recorded_temperature": 20.0,
            "peak_temperature": 22.0,
            "duration_minutes": 60,
        },
        auth=("admin", "123456"),
    )

    # 2. Truy vấn API trạng thái chuỗi lạnh của lô
    status_resp = client.get(
        f"/cold-chain/batches/{batch_id}/status",
        auth=("admin", "123456"),
    )
    assert status_resp.status_code == 200, status_resp.text
    status_data = status_resp.json()
    assert status_data["batch_id"] == batch_id
    assert status_data["has_temperature_violation"] is True
    assert status_data["cold_chain_status"] == "VIOLATED"
    assert status_data["total_violations"] >= 1
    assert "CẢNH BÁO" in status_data["warning_message"]

    # 3. Tạo yêu cầu bàn giao (Handover) sang tổ chức khác
    handover_resp = client.post(
        f"/batches/{batch_id}/handover",
        json={
            "to_org_id": setup_cold_chain_data["transporter_org_id"],
            "notes": "Bàn giao chuyển giao sang công ty vận chuyển lạnh",
        },
        auth=("farmer", "123456"),
    )
    assert handover_resp.status_code == 201, handover_resp.text
    handover_data = handover_resp.json()

    # Kiểm tra cờ has_temperature_violation xuất hiện trong thông tin bàn giao để cảnh báo bên nhận
    assert handover_data["has_temperature_violation"] is True


def test_cold_chain_validation_errors(client: TestClient, setup_cold_chain_data: dict):
    """Kiểm tra xử lý ngoại lệ rõ ràng khi dữ liệu không hợp lệ."""
    # 1. Không truyền cả batch_id lẫn shipment_id
    resp = client.post(
        "/cold-chain/violations",
        json={"recorded_temperature": 25.0},
        auth=("admin", "123456"),
    )
    assert resp.status_code == 400
    assert "batch_id" in resp.json()["detail"]

    # 2. batch_id không tồn tại
    resp2 = client.post(
        "/cold-chain/violations",
        json={"batch_id": 999999, "recorded_temperature": 25.0},
        auth=("admin", "123456"),
    )
    assert resp2.status_code == 404

    # 3. shipment_id không tồn tại
    resp3 = client.post(
        "/cold-chain/violations",
        json={"shipment_id": 999999, "recorded_temperature": 25.0},
        auth=("admin", "123456"),
    )
    assert resp3.status_code == 404


def test_existing_batch_apis_remain_unaffected(
    client: TestClient,
    setup_cold_chain_data: dict,
):
    """Kiểm tra đảm bảo các API hiện có về quản lý lô hàng hoạt động bình thường 100%."""
    batch_id = setup_cold_chain_data["batch1_id"]

    # GET /batches
    resp = client.get("/batches", auth=("admin", "123456"))
    assert resp.status_code == 200
    batches = resp.json()
    assert isinstance(batches, list)
    target = next((b for b in batches if b["id"] == batch_id), None)
    assert target is not None
    assert "has_temperature_violation" in target
    assert "cold_chain_status" in target

    # GET /batches/{id}
    resp_detail = client.get(f"/batches/{batch_id}", auth=("admin", "123456"))
    assert resp_detail.status_code == 200
    detail = resp_detail.json()
    assert detail["id"] == batch_id
    assert "has_temperature_violation" in detail
