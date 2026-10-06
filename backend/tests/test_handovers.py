"""Kiểm thử tự động chức năng Bàn giao lô hàng (SCRUM-27 / S-15 & SCRUM-28 / S-16).

Bao phủ các ca kiểm thử:
1. Bàn giao thành công:
   - Tổ chức sở hữu gửi yêu cầu bàn giao sang tổ chức khác.
   - Lưu bản ghi handover với trạng thái PENDING.
   - Ghi nhận sự kiện HANDOVER_PENDING vào batch_events trong cùng transaction.
2. Chặn bàn giao lần 2 khi đang pending:
   - Khi lô hàng đã có 1 yêu cầu bàn giao PENDING, không thể tạo thêm yêu cầu mới (HTTP 400).
3. Từ chối không có lý do hoặc lý do < 10 ký tự bị chặn:
   - action = 'REJECT' nhưng không có lý do hoặc lý do ngắn bị từ chối (HTTP 400/422).
4. Nhận lô thành công đổi current_org_id:
   - Tổ chức nhận phản hồi action = 'ACCEPT'.
   - Handover cập nhật status = 'ACCEPTED'.
   - Lô hàng đổi current_org_id thành tổ chức nhận.
   - Ghi nhận sự kiện HANDOVER_ACCEPTED vào batch_events.
5. Từ chối hợp lệ:
   - action = 'REJECT' kèm lý do >= 10 ký tự -> status = 'REJECTED', giữ nguyên chủ sở hữu, ghi sự kiện HANDOVER_REJECTED.
6. Chặn bàn giao cho chính mình:
   - to_org_id trùng với current_org_id -> HTTP 400.
7. Chặn tổ chức không sở hữu lô thực hiện bàn giao:
   - User không thuộc tổ chức đang giữ lô -> HTTP 403.
8. Chặn tổ chức không phải bên nhận phản hồi:
   - User không thuộc to_org_id gọi respond -> HTTP 403.
9. GET /api/handovers/pending:
   - Trả về đúng danh sách lô PENDING gửi tới tổ chức của user.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    EVENT_HANDOVER_ACCEPTED,
    EVENT_HANDOVER_PENDING,
    HANDOVER_ACCEPTED,
    HANDOVER_PENDING,
    HANDOVER_REJECTED,
    Batch,
    Farm,
    Organization,
    ROLE_ADMIN,
    ROLE_FARMER,
    User,
)
from app.security import hash_password

PASSWORD = "test-password-123"


@pytest.fixture()
def setup_handover_data(session_factory: sessionmaker[Session]) -> dict[str, int]:
    """Khởi tạo 2 tổ chức (HTX Đồng Tháp & HTX Tiền Giang), user và 1 lô hàng tại HTX Đồng Tháp."""
    with session_factory() as session:
        # 1. Tạo tổ chức ĐT
        org_dt = session.scalar(select(Organization).where(Organization.code == "HTX-DT"))
        if org_dt is None:
            org_dt = Organization(
                name="Hợp tác xã Nông sản An Toàn Đồng Tháp",
                code="HTX-DT",
                description="HTX Đồng Tháp",
            )
            session.add(org_dt)
            session.flush()

        # Tạo tổ chức TG
        org_tg = session.scalar(select(Organization).where(Organization.code == "HTX-TG"))
        if org_tg is None:
            org_tg = Organization(
                name="Hợp tác xã Nông nghiệp Sạch Tiền Giang",
                code="HTX-TG",
                description="HTX Tiền Giang",
            )
            session.add(org_tg)
            session.flush()

        # 2. Tạo users cho từng tổ chức
        users_to_create = [
            ("farmer_dt", ROLE_FARMER, org_dt.id),
            ("admin_dt", ROLE_ADMIN, org_dt.id),
            ("farmer_tg", ROLE_FARMER, org_tg.id),
            ("admin_tg", ROLE_ADMIN, org_tg.id),
        ]
        for username, role, org_id in users_to_create:
            if not session.scalar(select(User).where(User.username == username)):
                session.add(
                    User(
                        username=username,
                        password=hash_password(PASSWORD),
                        role=role,
                        organization_id=org_id,
                    )
                )
        session.flush()

        # 3. Tạo thửa đất thuộc HTX Đồng Tháp
        farm_dt = Farm(
            name="Vườn xoài Cát Chu Cao Lãnh",
            location="Cao Lãnh, Đồng Tháp",
            area=2.5,
            owner="HTX Đồng Tháp",
            organization_id=org_dt.id,
        )
        session.add(farm_dt)
        session.flush()

        # 4. Tạo lô nông sản ban đầu thuộc HTX Đồng Tháp
        batch = Batch(
            farm_id=farm_dt.id,
            product_name="Xoài Cát Chu xuất khẩu",
            quantity=500.0,
            harvest_date=date(2026, 1, 15),
            current_org_id=org_dt.id,
        )
        session.add(batch)
        session.commit()

        return {
            "org_dt_id": org_dt.id,
            "org_tg_id": org_tg.id,
            "farm_dt_id": farm_dt.id,
            "batch_id": batch.id,
        }


# ==============================================================================
# 1. BÀN GIAO THÀNH CÔNG & GHI BATCH EVENT
# ==============================================================================

def test_ban_giao_thanh_cong(client: TestClient, setup_handover_data: dict[str, int]) -> None:
    """Tạo yêu cầu bàn giao thành công, status PENDING và ghi sự kiện HANDOVER_PENDING."""
    batch_id = setup_handover_data["batch_id"]
    org_tg_id = setup_handover_data["org_tg_id"]
    org_dt_id = setup_handover_data["org_dt_id"]

    payload = {
        "to_org_id": org_tg_id,
        "note": "Bàn giao 500kg xoài cát Chu đợt 1 sang Tiền Giang",
    }
    response = client.post(
        f"/api/batches/{batch_id}/handover",
        json=payload,
        auth=("farmer_dt", PASSWORD),
    )
    assert response.status_code == 201
    data = response.json()
    assert data["batch_id"] == batch_id
    assert data["from_org_id"] == org_dt_id
    assert data["to_org_id"] == org_tg_id
    assert data["status"] == HANDOVER_PENDING
    assert data["reject_reason"] is None

    # Kiểm tra sự kiện trong batch_events
    events_resp = client.get(f"/api/batches/{batch_id}/events")
    assert events_resp.status_code == 200
    events = events_resp.json()
    assert len(events) >= 1
    assert events[0]["event_type"] == EVENT_HANDOVER_PENDING
    assert events[0]["from_org_id"] == org_dt_id
    assert events[0]["to_org_id"] == org_tg_id
    assert events[0]["notes"] == payload["note"]


# ==============================================================================
# 2. CHẶN BÀN GIAO LẦN 2 KHI ĐANG PENDING
# ==============================================================================

def test_chan_ban_giao_lan_2_khi_dang_pending(
    client: TestClient, setup_handover_data: dict[str, int]
) -> None:
    """Không cho phép tạo bàn giao thứ 2 nếu lô hàng đang có bàn giao PENDING."""
    batch_id = setup_handover_data["batch_id"]
    org_tg_id = setup_handover_data["org_tg_id"]

    # Lần 1: Thành công
    first_resp = client.post(
        f"/api/batches/{batch_id}/handover",
        json={"to_org_id": org_tg_id, "note": "Bàn giao lần 1"},
        auth=("farmer_dt", PASSWORD),
    )
    assert first_resp.status_code == 201

    # Lần 2: Bị chặn (HTTP 400)
    second_resp = client.post(
        f"/api/batches/{batch_id}/handover",
        json={"to_org_id": org_tg_id, "note": "Bàn giao lần 2 khi chưa duyệt lần 1"},
        auth=("farmer_dt", PASSWORD),
    )
    assert second_resp.status_code == 400
    assert "PENDING" in second_resp.json()["detail"]


# ==============================================================================
# 3. TỪ CHỐI KHÔNG CÓ LÝ DO BỊ CHẶN
# ==============================================================================

def test_tu_choi_khong_co_ly_do_bi_chan(
    client: TestClient, setup_handover_data: dict[str, int]
) -> None:
    """Từ chối bàn giao mà không có lý do hoặc lý do < 10 ký tự thì bị chặn (HTTP 400/422)."""
    batch_id = setup_handover_data["batch_id"]
    org_tg_id = setup_handover_data["org_tg_id"]

    # Tạo yêu cầu bàn giao
    handover_resp = client.post(
        f"/api/batches/{batch_id}/handover",
        json={"to_org_id": org_tg_id},
        auth=("farmer_dt", PASSWORD),
    )
    assert handover_resp.status_code == 201
    handover_id = handover_resp.json()["id"]

    # 3.1: Không gửi reject_reason
    resp_no_reason = client.post(
        f"/api/handovers/{handover_id}/respond",
        json={"action": "REJECT"},
        auth=("farmer_tg", PASSWORD),
    )
    assert resp_no_reason.status_code in (400, 422)

    # 3.2: Gửi reject_reason quá ngắn (< 10 ký tự)
    resp_short_reason = client.post(
        f"/api/handovers/{handover_id}/respond",
        json={"action": "REJECT", "reject_reason": "Từ chối"},
        auth=("farmer_tg", PASSWORD),
    )
    assert resp_short_reason.status_code in (400, 422)


# ==============================================================================
# 4. NHẬN LÔ THÀNH CÔNG ĐỔI CURRENT_ORG_ID
# ==============================================================================

def test_nhan_lo_thanh_cong_doi_current_org_id(
    client: TestClient, setup_handover_data: dict[str, int], session_factory: sessionmaker[Session]
) -> None:
    """Tổ chức nhận ACCEPT bàn giao: status thành ACCEPTED và batch.current_org_id đổi sang org nhận."""
    batch_id = setup_handover_data["batch_id"]
    org_tg_id = setup_handover_data["org_tg_id"]

    # Tạo handover từ ĐT sang TG
    create_resp = client.post(
        f"/api/batches/{batch_id}/handover",
        json={"to_org_id": org_tg_id, "note": "Bàn giao lô sang Tiền Giang"},
        auth=("farmer_dt", PASSWORD),
    )
    assert create_resp.status_code == 201
    handover_id = create_resp.json()["id"]

    # TG xác nhận nhận lô
    accept_resp = client.post(
        f"/api/handovers/{handover_id}/respond",
        json={"action": "ACCEPT"},
        auth=("farmer_tg", PASSWORD),
    )
    assert accept_resp.status_code == 200
    data = accept_resp.json()
    assert data["status"] == HANDOVER_ACCEPTED

    # Kiểm tra database: batch.current_org_id đã chuyển sang org_tg_id
    with session_factory() as session:
        batch = session.get(Batch, batch_id)
        assert batch is not None
        assert batch.current_org_id == org_tg_id

    # Kiểm tra sự kiện HANDOVER_ACCEPTED
    events_resp = client.get(f"/api/batches/{batch_id}/events")
    assert events_resp.status_code == 200
    events = events_resp.json()
    assert events[0]["event_type"] == EVENT_HANDOVER_ACCEPTED
    assert events[0]["to_org_id"] == org_tg_id


# ==============================================================================
# 5. TỪ CHỐI HỢP LỆ VỚI LÝ DO >= 10 KÝ TỰ
# ==============================================================================

def test_tu_choi_hop_le_giu_nguyen_chu_so_huu(
    client: TestClient, setup_handover_data: dict[str, int], session_factory: sessionmaker[Session]
) -> None:
    """Từ chối có lý do >= 10 ký tự: status REJECTED, current_org_id giữ nguyên tổ chức gửi."""
    batch_id = setup_handover_data["batch_id"]
    org_tg_id = setup_handover_data["org_tg_id"]
    org_dt_id = setup_handover_data["org_dt_id"]

    # Tạo bàn giao
    create_resp = client.post(
        f"/api/batches/{batch_id}/handover",
        json={"to_org_id": org_tg_id},
        auth=("farmer_dt", PASSWORD),
    )
    handover_id = create_resp.json()["id"]

    # TG từ chối với lý do rõ ràng
    reject_reason = "Chất lượng quả chưa đạt độ ngọt và có dấu hiệu nứt vỏ"
    reject_resp = client.post(
        f"/api/handovers/{handover_id}/respond",
        json={"action": "REJECT", "reject_reason": reject_reason},
        auth=("farmer_tg", PASSWORD),
    )
    assert reject_resp.status_code == 200
    data = reject_resp.json()
    assert data["status"] == HANDOVER_REJECTED
    assert data["reject_reason"] == reject_reason

    # Kiểm tra chủ sở hữu lô vẫn là org_dt_id (không đổi)
    with session_factory() as session:
        batch = session.get(Batch, batch_id)
        assert batch is not None
        assert batch.current_org_id == org_dt_id

    # Sau khi từ chối, có thể bàn giao lại vì không còn PENDING
    retry_resp = client.post(
        f"/api/batches/{batch_id}/handover",
        json={"to_org_id": org_tg_id, "note": "Bàn giao lại sau khi chọn lọc lại quả"},
        auth=("farmer_dt", PASSWORD),
    )
    assert retry_resp.status_code == 201


# ==============================================================================
# 6. CÁC CA RÀNG BUỘC BẢO MẬT VÀ PHÂN QUYỀN
# ==============================================================================

def test_chan_ban_giao_cho_chinh_minh(
    client: TestClient, setup_handover_data: dict[str, int]
) -> None:
    """Không cho phép bàn giao cho chính tổ chức đang nắm giữ lô (HTTP 400)."""
    batch_id = setup_handover_data["batch_id"]
    org_dt_id = setup_handover_data["org_dt_id"]

    response = client.post(
        f"/api/batches/{batch_id}/handover",
        json={"to_org_id": org_dt_id},
        auth=("farmer_dt", PASSWORD),
    )
    assert response.status_code == 400
    assert "chính" in response.json()["detail"].lower()


def test_chan_to_chuc_khong_so_huu_lo_ban_giao(
    client: TestClient, setup_handover_data: dict[str, int]
) -> None:
    """User thuộc Tiền Giang không thể bàn giao lô đang thuộc sở hữu của Đồng Tháp (HTTP 403)."""
    batch_id = setup_handover_data["batch_id"]
    org_tg_id = setup_handover_data["org_tg_id"]

    response = client.post(
        f"/api/batches/{batch_id}/handover",
        json={"to_org_id": org_tg_id},
        auth=("farmer_tg", PASSWORD),
    )
    assert response.status_code == 403


def test_chan_to_chuc_khong_phai_ben_nhan_phan_hoi(
    client: TestClient, setup_handover_data: dict[str, int]
) -> None:
    """Bên gửi (Đồng Tháp) không được phép tự chấp nhận hoặc từ chối bàn giao của chính mình (HTTP 403)."""
    batch_id = setup_handover_data["batch_id"]
    org_tg_id = setup_handover_data["org_tg_id"]

    # ĐT tạo bàn giao sang TG
    create_resp = client.post(
        f"/api/batches/{batch_id}/handover",
        json={"to_org_id": org_tg_id},
        auth=("farmer_dt", PASSWORD),
    )
    handover_id = create_resp.json()["id"]

    # ĐT cố tình gọi respond
    illegal_resp = client.post(
        f"/api/handovers/{handover_id}/respond",
        json={"action": "ACCEPT"},
        auth=("farmer_dt", PASSWORD),
    )
    assert illegal_resp.status_code == 403


def test_danh_sach_pending_loc_dung_theo_to_chuc(
    client: TestClient, setup_handover_data: dict[str, int]
) -> None:
    """GET /api/handovers/pending chỉ hiển thị các bàn giao gửi đến tổ chức của user."""
    batch_id = setup_handover_data["batch_id"]
    org_tg_id = setup_handover_data["org_tg_id"]

    # ĐT gửi bàn giao sang TG
    client.post(
        f"/api/batches/{batch_id}/handover",
        json={"to_org_id": org_tg_id, "note": "Gửi sang TG"},
        auth=("farmer_dt", PASSWORD),
    )

    # TG kiểm tra danh sách chờ nhận -> thấy 1 lô
    pending_tg = client.get("/api/handovers/pending", auth=("farmer_tg", PASSWORD))
    assert pending_tg.status_code == 200
    items_tg = pending_tg.json()
    assert len(items_tg) == 1
    assert items_tg[0]["batch_id"] == batch_id

    # ĐT kiểm tra danh sách chờ nhận -> rỗng (vì ĐT là bên gửi, không phải bên nhận)
    pending_dt = client.get("/api/handovers/pending", auth=("farmer_dt", PASSWORD))
    assert pending_dt.status_code == 200
    assert len(pending_dt.json()) == 0
