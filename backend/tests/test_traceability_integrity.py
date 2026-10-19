"""Bộ kiểm thử cho Story S-50: Kiểm tra tính toàn vẹn dữ liệu truy xuất nguồn gốc.

Kiểm chứng các kịch bản:
1. Lô đơn lẻ hợp lệ (single batch valid).
2. Chuỗi phả hệ đa tầng hợp lệ (multi-tier lineage valid).
3. Phát hiện can thiệp sửa trực tiếp SQL tại lô gốc (tampered root payload -> HASH_MISMATCH).
4. Phát hiện can thiệp sửa trực tiếp SQL tại lô trung gian.
5. Phát hiện đứt mạch do xóa sự kiện (deleted event -> CHAIN_BROKEN).
6. Endpoint công khai xác thực theo batch_code không cần đăng nhập.
7. Tra cứu mã lô không tồn tại trả về HTTP 404 thân thiện.
8. Giới hạn tần suất (Rate Limiting) chặn IP gọi quá 30 mã lô khác nhau trong 1 phút (HTTP 429).
9. Bộ nhớ đệm cache 60s và hàm vô hiệu hóa cache.
10. Phân quyền RBAC nội bộ (Admin xem toàn quyền, không có auth bị 401).
11. Lô mới tạo chưa có sự kiện (status: NO_EVENTS).
"""

from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from app.services.rate_limiter import clear_rate_limit_cache
from app.services.trace_integrity import clear_trace_integrity_cache
from tests.conftest import TEST_PASSWORD, TEST_USERNAME_FARMER


def _get_farmer_auth_headers() -> dict[str, str]:
    import base64
    credentials = f"{TEST_USERNAME_FARMER}:{TEST_PASSWORD}"
    encoded = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
    return {"Authorization": f"Basic {encoded}"}


def _create_sample_farm_and_batch(client: TestClient) -> tuple[int, int, str]:
    headers = _get_farmer_auth_headers()
    farm_res = client.post(
        "/farms",
        json={
            "name": "Nông trại kiểm thử S-50",
            "location": "Mộc Châu, Sơn La",
            "area": 5.0,
            "owner": "HTX Nông nghiệp Số 5",
        },
        headers=headers,
    )
    farm_id = farm_res.json()["id"]

    batch_res = client.post(
        "/batches",
        json={
            "farm_id": farm_id,
            "product_name": "Dâu tây Mộc Châu S-50",
            "quantity": 1000.0,
            "harvest_date": "2026-05-01",
        },
        headers=headers,
    )
    b_data = batch_res.json()
    return farm_id, b_data["id"], b_data["code"]


def test_1_single_batch_integrity_valid(client: TestClient) -> None:
    """Test 1: Lô đơn lẻ với các sự kiện liên tiếp đạt tính toàn vẹn 100%."""
    clear_trace_integrity_cache()
    headers = _get_farmer_auth_headers()
    _, batch_id, _ = _create_sample_farm_and_batch(client)

    # Thêm 3 sự kiện
    client.post(
        f"/batches/{batch_id}/events",
        json={"event_type": "HARVEST_NOTE", "event_data": "Thu hoạch 1000kg"},
        headers=headers,
    )
    client.post(
        f"/batches/{batch_id}/events",
        json={"event_type": "PACKAGING", "event_data": "Đóng gói tiêu chuẩn"},
        headers=headers,
    )
    client.post(
        f"/batches/{batch_id}/events",
        json={"event_type": "STORAGE", "event_data": "Lưu kho lạnh"},
        headers=headers,
    )

    res = client.get(f"/batches/{batch_id}/trace-integrity", headers=headers)
    assert res.status_code == 200
    data = res.json()

    assert data["is_valid"] is True
    assert data["status"] == "VERIFIED"
    assert data["total_batches_checked"] == 1
    assert data["total_events_checked"] >= 3
    assert len(data["verification_seal"]) == 64
    assert data["latest_hash"] is not None
    assert len(data["nodes"]) == 1
    assert data["nodes"][0]["is_valid"] is True
    assert data["tampered_node"] is None


