"""Bộ kiểm thử cho Sprint S-11: Không đường nào trong ứng dụng có thể sửa hoặc xoá sự kiện đã ghi."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.models import BatchEvent
from tests.conftest import TEST_PASSWORD, TEST_USERNAME_FARMER


def _get_farmer_auth_headers() -> dict[str, str]:
    import base64

    credentials = f"{TEST_USERNAME_FARMER}:{TEST_PASSWORD}"
    encoded = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
    return {"Authorization": f"Basic {encoded}"}


def _create_sample_farm_and_batch(client: TestClient) -> tuple[int, int]:
    headers = _get_farmer_auth_headers()
    farm_res = client.post(
        "/farms",
        json={
            "name": "Vườn xoài thử nghiệm S-11",
            "location": "Cao Lãnh, Đồng Tháp",
            "area": 1.5,
            "owner": "HTX Đồng Tháp",
        },
        headers=headers,
    )
    farm_id = farm_res.json()["id"]

    batch_res = client.post(
        "/batches",
        json={
            "farm_id": farm_id,
            "product_name": "Xoài Cát Chu xuất khẩu S-11",
            "quantity": 500.0,
            "harvest_date": "2026-03-01",
        },
        headers=headers,
    )
    batch_id = batch_res.json()["id"]
    return farm_id, batch_id


def test_bang_batch_events_co_du_cac_cot(engine) -> None:
    """Kiểm tra bảng `batch_events` có đủ 7 cột yêu cầu: id, batch_id, event_type, event_data, created_at, prev_hash, record_hash."""
    inspector = inspect(engine)
    columns = {col["name"] for col in inspector.get_columns("batch_events")}
    expected_columns = {
        "id",
        "batch_id",
        "event_type",
        "event_data",
        "created_at",
        "prev_hash",
        "record_hash",
    }
    assert expected_columns.issubset(columns), f"Bảng batch_events thiếu cột: {expected_columns - columns}"


def test_tao_event_moi_thanh_cong_va_chuoi_hash_hop_le(client: TestClient) -> None:
    """Test 1: Tạo event mới thành công và mã băm SHA-256 (prev_hash / record_hash) chính xác."""
    _, batch_id = _create_sample_farm_and_batch(client)
    headers = _get_farmer_auth_headers()

    # Thêm event 1
    res1 = client.post(
        f"/batches/{batch_id}/events",
        json={
            "event_type": "HARVEST",
            "event_data": "Thu hoạch xoài 500kg",
        },
        headers=headers,
    )
    assert res1.status_code == 201
    event1 = res1.json()
    assert event1["batch_id"] == batch_id
    assert event1["event_type"] == "HARVEST"
    assert event1["event_data"] == "Thu hoạch xoài 500kg"
    assert "prev_hash" in event1
    assert "record_hash" in event1

    # Thêm event 2 cho cùng lô -> prev_hash của event2 phải bằng record_hash của event1
    res2 = client.post(
        f"/batches/{batch_id}/events",
        json={
            "event_type": "QUALITY_CHECK",
            "event_data": "Đạt chuẩn xuất khẩu VietGAP",
        },
        headers=headers,
    )
    assert res2.status_code == 201
    event2 = res2.json()
    assert event2["prev_hash"] == event1["record_hash"]


def test_doc_event_thanh_cong(client: TestClient) -> None:
    """Test 2: Đọc event thành công qua API."""
    _, batch_id = _create_sample_farm_and_batch(client)
    headers = _get_farmer_auth_headers()

    client.post(
        f"/batches/{batch_id}/events",
        json={"event_type": "PROCESSING", "event_data": "Sơ chế & đóng gói"},
        headers=headers,
    )

    # Đọc danh sách event theo batch
    res_batch_events = client.get(f"/batches/{batch_id}/events")
    assert res_batch_events.status_code == 200
    events_list = res_batch_events.json()
    assert len(events_list) >= 2  # Gồm BATCH_CREATED và PROCESSING

    # Đọc tất cả event
    res_all = client.get("/events")
    assert res_all.status_code == 200
    assert len(res_all.json()) >= 2

    # Đọc chi tiết event theo ID
    event_id = events_list[0]["id"]
    res_detail = client.get(f"/events/{event_id}")
    assert res_detail.status_code == 200
    assert res_detail.json()["id"] == event_id


def test_thu_update_event_bi_tu_choi(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    """Test 3: Thử UPDATE event bị từ chối ở cả tầng ORM và tầng Database (Triggers)."""
    _, batch_id = _create_sample_farm_and_batch(client)
    headers = _get_farmer_auth_headers()

    res = client.post(
        f"/batches/{batch_id}/events",
        json={"event_type": "TEMP_CHECK", "event_data": "Nhiệt độ 5°C"},
        headers=headers,
    )
    event_id = res.json()["id"]

    # 1. Thử UPDATE qua ORM -> bị chặn bởi SQLAlchemy listener (PermissionError)
    with session_factory() as session:
        evt = session.get(BatchEvent, event_id)
        assert evt is not None
        evt.event_type = "HACKED_EVENT"
        with pytest.raises(PermissionError, match="S-11: Batch events are append-only and cannot be updated."):
            session.commit()
        session.rollback()

    # 2. Thử UPDATE trực tiếp bằng câu lệnh SQL thô -> bị chặn bởi DB Trigger (BEFORE UPDATE ON batch_events)
    with session_factory() as session:
        with pytest.raises(Exception) as exc_info:
            session.execute(
                text("UPDATE batch_events SET event_type = 'HACKED_SQL' WHERE id = :id"),
                {"id": event_id},
            )
            session.commit()
        assert "S-11: Updates to batch_events table are strictly prohibited" in str(exc_info.value)
        session.rollback()

    # Kiểm tra dữ liệu trong DB vẫn nguyên vẹn không bị thay đổi
    with session_factory() as session:
        evt_after = session.get(BatchEvent, event_id)
        assert evt_after.event_type == "TEMP_CHECK"


def test_thu_delete_event_bi_tu_choi(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    """Test 4: Thử DELETE event bị từ chối ở cả tầng ORM và tầng Database (Triggers)."""
    _, batch_id = _create_sample_farm_and_batch(client)
    headers = _get_farmer_auth_headers()

    res = client.post(
        f"/batches/{batch_id}/events",
        json={"event_type": "TRANSPORT", "event_data": "Vận chuyển hàng tới kho An Giang"},
        headers=headers,
    )
    event_id = res.json()["id"]

    # 1. Thử DELETE qua ORM -> bị chặn bởi SQLAlchemy listener (PermissionError)
    with session_factory() as session:
        evt = session.get(BatchEvent, event_id)
        assert evt is not None
        session.delete(evt)
        with pytest.raises(PermissionError, match="S-11: Batch events are append-only and cannot be deleted."):
            session.commit()
        session.rollback()

    # 2. Thử DELETE trực tiếp bằng câu lệnh SQL thô -> bị chặn bởi DB Trigger (BEFORE DELETE ON batch_events)
    with session_factory() as session:
        with pytest.raises(Exception) as exc_info:
            session.execute(
                text("DELETE FROM batch_events WHERE id = :id"),
                {"id": event_id},
            )
            session.commit()
        assert "S-11: Deletions from batch_events table are strictly prohibited" in str(exc_info.value)
        session.rollback()

    # Kiểm tra bản ghi vẫn tồn tại trong DB
    with session_factory() as session:
        evt_after = session.get(BatchEvent, event_id)
        assert evt_after is not None
        assert evt_after.id == event_id


def test_api_khong_cung_cap_duong_dan_sua_xoa_event(client: TestClient) -> None:
    """Test 5: API không cung cấp các endpoint PUT, PATCH, DELETE hợp lệ cho event."""
    _, batch_id = _create_sample_farm_and_batch(client)
    headers = _get_farmer_auth_headers()

    res_post = client.post(
        f"/batches/{batch_id}/events",
        json={"event_type": "INSPECTION", "event_data": "Kiểm tra chất lượng"},
        headers=headers,
    )
    event_id = res_post.json()["id"]

    # Gọi PUT /batches/{batch_id}/events/{event_id} -> 404/405
    res_put1 = client.put(f"/batches/{batch_id}/events/{event_id}", json={"event_type": "HACK"}, headers=headers)
    assert res_put1.status_code in (404, 405)

    # Gọi DELETE /batches/{batch_id}/events/{event_id} -> 404/405
    res_del1 = client.delete(f"/batches/{batch_id}/events/{event_id}", headers=headers)
    assert res_del1.status_code in (404, 405)

    # Gọi PUT /events/{event_id} -> 404/405
    res_put2 = client.put(f"/events/{event_id}", json={"event_type": "HACK"}, headers=headers)
    assert res_put2.status_code in (404, 405)

    # Gọi DELETE /events/{event_id} -> 404/405
    res_del2 = client.delete(f"/events/{event_id}", headers=headers)
    assert res_del2.status_code in (404, 405)
