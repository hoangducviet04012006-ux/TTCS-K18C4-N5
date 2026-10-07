"""Bộ kiểm thử cho Sprint S-12: Kiểm tra toàn vẹn chuỗi sự kiện của một lô
và chỉ ra chính xác chỗ đứt mạch (Cryptographic Hash Chain).
"""

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.events import verify_batch_events_integrity
from tests.conftest import TEST_PASSWORD, TEST_USERNAME_FARMER


def _get_farmer_auth_headers() -> dict[str, str]:
    import base64

    credentials = f"{TEST_USERNAME_FARMER}:{TEST_PASSWORD}"
    encoded = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
    return {"Authorization": f"Basic {encoded}"}


def _create_sample_batch(client: TestClient) -> int:
    headers = _get_farmer_auth_headers()
    farm_res = client.post(
        "/farms",
        json={
            "name": "Vườn xoài kiểm tra S-12",
            "location": "Cao Lãnh, Đồng Tháp",
            "area": 2.0,
            "owner": "HTX Đồng Tháp",
        },
        headers=headers,
    )
    farm_id = farm_res.json()["id"]

    batch_res = client.post(
        "/batches",
        json={
            "farm_id": farm_id,
            "product_name": "Xoài Cát Chu kiểm tra integrity S-12",
            "quantity": 1000.0,
            "harvest_date": "2026-04-01",
        },
        headers=headers,
    )
    return batch_res.json()["id"]


