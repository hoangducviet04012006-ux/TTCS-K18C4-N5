"""Test chức năng gộp nhiều lô cùng sản phẩm thành một lô lớn.

Bao phủ các yêu cầu:
1. Gộp thành công 2 lô cùng sản phẩm.
2. Gộp thành công 3 lô cùng sản phẩm.
3. Tổng quantity chính xác.
4. Không cho gộp dưới 2 lô (ít hơn 2 phần tử hoặc các ID trùng nhau).
5. Không cho gộp các sản phẩm khác nhau.
6. Không cho gộp batch không tồn tại.
7. Không cho gộp batch của organization khác (multi-tenant isolation).
8. Kiểm tra rollback nếu transaction lỗi (không làm mất dữ liệu).
9. Kiểm tra ghi audit log đúng định dạng (action merge và create).
10. Kiểm tra chức năng CRUD lô và vùng trồng cũ vẫn hoạt động tốt.
"""

from datetime import date
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.models import AuditLog, Batch, Farm, Organization, User
from app.security import hash_password
from tests.conftest import (
    TEST_PASSWORD,
    TEST_USERNAME_ADMIN,
    TEST_USERNAME_FARMER,
)

FARM_PAYLOAD = {
    "name": "Vùng trồng Cà chua Đức Trọng",
    "location": "Đức Trọng, Lâm Đồng",
    "area": 3.0,
    "owner": "HTX Nông nghiệp Đức Trọng",
}


def _auth(username: str = TEST_USERNAME_FARMER) -> tuple[str, str]:
    """Thông tin HTTP Basic auth."""
    return username, TEST_PASSWORD


def _create_farm(
    client: TestClient,
    username: str = TEST_USERNAME_FARMER,
) -> dict:
    """Tạo nhanh 1 farm test."""
    resp = client.post("/farms", json=FARM_PAYLOAD, auth=_auth(username))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_batch(
    client: TestClient,
    farm_id: int,
    product_name: str = "Cà chua",
    quantity: float = 100.0,
    harvest_date: str = "2026-03-01",
    username: str = TEST_USERNAME_FARMER,
) -> dict:
    """Tạo nhanh 1 batch test."""
    payload = {
        "farm_id": farm_id,
        "product_name": product_name,
        "quantity": quantity,
        "harvest_date": harvest_date,
    }
    resp = client.post("/batches", json=payload, auth=_auth(username))
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_gop_thanh_cong_2_lo_cung_san_pham(client: TestClient) -> None:
    """1. Gộp thành công 2 lô cùng sản phẩm."""
    farm = _create_farm(client)
    b1 = _create_batch(client, farm["id"], "Cà chua", 100.0, "2026-03-01")
    b2 = _create_batch(client, farm["id"], "Cà chua", 150.0, "2026-03-05")

    merge_payload = {
        "batch_ids": [b1["id"], b2["id"]],
    }
    resp = client.post("/batches/merge", json=merge_payload, auth=_auth())
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["product_name"] == "Cà chua"
    assert data["total_quantity"] == 250.0
    assert data["merged_batch_ids"] == [b1["id"], b2["id"]]
    assert data["new_batch"]["quantity"] == 250.0
    assert data["new_batch"]["product_name"] == "Cà chua"
    assert data["new_batch"]["harvest_date"] == "2026-03-05"

    # Kiểm tra danh sách batch sau khi gộp
    batches_resp = client.get("/batches")
    assert batches_resp.status_code == 200
    current_batches = batches_resp.json()
    assert len(current_batches) == 1
    assert current_batches[0]["id"] == data["new_batch"]["id"]
    assert current_batches[0]["quantity"] == 250.0


def test_gop_thanh_cong_3_lo_cung_san_pham(client: TestClient) -> None:
    """2. Gộp thành công 3 lô cùng sản phẩm với tổng quantity chính xác."""
    farm = _create_farm(client)
    b1 = _create_batch(client, farm["id"], "Cà chua", 100.0, "2026-03-01")
    b2 = _create_batch(client, farm["id"], "Cà chua", 150.0, "2026-03-02")
    b3 = _create_batch(client, farm["id"], "Cà chua", 200.0, "2026-03-03")

    merge_payload = {
        "batch_ids": [b1["id"], b2["id"], b3["id"]],
    }
    resp = client.post("/batches/merge", json=merge_payload, auth=_auth())
    assert resp.status_code == 200
    data = resp.json()

    assert data["product_name"] == "Cà chua"
    assert data["total_quantity"] == 450.0
    assert len(data["merged_batch_ids"]) == 3
    assert data["new_batch"]["quantity"] == 450.0

    # Lô cũ không còn tồn tại qua GET /batches/{id}
    for old_id in [b1["id"], b2["id"], b3["id"]]:
        assert client.get(f"/batches/{old_id}").status_code == 404


