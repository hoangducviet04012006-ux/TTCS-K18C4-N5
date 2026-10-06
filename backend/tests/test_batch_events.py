import pytest
from httpx import AsyncClient
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.models import Batch, BatchEvent

@pytest.mark.asyncio
async def test_batch_events_chain(async_client: AsyncClient, db: Session, normal_user_token: dict, test_farm: dict):
    # 1. Tạo lô mới -> sinh sự kiện khởi tạo với hash hợp lệ.
    batch_payload = {
        "farm_id": test_farm["id"],
        "product_name": "Test Event Sourcing",
        "quantity": 100,
        "harvest_date": "2026-10-10"
    }
    create_resp = await async_client.post(
        "/batches",
        json=batch_payload,
        headers=normal_user_token
    )
    assert create_resp.status_code == 201
    batch_id = create_resp.json()["id"]

    # Kiểm tra chuỗi sự kiện
    events_resp = await async_client.get(f"/batches/{batch_id}/events")
    assert events_resp.status_code == 200
    events_data = events_resp.json()
    assert events_data["is_valid"] is True
    assert len(events_data["events"]) == 1
    assert events_data["events"][0]["event_type"] == "CREATED"
    assert events_data["events"][0]["previous_hash"] == "0" * 64

    # 2. Cập nhật thông tin lô -> sinh sự kiện tiếp theo có liên kết previous_hash chính xác.
    update_payload = {
        "farm_id": test_farm["id"],
        "product_name": "Test Event Sourcing - Updated",
        "quantity": 150,
        "harvest_date": "2026-10-10"
    }
    update_resp = await async_client.put(
        f"/batches/{batch_id}",
        json=update_payload,
        headers=normal_user_token
    )
    assert update_resp.status_code == 200

    # Kiểm tra lại chuỗi
    events_resp2 = await async_client.get(f"/batches/{batch_id}/events")
    events_data2 = events_resp2.json()
    assert events_data2["is_valid"] is True
    assert len(events_data2["events"]) == 2
    assert events_data2["events"][1]["event_type"] == "UPDATED"
    
    # 3. Thử can thiệp sửa đổi trái phép dữ liệu lịch sử trong database
    db.execute(
        text("UPDATE batch_events SET payload = :p WHERE id = :id"),
        {"p": "tampered payload", "id": events_data2["events"][0]["id"]}
    )
    db.commit()

    # Xác thực phát hiện sai lệch
    events_resp3 = await async_client.get(f"/batches/{batch_id}/events")
    events_data3 = events_resp3.json()
    assert events_data3["is_valid"] is False
    assert len(events_data3["errors"]) > 0
    assert events_data3["errors"][0]["error"] == "Hash mismatch"