def test_1_chuoi_su_kien_hop_le(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    """Test 1 – Chuỗi hợp lệ: Tạo nhiều event liên tiếp, kết quả kiểm tra integrity phải có `valid = True`."""
    batch_id = _create_sample_batch(client)
    headers = _get_farmer_auth_headers()

    # Thêm 3 sự kiện liên tiếp
    events_payload = [
        {"event_type": "HARVEST", "event_data": "Thu hoạch 1000kg xoài"},
        {"event_type": "PROCESSING", "event_data": "Sơ chế và dán tem truy xuất"},
        {"event_type": "TEMP_CHECK", "event_data": "Bảo quản lạnh 12°C"},
    ]
    for p in events_payload:
        res = client.post(f"/batches/{batch_id}/events", json=p, headers=headers)
        assert res.status_code == 201

    # Gọi API integrity check
    res_integrity = client.get(f"/batches/{batch_id}/integrity")
    assert res_integrity.status_code == 200
    data = res_integrity.json()

    assert data["valid"] is True
    assert data["batch_id"] == batch_id
    assert data["total_events"] >= 4  # Gồm BATCH_CREATED + 3 events
    assert "hợp lệ" in data["message"].lower()

    # Kiểm tra trực tiếp hàm Python
    with session_factory() as session:
        result_direct = verify_batch_events_integrity(session, batch_id)
        assert result_direct["valid"] is True


def test_2_event_bi_sua_du_lieu(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    """Test 2 – Event bị sửa: Thay đổi dữ liệu một event trong môi trường test,
    phải phát hiện đúng event bị sửa (RECORD_HASH_MISMATCH).
    """
    batch_id = _create_sample_batch(client)
    headers = _get_farmer_auth_headers()

    # Thêm sự kiện
    res1 = client.post(
        f"/batches/{batch_id}/events",
        json={"event_type": "HARVEST", "event_data": "Thu hoạch ban đầu 500kg"},
        headers=headers,
    )
    event1_id = res1.json()["id"]

    client.post(
        f"/batches/{batch_id}/events",
        json={"event_type": "TRANSPORT", "event_data": "Vận chuyển đến kho"},
        headers=headers,
    )

    # Trong môi trường test, giả lập sửa dữ liệu trong database (bằng cách tạm thả trigger rồi sửa SQL)
    with session_factory() as session:
        session.execute(text("DROP TRIGGER IF EXISTS prevent_batch_events_update"))
        session.execute(
            text("UPDATE batch_events SET event_data = 'DỮ LIỆU ĐÃ BỊ SỬA TRÁI PHÉP' WHERE id = :id"),
            {"id": event1_id},
        )
        session.commit()
        # Dựng lại trigger sau khi thử nghiệm
        session.execute(
            text(
                """
                CREATE TRIGGER IF NOT EXISTS prevent_batch_events_update
                BEFORE UPDATE ON batch_events
                BEGIN
                    SELECT RAISE(ABORT, 'S-11: Updates to batch_events table are strictly prohibited (append-only log).');
                END;
                """
            )
        )
        session.commit()

    # Chạy kiểm tra toàn vẹn qua API
    res_check = client.get(f"/batches/{batch_id}/integrity")
    assert res_check.status_code == 200
    data = res_check.json()

    assert data["valid"] is False
    assert data["event_id"] == event1_id
    assert data["error_type"] == "RECORD_HASH_MISMATCH"
    assert data["expected_hash"] != data["actual_hash"]
    assert "chỉnh sửa" in data["message"].lower() or "giả mạo" in data["message"].lower()


def test_3_event_bi_xoa(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    """Test 3 – Event bị xóa: Xóa một event trong môi trường test,
    phải phát hiện chính xác vị trí chuỗi bị đứt thông qua prev_hash (PREV_HASH_MISMATCH).
    """
    batch_id = _create_sample_batch(client)
    headers = _get_farmer_auth_headers()

    # Tạo 3 sự kiện E1, E2, E3
    res1 = client.post(
        f"/batches/{batch_id}/events",
        json={"event_type": "EVENT_1", "event_data": "Sự kiện số 1"},
        headers=headers,
    )
    res2 = client.post(
        f"/batches/{batch_id}/events",
        json={"event_type": "EVENT_2", "event_data": "Sự kiện số 2 (Sẽ bị xóa)"},
        headers=headers,
    )
    res3 = client.post(
        f"/batches/{batch_id}/events",
        json={"event_type": "EVENT_3", "event_data": "Sự kiện số 3"},
        headers=headers,
    )

    e1 = res1.json()
    e2_id = res2.json()["id"]
    e3_id = res3.json()["id"]

    # Giả lập xóa Event 2 trực tiếp trong DB (tạm thả trigger delete)
    with session_factory() as session:
        session.execute(text("DROP TRIGGER IF EXISTS prevent_batch_events_delete"))
        session.execute(text("DELETE FROM batch_events WHERE id = :id"), {"id": e2_id})
        session.commit()
        # Dựng lại trigger
        session.execute(
            text(
                """
                CREATE TRIGGER IF NOT EXISTS prevent_batch_events_delete
                BEFORE DELETE ON batch_events
                BEGIN
                    SELECT RAISE(ABORT, 'S-11: Deletions from batch_events table are strictly prohibited (append-only log).');
                END;
                """
            )
        )
        session.commit()

    # Chạy kiểm tra toàn vẹn
    res_check = client.get(f"/batches/{batch_id}/integrity")
    assert res_check.status_code == 200
    data = res_check.json()

    assert data["valid"] is False
    assert data["event_id"] == e3_id  # Sự kiện E3 đứng ngay sau E2 bị phát hiện có prev_hash không khớp với E1
    assert data["error_type"] == "PREV_HASH_MISMATCH"
    assert data["expected_hash"] == e1["record_hash"]
    assert data["actual_hash"] == res3.json()["prev_hash"]
    assert "đứt mạch" in data["message"].lower() or "bị xóa" in data["message"].lower()


def test_prev_hash_bi_thay_doi(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    """Test 4 – prev_hash bị thay đổi: Thay đổi cột prev_hash của một event trong DB."""
    batch_id = _create_sample_batch(client)
    headers = _get_farmer_auth_headers()

    client.post(
        f"/batches/{batch_id}/events",
        json={"event_type": "STEP1", "event_data": "Bước 1"},
        headers=headers,
    )
    res2 = client.post(
        f"/batches/{batch_id}/events",
        json={"event_type": "STEP2", "event_data": "Bước 2"},
        headers=headers,
    )
    e2_id = res2.json()["id"]

    # Giả lập sửa prev_hash của STEP2
    fake_hash = "f" * 64
    with session_factory() as session:
        session.execute(text("DROP TRIGGER IF EXISTS prevent_batch_events_update"))
        session.execute(
            text("UPDATE batch_events SET prev_hash = :fake_hash WHERE id = :id"),
            {"fake_hash": fake_hash, "id": e2_id},
        )
        session.commit()
        session.execute(
            text(
                """
                CREATE TRIGGER IF NOT EXISTS prevent_batch_events_update
                BEFORE UPDATE ON batch_events
                BEGIN
                    SELECT RAISE(ABORT, 'S-11: Updates to batch_events table are strictly prohibited (append-only log).');
                END;
                """
            )
        )
        session.commit()

    res_check = client.get(f"/batches/{batch_id}/integrity")
    assert res_check.status_code == 200
    data = res_check.json()
    assert data["valid"] is False
    assert data["event_id"] == e2_id