def test_tuy_chon_farm_id_va_harvest_date_khi_gop(client: TestClient) -> None:
    """3. Kiểm tra tuỳ chọn truyền farm_id và harvest_date tuỳ chỉnh."""
    farm1 = _create_farm(client)
    farm2_resp = client.post(
        "/farms",
        json={**FARM_PAYLOAD, "name": "Vùng trồng Cà chua số 2"},
        auth=_auth(),
    )
    farm2 = farm2_resp.json()

    b1 = _create_batch(client, farm1["id"], "Xoài Cát", 50.0, "2026-02-01")
    b2 = _create_batch(client, farm1["id"], "Xoài Cát", 70.0, "2026-02-02")

    merge_payload = {
        "batch_ids": [b1["id"], b2["id"]],
        "farm_id": farm2["id"],
        "harvest_date": "2026-02-10",
    }
    resp = client.post("/batches/merge", json=merge_payload, auth=_auth())
    assert resp.status_code == 200
    data = resp.json()
    assert data["new_batch"]["farm_id"] == farm2["id"]
    assert data["new_batch"]["harvest_date"] == "2026-02-10"


def test_khong_cho_gop_duoi_2_lo(client: TestClient) -> None:
    """4. Không cho gộp dưới 2 lô (1 lô, mảng rỗng, hoặc 2 ID trùng lặp)."""
    farm = _create_farm(client)
    b1 = _create_batch(client, farm["id"], "Cà chua", 100.0)

    # 1 lô -> 422 Unprocessable Entity (Pydantic min_length=2)
    resp1 = client.post(
        "/batches/merge", json={"batch_ids": [b1["id"]]}, auth=_auth()
    )
    assert resp1.status_code == 422

    # Mảng rỗng -> 422
    resp2 = client.post(
        "/batches/merge", json={"batch_ids": []}, auth=_auth()
    )
    assert resp2.status_code == 422

    # 2 ID trùng nhau -> 400 Bad Request
    resp3 = client.post(
        "/batches/merge",
        json={"batch_ids": [b1["id"], b1["id"]]},
        auth=_auth(),
    )
    assert resp3.status_code == 400
    assert "ít nhất 2 lô" in resp3.json()["detail"]


def test_khong_cho_gop_cac_san_pham_khac_nhau(client: TestClient) -> None:
    """5. Không cho gộp các sản phẩm khác nhau -> trả 400 Bad Request."""
    farm = _create_farm(client)
    b1 = _create_batch(client, farm["id"], "Cà chua", 100.0)
    b2 = _create_batch(client, farm["id"], "Dưa leo", 150.0)

    merge_payload = {"batch_ids": [b1["id"], b2["id"]]}
    resp = client.post("/batches/merge", json=merge_payload, auth=_auth())
    assert resp.status_code == 400
    assert "cùng tên sản phẩm" in resp.json()["detail"]

    # Cả 2 batch cũ vẫn còn nguyên
    assert len(client.get("/batches").json()) == 2


def test_khong_cho_gop_batch_khong_ton_tai(client: TestClient) -> None:
    """6. Không cho gộp batch không tồn tại -> trả 404 Not Found."""
    farm = _create_farm(client)
    b1 = _create_batch(client, farm["id"], "Cà chua", 100.0)

    merge_payload = {"batch_ids": [b1["id"], 9999]}
    resp = client.post("/batches/merge", json=merge_payload, auth=_auth())
    assert resp.status_code == 404
    assert "9999" in resp.json()["detail"]


