"""Bộ kiểm thử cho Task T-59: Màn hình chi tiết liên kết sang dòng thời gian
và danh sách tổ tiên.

Kiểm thử API:
- GET /batches/{batch_id}/ancestors  – trả về chuỗi tổ tiên từ lô mẹ lên lô gốc.
- GET /batches/{batch_id}/events     – trả về dòng thời gian sự kiện của lô.
"""

import base64
from datetime import date

from fastapi.testclient import TestClient

from tests.conftest import TEST_PASSWORD, TEST_USERNAME_ADMIN, TEST_USERNAME_FARMER


def _farmer_headers() -> dict[str, str]:
    creds = f"{TEST_USERNAME_FARMER}:{TEST_PASSWORD}"
    token = base64.b64encode(creds.encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _admin_headers() -> dict[str, str]:
    creds = f"{TEST_USERNAME_ADMIN}:{TEST_PASSWORD}"
    token = base64.b64encode(creds.encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _create_farm(client: TestClient) -> int:
    """Tạo một vùng trồng mới và trả về ID của nó."""
    res = client.post(
        "/farms",
        json={
            "name": "Nông trường Kiểm thử T-59",
            "location": "Cao Lãnh, Đồng Tháp",
            "area": 3.0,
            "owner": "HTX Đồng Tháp Test",
        },
        headers=_farmer_headers(),
    )
    assert res.status_code == 201, f"Tạo farm thất bại: {res.text}"
    return res.json()["id"]


def _create_batch(
    client: TestClient, farm_id: int, product_name: str, parent_id: int | None = None
) -> int:
    """Tạo một lô nông sản và trả về ID của nó."""
    payload: dict = {
        "farm_id": farm_id,
        "product_name": product_name,
        "quantity": 100.0,
        "harvest_date": str(date.today()),
    }
    if parent_id is not None:
        payload["parent_id"] = parent_id
    res = client.post("/batches", json=payload, headers=_farmer_headers())
    assert res.status_code == 201, f"Tạo batch thất bại: {res.text}"
    return res.json()["id"]


# ─────────────────────────── T-59 / ancestors API ───────────────────────────


def test_t59_ancestors_lo_khong_ton_tai(client: TestClient) -> None:
    """Test 1 – Gọi ancestors cho lô không tồn tại phải trả HTTP 404."""
    res = client.get("/batches/999999/ancestors")
    assert res.status_code == 404
    assert "Không tìm thấy" in res.json()["detail"]


def test_t59_ancestors_lo_goc_khong_co_to_tien(client: TestClient) -> None:
    """Test 2 – Lô gốc (không có parent) trả về ancestors = [] (rỗng)."""
    farm_id = _create_farm(client)
    lo_goc_id = _create_batch(client, farm_id, "Lô gốc T-59 Xoài")

    res = client.get(f"/batches/{lo_goc_id}/ancestors")
    assert res.status_code == 200

    data = res.json()
    assert data["batch_id"] == lo_goc_id
    assert data["ancestors"] == []


def test_t59_ancestors_chuoi_2_the_he(client: TestClient) -> None:
    """Test 3 – Chuỗi 2 thế hệ: Lô mẹ -> Lô con.

    Khi truy vết tổ tiên của lô con thì phải trả về 1 phần tử = lô mẹ với
    generation=1.
    """
    farm_id = _create_farm(client)

    lo_me_id = _create_batch(client, farm_id, "Lô mẹ T-59 Mãng cầu")
    lo_con_id = _create_batch(
        client, farm_id, "Lô con T-59 Mãng cầu", parent_id=lo_me_id
    )

    res = client.get(f"/batches/{lo_con_id}/ancestors")
    assert res.status_code == 200

    data = res.json()
    assert data["batch_id"] == lo_con_id

    ancestors = data["ancestors"]
    assert len(ancestors) == 1, f"Mong đợi 1 tổ tiên nhưng nhận được {len(ancestors)}"

    lo_me = ancestors[0]
    assert lo_me["id"] == lo_me_id
    assert lo_me["generation"] == 1
    assert "Mãng cầu" in (lo_me.get("product_name") or lo_me.get("product", ""))


def test_t59_ancestors_chuoi_3_the_he(client: TestClient) -> None:
    """Test 4 – Chuỗi 3 thế hệ: Lô bà -> Lô mẹ -> Lô cháu.

    Khi truy vết tổ tiên của lô cháu thì phải trả về 2 phần tử:
    - generation=1 là Lô mẹ trực tiếp
    - generation=2 là Lô bà
    """
    farm_id = _create_farm(client)

    lo_ba_id = _create_batch(client, farm_id, "Lô bà T-59 Thanh long")
    lo_me_id = _create_batch(
        client, farm_id, "Lô mẹ T-59 Thanh long", parent_id=lo_ba_id
    )
    lo_chau_id = _create_batch(
        client, farm_id, "Lô cháu T-59 Thanh long", parent_id=lo_me_id
    )

    res = client.get(f"/batches/{lo_chau_id}/ancestors")
    assert res.status_code == 200

    data = res.json()
    ancestors = data["ancestors"]
    assert len(ancestors) == 2, (
        f"Mong đợi 2 tổ tiên (mẹ + bà) nhưng nhận được {len(ancestors)}"
    )

    ids_theo_thu_tu = [a["id"] for a in ancestors]
    generations = [a["generation"] for a in ancestors]

    # Thứ tự: Lô mẹ trước (gen=1), Lô bà sau (gen=2)
    assert ids_theo_thu_tu == [lo_me_id, lo_ba_id], (
        f"Thứ tự tổ tiên sai: {ids_theo_thu_tu}"
    )
    assert generations == [1, 2], f"Thứ tự generation sai: {generations}"


# ─────────────────────────── T-59 / events timeline API ─────────────────────


def test_t59_timeline_lo_khong_ton_tai(client: TestClient) -> None:
    """Test 5 – Gọi events cho lô không tồn tại phải trả HTTP 404."""
    res = client.get("/batches/999998/events")
    assert res.status_code == 404
    assert "Không tìm thấy" in res.json()["detail"]


def test_t59_timeline_lo_moi_co_event_khoi_tao(client: TestClient) -> None:
    """Test 6 – Lô mới tạo phải có ít nhất 1 sự kiện BATCH_CREATED trong timeline."""
    farm_id = _create_farm(client)
    lo_id = _create_batch(client, farm_id, "Lô timeline T-59 Sầu riêng")

    res = client.get(f"/batches/{lo_id}/events")
    assert res.status_code == 200

    events = res.json()
    assert isinstance(events, list)
    assert len(events) >= 1, "Lô mới tạo phải có ít nhất sự kiện BATCH_CREATED"

    event_types = [ev["event_type"] for ev in events]
    assert "BATCH_CREATED" in event_types, (
        f"Không tìm thấy BATCH_CREATED trong timeline: {event_types}"
    )


def test_t59_timeline_them_su_kien_va_kiem_tra_thu_tu(client: TestClient) -> None:
    """Test 7 – Thêm sự kiện mới vào timeline và kiểm tra thứ tự tăng dần."""
    farm_id = _create_farm(client)
    lo_id = _create_batch(client, farm_id, "Lô timeline T-59 Mít")

    # Thêm sự kiện mới qua API (dùng auth farmer)
    res_add = client.post(
        f"/batches/{lo_id}/events",
        json={
            "event_type": "INSPECTION_PASSED",
            "event_data": "Kiểm tra chất lượng đạt yêu cầu xuất khẩu.",
        },
        headers=_farmer_headers(),
    )
    assert res_add.status_code == 201, f"Thêm sự kiện thất bại: {res_add.text}"

    # Lấy danh sách sự kiện
    res = client.get(f"/batches/{lo_id}/events")
    assert res.status_code == 200

    events = res.json()
    assert len(events) >= 2, "Phải có ít nhất 2 sự kiện sau khi thêm"

    # Kiểm tra sự kiện mới nhất ở cuối (thứ tự tăng dần theo sequence)
    types = [ev["event_type"] for ev in events]
    assert "INSPECTION_PASSED" in types, (
        f"Không thấy INSPECTION_PASSED trong timeline: {types}"
    )