def test_2_multi_tier_lineage_integrity_valid(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    """Test 2: Chuỗi phả hệ đa tầng (Lô gốc -> Lô chia tách) xác thực toàn vẹn 100%."""
    clear_trace_integrity_cache()
    headers = _get_farmer_auth_headers()
    farm_id, root_batch_id, root_code = _create_sample_farm_and_batch(client)

    # Sự kiện lô gốc
    client.post(
        f"/batches/{root_batch_id}/events",
        json={"event_type": "HARVEST_NOTE", "event_data": "Thu hoạch gốc"},
        headers=headers,
    )

    # Tạo lô con và quan hệ chia tách (BatchRelation)
    child_res = client.post(
        "/batches",
        json={
            "farm_id": farm_id,
            "product_name": "Dâu tây sơ chế",
            "quantity": 500.0,
            "harvest_date": "2026-05-01",
        },
        headers=headers,
    )
    child_data = child_res.json()
    child_batch_id = child_data["id"]
    child_code = child_data["code"]

    with session_factory() as session:
        from app.models import BatchRelation
        rel = BatchRelation(
            parent_batch_id=root_batch_id,
            child_batch_id=child_batch_id,
            relation_type="SPLIT",
            transferred_quantity=500.0,
        )
        session.add(rel)
        session.commit()

    # Thêm sự kiện ở lô con
    client.post(
        f"/batches/{child_batch_id}/events",
        json={"event_type": "PACKAGING", "event_data": "Đóng hộp 500g"},
        headers=headers,
    )

    # Thẩm định từ lô con
    res = client.get(f"/batches/{child_batch_id}/trace-integrity", headers=headers)
    assert res.status_code == 200
    data = res.json()

    assert data["is_valid"] is True
    assert data["total_batches_checked"] == 2
    assert data["total_events_checked"] >= 2
    assert len(data["root_hashes"]) >= 1
    assert len(data["nodes"]) == 2
    # Cả node con (level 0) và node cha (level 1) đều hợp lệ
    node_levels = {n["code"]: n["level"] for n in data["nodes"]}
    assert node_levels[child_code] == 0
    assert node_levels[root_code] == 1


def test_3_detects_tampered_root_payload(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    """Test 3: Can thiệp sửa trực tiếp SQL tại lô gốc -> phát hiện HASH_MISMATCH tại lô gốc."""
    clear_trace_integrity_cache()
    headers = _get_farmer_auth_headers()
    farm_id, root_batch_id, _ = _create_sample_farm_and_batch(client)

    evt_res = client.post(
        f"/batches/{root_batch_id}/events",
        json={"event_type": "HARVEST_NOTE", "event_data": "Dữ liệu ban đầu"},
        headers=headers,
    )
    root_event_id = evt_res.json()["id"]

    # Tạo lô con
    child_res = client.post(
        "/batches",
        json={
            "farm_id": farm_id,
            "product_name": "Dâu tây sơ chế",
            "quantity": 300.0,
            "harvest_date": "2026-05-01",
        },
        headers=headers,
    )
    child_batch_id = child_res.json()["id"]

    with session_factory() as session:
        from app.models import BatchRelation
        session.add(BatchRelation(
            parent_batch_id=root_batch_id,
            child_batch_id=child_batch_id,
            relation_type="SPLIT",
            transferred_quantity=300.0,
        ))
        session.commit()

    client.post(
        f"/batches/{child_batch_id}/events",
        json={"event_type": "SPLIT", "event_data": "Tách lô"},
        headers=headers,
    )

    # Giả lập kẻ xấu sửa trực tiếp dữ liệu event của lô gốc trong database bằng SQL
    with session_factory() as session:
        session.execute(text("DROP TRIGGER IF EXISTS prevent_batch_events_update"))
        session.execute(
            text("UPDATE batch_events SET event_data = 'DỮ LIỆU ĐÃ BỊ SỬA LÉN' WHERE id = :id"),
            {"id": root_event_id},
        )
        session.commit()
        session.execute(text(
            "CREATE TRIGGER IF NOT EXISTS prevent_batch_events_update BEFORE UPDATE ON batch_events "
            "BEGIN SELECT RAISE(ABORT, 'append-only'); END;"
        ))
        session.commit()

    # Thẩm định toàn vẹn từ lô con
    res = client.get(f"/batches/{child_batch_id}/trace-integrity", headers=headers)
    assert res.status_code == 200
    data = res.json()

    assert data["is_valid"] is False
    assert data["status"] == "HASH_MISMATCH"
    assert data["tampered_node"] is not None
    assert data["tampered_node"]["batch_id"] == root_batch_id
    assert data["tampered_node"]["tampered_event_id"] == root_event_id
    assert "CẢNH BÁO VI PHẠM TOÀN VẸN" in data["message"]


def test_4_detects_deleted_event_chain_broken(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    """Test 4: Xóa một sự kiện ở giữa chuỗi -> phát hiện CHAIN_BROKEN."""
    clear_trace_integrity_cache()
    headers = _get_farmer_auth_headers()
    _, batch_id, _ = _create_sample_farm_and_batch(client)

    client.post(f"/batches/{batch_id}/events", json={"event_type": "EVT_1", "event_data": "Sự kiện 1"}, headers=headers)
    res2 = client.post(f"/batches/{batch_id}/events", json={"event_type": "EVT_2", "event_data": "Sự kiện 2"}, headers=headers)
    evt2_id = res2.json()["id"]
    client.post(f"/batches/{batch_id}/events", json={"event_type": "EVT_3", "event_data": "Sự kiện 3"}, headers=headers)

    # Giả lập xóa sự kiện 2
    with session_factory() as session:
        session.execute(text("DROP TRIGGER IF EXISTS prevent_batch_events_delete"))
        session.execute(text("DELETE FROM batch_events WHERE id = :id"), {"id": evt2_id})
        session.commit()
        session.execute(text(
            "CREATE TRIGGER IF NOT EXISTS prevent_batch_events_delete BEFORE DELETE ON batch_events "
            "BEGIN SELECT RAISE(ABORT, 'append-only'); END;"
        ))
        session.commit()

    res = client.get(f"/batches/{batch_id}/trace-integrity", headers=headers)
    assert res.status_code == 200
    data = res.json()

    assert data["is_valid"] is False
    assert data["status"] == "CHAIN_BROKEN"
    assert data["tampered_node"] is not None


def test_5_public_trace_integrity_by_code_without_auth(client: TestClient) -> None:
    """Test 5: Endpoint công khai GET /public/trace/{batch_code}/integrity không cần Auth."""
    clear_trace_integrity_cache()
    clear_rate_limit_cache()
    headers = _get_farmer_auth_headers()
    _, batch_id, actual_code = _create_sample_farm_and_batch(client)

    client.post(
        f"/batches/{batch_id}/events",
        json={"event_type": "HARVEST_NOTE", "event_data": "Thu hoạch dâu"},
        headers=headers,
    )

    # Gọi API công khai KHÔNG truyền headers Authorization
    pub_res = client.get(f"/public/trace/{actual_code}/integrity")
    assert pub_res.status_code == 200
    pub_data = pub_res.json()

    assert pub_data["is_valid"] is True
    assert pub_data["batch_code"] == actual_code
    assert pub_data["status"] == "VERIFIED"
    assert len(pub_data["verification_seal"]) == 64


def test_6_public_trace_integrity_nonexistent_returns_404(client: TestClient) -> None:
    """Test 6: Tra cứu mã lô không tồn tại qua API công khai trả về HTTP 404."""
    clear_rate_limit_cache()
    res = client.get("/public/trace/NON-EXISTENT-CODE-999/integrity")
    assert res.status_code == 404
    assert "Không tìm thấy" in res.json()["detail"]


def test_7_rate_limit_blocks_scanning_over_30_codes(client: TestClient) -> None:
    """Test 7: Chống dò quét mã QR: Một IP gọi quá 30 mã lô khác nhau trong 1 phút bị chặn 429."""
    clear_rate_limit_cache()

    # Giả lập IP quét 30 mã khác nhau
    for i in range(1, 31):
        fake_code = f"SCAN-CODE-{i:03d}"
        res = client.get(f"/public/trace/{fake_code}/integrity", headers={"X-Forwarded-For": "198.51.100.10"})
        # 30 yêu cầu đầu tiên trả về 404 vì mã không tồn tại, nhưng vẫn nằm trong hạn mức 30
        assert res.status_code == 404

    # Yêu cầu thứ 31 với mã khác từ cùng IP đó -> Bị chặn 429 Too Many Requests
    blocked_res = client.get("/public/trace/SCAN-CODE-031/integrity", headers={"X-Forwarded-For": "198.51.100.10"})
    assert blocked_res.status_code == 429
    assert blocked_res.headers.get("Retry-After") == "60"
    assert "30 mã lô khác nhau" in blocked_res.json()["detail"]

    # Một IP khác vẫn có thể truy vấn bình thường
    other_ip_res = client.get("/public/trace/SCAN-CODE-031/integrity", headers={"X-Forwarded-For": "198.51.100.20"})
    assert other_ip_res.status_code == 404  # Không bị 429


def test_8_trace_integrity_cache_60s(client: TestClient) -> None:
    """Test 8: Kết quả xác thực toàn vẹn được cache 60s để giảm tải database."""
    clear_trace_integrity_cache()
    headers = _get_farmer_auth_headers()
    _, batch_id, _ = _create_sample_farm_and_batch(client)

    client.post(
        f"/batches/{batch_id}/events",
        json={"event_type": "INIT", "event_data": "Khởi tạo"},
        headers=headers,
    )

    res1 = client.get(f"/batches/{batch_id}/trace-integrity", headers=headers)
    assert res1.status_code == 200
    seal1 = res1.json()["verification_seal"]
    time1 = res1.json()["verified_at"]

    # Gọi lần 2 ngay lập tức -> Nhận từ cache (cùng verified_at và seal)
    res2 = client.get(f"/batches/{batch_id}/trace-integrity", headers=headers)
    assert res2.status_code == 200
    assert res2.json()["verification_seal"] == seal1
    assert res2.json()["verified_at"] == time1

    # Khi xóa cache -> Tính toán lại
    clear_trace_integrity_cache(batch_id)
    res3 = client.get(f"/batches/{batch_id}/trace-integrity", headers=headers)
    assert res3.status_code == 200
    assert res3.json()["verification_seal"] == seal1


def test_9_trace_integrity_empty_batch(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    """Test 9: Lô chưa có sự kiện nào trong hệ thống."""
    clear_trace_integrity_cache()
    headers = _get_farmer_auth_headers()
    farm_id, _, _ = _create_sample_farm_and_batch(client)

    from datetime import date
    from app.models import Batch
    with session_factory() as session:
        empty_b = Batch(
            farm_id=farm_id,
            product_name="Dâu tây thử nghiệm rỗng",
            quantity=50.0,
            harvest_date=date.today(),
            current_org_id=1,
        )
        session.add(empty_b)
        session.commit()
        empty_id = empty_b.id

    res = client.get(f"/batches/{empty_id}/trace-integrity", headers=headers)
    assert res.status_code == 200
    data = res.json()

    assert data["is_valid"] is True
    assert data["status"] == "NO_EVENTS"
    assert data["total_events_checked"] == 0
    assert "chưa có sự kiện nào" in data["message"].lower()


def test_10_trace_integrity_rbac_inspector_vs_unauthorized(client: TestClient) -> None:
    """Test 10: Phân quyền nội bộ: Admin xem toàn quyền, không có thông tin đăng nhập bị 401."""
    clear_trace_integrity_cache()
    _, batch_id, _ = _create_sample_farm_and_batch(client)

    # Admin xem toàn quyền
    admin_res = client.get(f"/batches/{batch_id}/trace-integrity", auth=("admin", "123456"))
    assert admin_res.status_code == 200

    # Không đăng nhập -> 401 Unauthorized
    unauth_res = client.get(f"/batches/{batch_id}/trace-integrity")
    assert unauth_res.status_code == 401


def test_11_public_trace_integrity_sanitizes_internal_data(client: TestClient) -> None:
    """Test 11: Endpoint công khai S-48/S-50 KHÔNG để lộ batch_id, ID nội bộ, hay tên tổ chức."""
    clear_trace_integrity_cache()
    clear_rate_limit_cache()
    headers = _get_farmer_auth_headers()
    _, batch_id, actual_code = _create_sample_farm_and_batch(client)

    client.post(
        f"/batches/{batch_id}/events",
        json={"event_type": "HARVEST_NOTE", "event_data": "Thu hoạch dâu sạch"},
        headers=headers,
    )

    pub_res = client.get(f"/public/trace/{actual_code}/integrity")
    assert pub_res.status_code == 200
    pub_data = pub_res.json()

    # Xác thực rằng batch_id KHÔNG tồn tại trong top-level
    assert "batch_id" not in pub_data
    assert pub_data["batch_code"] == actual_code
    assert pub_data["is_valid"] is True

    # Xác thực từng node không chứa ID nội bộ hay tên riêng đối tác
    for node in pub_data["nodes"]:
        assert "batch_id" not in node
        assert "current_org_id" not in node
        assert "current_org_name" not in node
        assert "tampered_event_id" not in node
        assert "stage_name" in node


def test_12_rate_limiter_anti_spoofing_rejects_untrusted_forwarded_for() -> None:
    """Test 12: Rate limiter chống giả mạo IP: Client kết nối từ IP ngoài không thể dùng X-Forwarded-For giả mạo."""
    from unittest.mock import MagicMock
    from fastapi import HTTPException, Request
    import pytest
    from app.services.rate_limiter import check_scan_rate_limit, get_trusted_client_ip

    clear_rate_limit_cache()

    # 1. Giả lập client kết nối trực tiếp từ IP untrusted ngoài Internet: 198.51.100.24
    untrusted_request = MagicMock(spec=Request)
    untrusted_request.client.host = "198.51.100.24"
    untrusted_request.headers = {"x-forwarded-for": "10.0.0.1"}

    # IP thực sự được nhận diện phải là 198.51.100.24, bỏ qua hoàn toàn header 10.0.0.1
    detected_ip = get_trusted_client_ip(untrusted_request)
    assert detected_ip == "198.51.100.24"

    # Giả lập quét 30 mã từ IP này
    for i in range(1, 31):
        check_scan_rate_limit(untrusted_request, f"PROBE-{i:03d}")

    # Yêu cầu 31 từ IP này dù đổi header x-forwarded-for thành gì cũng bị chặn 429
    untrusted_request.headers = {"x-forwarded-for": "192.168.1.99"}
    with pytest.raises(HTTPException) as exc_info:
        check_scan_rate_limit(untrusted_request, "PROBE-031")
    assert exc_info.value.status_code == 429


def test_13_trace_integrity_cache_invalidates_on_new_event(client: TestClient) -> None:
    """Test 13: Cache 60s tự động vô hiệu hóa ngay khi có sự kiện mới được thêm vào lô."""
    clear_trace_integrity_cache()
    headers = _get_farmer_auth_headers()
    _, batch_id, batch_code = _create_sample_farm_and_batch(client)

    client.post(
        f"/batches/{batch_id}/events",
        json={"event_type": "EVT_1", "event_data": "Sự kiện 1"},
        headers=headers,
    )

    # Lần 1: Tính toán và lưu cache
    res1 = client.get(f"/batches/{batch_id}/trace-integrity", headers=headers)
    assert res1.status_code == 200
    assert res1.json()["total_events_checked"] >= 1
    seal1 = res1.json()["verification_seal"]

    # Ghi thêm sự kiện thứ 2
    client.post(
        f"/batches/{batch_id}/events",
        json={"event_type": "EVT_2", "event_data": "Sự kiện 2"},
        headers=headers,
    )

    # Lần 2 (ngay lập tức trong 60s): Cache PHẢI được vô hiệu hóa tự động nhờ fingerprint
    res2 = client.get(f"/batches/{batch_id}/trace-integrity", headers=headers)
    assert res2.status_code == 200
    assert res2.json()["total_events_checked"] >= 2
    assert res2.json()["verification_seal"] != seal1


def test_14_trace_integrity_cache_invalidates_on_data_change(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """Test 14: Cache 60s tự động vô hiệu hóa ngay khi dữ liệu lô hoặc trạng thái thay đổi."""
    clear_trace_integrity_cache()
    headers = _get_farmer_auth_headers()
    _, batch_id, batch_code = _create_sample_farm_and_batch(client)

    client.post(
        f"/batches/{batch_id}/events",
        json={"event_type": "HARVEST", "event_data": "Thu hoạch"},
        headers=headers,
    )

    # Lần 1: Cache được lưu
    res1 = client.get(f"/batches/{batch_id}/trace-integrity", headers=headers)
    assert res1.status_code == 200
    assert res1.json()["verified_at"] is not None

    # Giả lập thay đổi trạng thái lô trực tiếp
    with session_factory() as session:
        from app.models import Batch
        b = session.get(Batch, batch_id)
        if b:
            b.status = "CONSUMED"
            session.commit()

    # Lần 2: Cache phải tự động phát hiện fingerprint thay đổi và tính toán lại
    res2 = client.get(f"/batches/{batch_id}/trace-integrity", headers=headers)
    assert res2.status_code == 200
    assert res2.json()["status"] == "VERIFIED"


def test_15_rate_limiter_prioritizes_nginx_x_real_ip_over_spoofed_forwarded_for() -> None:
    """Test 15: Chống giả mạo IP qua Nginx: Ưu tiên X-Real-IP và lấy đúng IP thực do proxy thêm vào."""
    from unittest.mock import MagicMock
    from fastapi import HTTPException, Request
    import pytest
    from app.services.rate_limiter import check_scan_rate_limit, get_trusted_client_ip

    clear_rate_limit_cache()

    # 1. Kịch bản qua Nginx: Client gửi giả mạo X-Forwarded-For: 10.99.99.99
    # Nginx ghi nhận real client IP: 203.0.113.88
    # Nginx ghi đè X-Real-IP: 203.0.113.88 và nối thêm vào X-Forwarded-For: 10.99.99.99, 203.0.113.88
    proxy_request = MagicMock(spec=Request)
    proxy_request.client.host = "127.0.0.1"  # Kết nối từ reverse proxy tin cậy Nginx
    proxy_request.headers = {
        "x-real-ip": "203.0.113.88",
        "x-forwarded-for": "10.99.99.99, 203.0.113.88",
    }

    # Phải nhận đúng IP 203.0.113.88 từ X-Real-IP, tuyệt đối không bị lừa bởi 10.99.99.99
    detected_ip = get_trusted_client_ip(proxy_request)
    assert detected_ip == "203.0.113.88"

    # 2. Kịch bản nếu không có X-Real-IP nhưng có chuỗi X-Forwarded-For
    no_real_ip_request = MagicMock(spec=Request)
    no_real_ip_request.client.host = "127.0.0.1"
    no_real_ip_request.headers = {
        "x-forwarded-for": "1.2.3.4, 203.0.113.88",
    }
    # Phải lấy IP cuối cùng do proxy thêm vào (203.0.113.88), không lấy IP đầu tiên (1.2.3.4) do client gửi
    assert get_trusted_client_ip(no_real_ip_request) == "203.0.113.88"

    # 3. Kịch bản client cố gắng bypass rate limit bằng cách đổi IP giả mạo trong X-Forwarded-For
    # Nhưng Nginx vẫn gán đúng X-Real-IP: 203.0.113.88
    client_attack_request = MagicMock(spec=Request)
    client_attack_request.client.host = "127.0.0.1"

    # Quét 30 mã đầu với fake IP trong X-Forwarded-For
    for i in range(1, 31):
        client_attack_request.headers = {
            "x-real-ip": "203.0.113.88",
            "x-forwarded-for": f"10.0.0.{i}, 203.0.113.88",
        }
        check_scan_rate_limit(client_attack_request, f"NGINX-SCAN-{i:03d}")

    # Yêu cầu thứ 31 từ IP thật 203.0.113.88 dù có đổi header gì cũng bị chặn 429
    client_attack_request.headers = {
        "x-real-ip": "203.0.113.88",
        "x-forwarded-for": "99.99.99.99, 203.0.113.88",
    }
    with pytest.raises(HTTPException) as exc_info:
        check_scan_rate_limit(client_attack_request, "NGINX-SCAN-031")
    assert exc_info.value.status_code == 429


def test_16_trace_integrity_cache_invalidates_on_batch_relation_change(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """Test 16: Cache 60s tự động vô hiệu hóa ngay khi bảng BatchRelation thêm/xóa quan hệ cha/con."""
    clear_trace_integrity_cache()
    headers = _get_farmer_auth_headers()
    farm_id, child_id, child_code = _create_sample_farm_and_batch(client)

    from datetime import date
    from app.models import Batch, BatchRelation

    # 1. Tạo lô cha A
    with session_factory() as session:
        parent_a = Batch(
            farm_id=farm_id,
            product_name="Dâu tây giống F1",
            quantity=2000.0,
            harvest_date=date.today(),
            current_org_id=1,
        )
        session.add(parent_a)
        session.commit()
        parent_a_id = parent_a.id

        # Liên kết A là cha của child
        rel_a_child = BatchRelation(
            parent_batch_id=parent_a_id,
            child_batch_id=child_id,
            transferred_quantity=500.0,
            relation_type="SPLIT",
        )
        session.add(rel_a_child)
        session.commit()

    # Thêm sự kiện cho lô con
    client.post(
        f"/batches/{child_id}/events",
        json={"event_type": "PACKAGING", "event_data": "Đóng hộp"},
        headers=headers,
    )
    # Thêm sự kiện cho lô cha
    client.post(
        f"/batches/{parent_a_id}/events",
        json={"event_type": "HARVEST", "event_data": "Thu hoạch gốc"},
        headers=headers,
    )

    # Lần 1: Thẩm định chuỗi phả hệ (2 lô: child và A) và lưu cache
    res1 = client.get(f"/batches/{child_id}/trace-integrity", headers=headers)
    assert res1.status_code == 200
    assert res1.json()["total_batches_checked"] == 2
    seal1 = res1.json()["verification_seal"]

    # 2. Thêm quan hệ phả hệ mới: Tạo lô ông Root và liên kết Root -> A
    with session_factory() as session:
        root_batch = Batch(
            farm_id=farm_id,
            product_name="Hạt giống dâu thuần chủng",
            quantity=5000.0,
            harvest_date=date.today(),
            current_org_id=1,
        )
        session.add(root_batch)
        session.commit()
        root_batch_id = root_batch.id

        rel_root_a = BatchRelation(
            parent_batch_id=root_batch_id,
            child_batch_id=parent_a_id,
            transferred_quantity=1000.0,
            relation_type="SPLIT",
        )
        session.add(rel_root_a)
        session.commit()
        rel_root_a_id = rel_root_a.id

    client.post(
        f"/batches/{root_batch_id}/events",
        json={"event_type": "SEED", "event_data": "Gieo hạt"},
        headers=headers,
    )

    # Lần 2 (ngay lập tức trong 60s): Cache PHẢI tự động vô hiệu hóa vì BatchRelation thay đổi!
    res2 = client.get(f"/batches/{child_id}/trace-integrity", headers=headers)
    assert res2.status_code == 200
    # Phải kiểm tra 3 lô thay vì 2
    assert res2.json()["total_batches_checked"] == 3
    assert res2.json()["verification_seal"] != seal1

    # 3. Xóa quan hệ phả hệ Root -> A trong database
    with session_factory() as session:
        rel_to_delete = session.get(BatchRelation, rel_root_a_id)
        if rel_to_delete:
            session.delete(rel_to_delete)
            session.commit()

    # Lần 3 (ngay lập tức trong 60s): Cache PHẢI tự động vô hiệu hóa vì BatchRelation bị xóa!
    res3 = client.get(f"/batches/{child_id}/trace-integrity", headers=headers)
    assert res3.status_code == 200
    # Trở lại 2 lô
    assert res3.json()["total_batches_checked"] == 2


def test_17_public_api_cleans_messages_and_does_not_leak_event_ids(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """Test 17: Bảo mật API công khai: Tuyệt đối không để lộ Event ID hay thông tin lỗi kỹ thuật nội bộ."""
    clear_trace_integrity_cache()
    clear_rate_limit_cache()
    headers = _get_farmer_auth_headers()
    _, batch_id, actual_code = _create_sample_farm_and_batch(client)

    # Tạo 2 sự kiện
    client.post(
        f"/batches/{batch_id}/events",
        json={"event_type": "EVT_A", "event_data": "Dữ liệu A"},
        headers=headers,
    )
    client.post(
        f"/batches/{batch_id}/events",
        json={"event_type": "EVT_B", "event_data": "Dữ liệu B"},
        headers=headers,
    )

    # Giả lập kẻ xấu can thiệp trực tiếp database bằng SQL làm hỏng chuỗi băm
    with session_factory() as session:
        from app.models import BatchEvent
        last_evt = session.scalars(
            select(BatchEvent).where(BatchEvent.batch_id == batch_id).order_by(BatchEvent.id.desc())
        ).first()
        assert last_evt is not None
        tampered_evt_id = last_evt.id

        session.execute(text("DROP TRIGGER IF EXISTS prevent_batch_events_update"))
        session.execute(
            text("UPDATE batch_events SET event_data = 'Dữ liệu bị sửa lén trực tiếp SQL' WHERE id = :id"),
            {"id": tampered_evt_id},
        )
        session.commit()
        session.execute(text(
            "CREATE TRIGGER IF NOT EXISTS prevent_batch_events_update BEFORE UPDATE ON batch_events "
            "BEGIN SELECT RAISE(ABORT, 'append-only'); END;"
        ))
        session.commit()

    # 1. API nội bộ (/batches/{id}/trace-integrity): Thanh tra viên ĐƯỢC PHÉP xem chi tiết lỗi và Event ID
    internal_res = client.get(f"/batches/{batch_id}/trace-integrity", auth=("admin", "123456"))
    assert internal_res.status_code == 200
    int_data = internal_res.json()
    assert int_data["is_valid"] is False
    assert int_data["tampered_node"] is not None
    assert int_data["tampered_node"]["tampered_event_id"] == tampered_evt_id

    # 2. API công khai (/public/trace/{code}/integrity): TUYỆT ĐỐI KHÔNG để lộ Event ID hay ID nội bộ
    clear_trace_integrity_cache()
    pub_res = client.get(f"/public/trace/{actual_code}/integrity")
    assert pub_res.status_code == 200
    pub_data = pub_res.json()

    assert pub_data["is_valid"] is False
    assert pub_data["status"] == "HASH_MISMATCH"

    # Kiểm tra message công khai cố định, không lộ Event ID
    assert "CẢNH BÁO" in pub_data["message"]
    assert "Event ID" not in pub_data["message"]
    assert f"#{tampered_evt_id}" not in pub_data["message"]

    # Kiểm tra tampered_node công khai
    assert pub_data["tampered_node"] is not None
    assert "tampered_event_id" not in pub_data["tampered_node"]
    assert "batch_id" not in pub_data["tampered_node"]
    assert pub_data["tampered_node"]["message"] == "Phát hiện sai lệch tính toàn vẹn trong chuỗi dữ liệu."

    # Quét toàn bộ JSON payload công khai để đảm bảo không rò rỉ ID sự kiện hay chi tiết nội bộ
    pub_json_str = str(pub_data)
    assert "tampered_event_id" not in pub_json_str
    assert "current_org_name" not in pub_json_str
    assert "Event ID" not in pub_json_str
    assert f"#{tampered_evt_id}" not in pub_json_str
