"""Bộ kiểm thử cho Sprint S-25: Trang chi tiết lô nông sản (Batch Detail API)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.models import Batch
from tests.conftest import TEST_PASSWORD, TEST_USERNAME_FARMER


def _get_farmer_auth_headers() -> dict[str, str]:
    import base64

    credentials = f"{TEST_USERNAME_FARMER}:{TEST_PASSWORD}"
    encoded = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
    return {"Authorization": f"Basic {encoded}"}


def test_get_batch_detail_batch_khong_ton_tai(client: TestClient) -> None:
    """Test 1: Gọi API GET /batches/99999 trả về status 404 Not Found."""
    res = client.get("/batches/99999")
    assert res.status_code == 404
    assert "Không tìm thấy" in res.json()["detail"]


def test_get_batch_detail_khong_co_me_khong_co_con(client: TestClient) -> None:
    """Test 2: Lô độc lập (không có lô mẹ và không có lô con)."""
    headers = _get_farmer_auth_headers()
    farm_res = client.post(
        "/farms",
        json={
            "name": "Vườn xoài Cát Chu S-25",
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
            "product_name": "Xoài Cát Chu loại 1",
            "quantity": 1000.0,
            "harvest_date": "2026-05-01",
        },
        headers=headers,
    )
    batch_id = batch_res.json()["id"]

    # Gọi API lấy chi tiết lô
    res = client.get(f"/batches/{batch_id}")
    assert res.status_code == 200
    data = res.json()

    assert data["id"] == batch_id
    assert data["product_name"] == "Xoài Cát Chu loại 1"
    assert data["initial_quantity"] == 1000.0
    assert data["remaining_quantity"] == 1000.0
    assert data["unit"] == "kg"
    assert data["status"] == "Đang lưu kho"
    assert data["farm_name"] == "Vườn xoài Cát Chu S-25"
    assert data["farm_location"] == "Cao Lãnh, Đồng Tháp"
    assert data["parent"] is None
    assert data["children"] == []


def test_get_batch_detail_co_lo_me_va_lo_con(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    """Test 3: Lô có lô mẹ trực tiếp và danh sách lô con trực tiếp."""
    headers = _get_farmer_auth_headers()
    farm_res = client.post(
        "/farms",
        json={
            "name": "Nông trường Xoài Chu S25",
            "location": "Mỹ Xương, Đồng Tháp",
            "area": 3.0,
            "owner": "HTX Đồng Tháp",
        },
        headers=headers,
    )
    farm_id = farm_res.json()["id"]

    # Tạo Lô mẹ (Batch Parent)
    parent_res = client.post(
        "/batches",
        json={
            "farm_id": farm_id,
            "product_name": "Xoài Cát Chu tổng thu hoạch",
            "quantity": 5000.0,
            "harvest_date": "2026-05-10",
        },
        headers=headers,
    )
    parent_id = parent_res.json()["id"]

    from datetime import date

    # Gán quan hệ mẹ - con trực tiếp trong DB
    h_date = date.fromisoformat(parent_res.json()["harvest_date"])
    with session_factory() as session:
        child1 = Batch(
            farm_id=farm_id,
            product_name="Xoài Cát Chu đóng thùng loại A",
            quantity=2000.0,
            remaining_quantity=1800.0,
            harvest_date=h_date,
            parent_id=parent_id,
            status="Đang lưu kho",
            unit="kg",
        )
        child2 = Batch(
            farm_id=farm_id,
            product_name="Xoài Cát Chu chế biến sấy dẻo",
            quantity=1500.0,
            remaining_quantity=1500.0,
            harvest_date=h_date,
            parent_id=parent_id,
            status="Đang chế biến",
            unit="kg",
        )
        session.add_all([child1, child2])
        session.commit()
        child1_id = child1.id
        child2_id = child2.id

    # 1. Kiểm tra lô con #1 -> phải trả về parent là Lô mẹ
    res_child1 = client.get(f"/batches/{child1_id}")
    assert res_child1.status_code == 200
    data_c1 = res_child1.json()
    assert data_c1["parent_id"] == parent_id
    assert data_c1["parent"]["id"] == parent_id
    assert data_c1["parent"]["product_name"] == "Xoài Cát Chu tổng thu hoạch"

    # 2. Kiểm tra Lô mẹ -> phải trả về danh sách 2 lô con
    res_parent = client.get(f"/batches/{parent_id}")
    assert res_parent.status_code == 200
    data_p = res_parent.json()
    assert len(data_p["children"]) == 2
    child_ids = [c["id"] for c in data_p["children"]]
    assert child1_id in child_ids
    assert child2_id in child_ids