def test_khong_cho_gop_khac_organization(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """7. Không cho gộp lô thuộc tổ chức khác (multi-tenant isolation)."""
    with session_factory() as session:
        org_other = Organization(
            name="Hợp tác xã Khác",
            code="HTX-KHAC",
            description="Tổ chức thứ 2",
        )
        session.add(org_other)
        session.flush()

        user_other = User(
            email="farmer_other@gmail.com",
            username="farmer_other",
            password=hash_password(TEST_PASSWORD),
            role="farmer",
            organization_id=org_other.id,
        )
        session.add(user_other)
        session.flush()

        farm_other = Farm(
            name="Vườn của HTX Khác",
            location="Cần Thơ",
            area=2.0,
            owner="Nông dân khác",
            organization_id=org_other.id,
        )
        session.add(farm_other)
        session.flush()

        b_other = Batch(
            farm_id=farm_other.id,
            product_name="Cà chua",
            quantity=100.0,
            harvest_date=date(2026, 3, 1),
        )
        session.add(b_other)
        session.commit()
        b_other_id = b_other.id

    # Farmer hiện tại tạo 1 lô của tổ chức mình
    farm_my = _create_farm(client)
    b_my = _create_batch(client, farm_my["id"], "Cà chua", 150.0)

    # Cố tình gộp lô của tổ chức mình với lô của tổ chức khác
    merge_payload = {"batch_ids": [b_my["id"], b_other_id]}
    resp = client.post("/batches/merge", json=merge_payload, auth=_auth())
    assert resp.status_code == 403
    assert "tổ chức khác" in resp.json()["detail"]


def test_rollback_neu_transaction_loi(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """8. Kiểm tra rollback nếu có lỗi: dữ liệu giữ nguyên, không ghi log."""
    farm = _create_farm(client)
    b1 = _create_batch(client, farm["id"], "Cà chua", 100.0)
    b2 = _create_batch(client, farm["id"], "Cà chua", 150.0)

    err = SQLAlchemyError("DB Error")
    with patch.object(Session, "commit", side_effect=err):
        merge_payload = {"batch_ids": [b1["id"], b2["id"]]}
        resp = client.post("/batches/merge", json=merge_payload, auth=_auth())
        assert resp.status_code == 500

    # Kiểm tra dữ liệu: 2 batch cũ vẫn còn nguyên vẹn
    batches_resp = client.get("/batches")
    assert len(batches_resp.json()) == 2

    # Kiểm tra audit logs: chỉ có log tạo farm và 2 log tạo batch ban đầu
    with session_factory() as session:
        logs = list(session.scalars(select(AuditLog)).all())
        # Không có log "merge" nào
        merge_logs = [log for log in logs if log.action == "merge"]
        assert len(merge_logs) == 0


def test_kiem_tra_audit_log_sau_khi_gop(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """9. Kiểm tra audit log: ghi đúng user, action merge và create."""
    farm = _create_farm(client, TEST_USERNAME_FARMER)
    b1 = _create_batch(
        client, farm["id"], "Cà chua", 100.0, username=TEST_USERNAME_FARMER
    )
    b2 = _create_batch(
        client, farm["id"], "Cà chua", 150.0, username=TEST_USERNAME_FARMER
    )

    resp = client.post(
        "/batches/merge",
        json={"batch_ids": [b1["id"], b2["id"]]},
        auth=_auth(TEST_USERNAME_FARMER),
    )
    assert resp.status_code == 200
    new_batch_id = resp.json()["new_batch"]["id"]

    # Đọc audit logs qua API bằng tài khoản admin
    logs_resp = client.get("/audit-logs", auth=_auth(TEST_USERNAME_ADMIN))
    assert logs_resp.status_code == 200
    logs = logs_resp.json()

    # Mới nhất trước:
    # 1. create batch new_batch_id
    # 2. merge batch b2["id"]
    # 3. merge batch b1["id"]
    actions = [
        (item["action"], item["entity"], item["entity_id"], item["username"])
        for item in logs
    ]
    assert actions[0] == (
        "create", "batch", new_batch_id, TEST_USERNAME_FARMER
    )
    assert actions[1] == (
        "merge", "batch", b2["id"], TEST_USERNAME_FARMER
    )
    assert actions[2] == (
        "merge", "batch", b1["id"], TEST_USERNAME_FARMER
    )


def test_chuc_nang_crud_cu_van_hoat_dong(client: TestClient) -> None:
    """10. Kiểm tra toàn bộ CRUD cũ của Batch & Farm vẫn hoạt động."""
    # 1. Tạo farm
    farm = _create_farm(client)
    # 2. Xem farm
    assert client.get(f"/farms/{farm['id']}", auth=_auth()).status_code == 200
    # 3. Sửa farm
    put_farm_resp = client.put(
        f"/farms/{farm['id']}",
        json={**FARM_PAYLOAD, "area": 4.5},
        auth=_auth(),
    )
    assert put_farm_resp.status_code == 200
    assert put_farm_resp.json()["area"] == 4.5

    # 4. Tạo batch
    b = _create_batch(client, farm["id"], "Xoài", 200.0)
    # 5. Xem batch
    assert client.get(f"/batches/{b['id']}").status_code == 200
    # 6. Sửa batch
    put_batch_resp = client.put(
        f"/batches/{b['id']}",
        json={
            "farm_id": farm["id"],
            "product_name": "Xoài loại 1",
            "quantity": 250.0,
            "harvest_date": "2026-03-02",
        },
        auth=_auth(),
    )
    assert put_batch_resp.status_code == 200
    assert put_batch_resp.json()["product_name"] == "Xoài loại 1"
    assert put_batch_resp.json()["quantity"] == 250.0

    # 7. Xoá batch (bằng admin)
    del_b_resp = client.delete(
        f"/batches/{b['id']}", auth=_auth(TEST_USERNAME_ADMIN)
    )
    assert del_b_resp.status_code == 200

    # 8. Xoá farm (bằng admin)
    del_f_resp = client.delete(
        f"/farms/{farm['id']}", auth=_auth(TEST_USERNAME_ADMIN)
    )
    assert del_f_resp.status_code == 200
