"""Bộ kiểm thử tự động toàn diện SPRINT 2 (T-16 đến T-38).

Kiểm tra đầy đủ 6 yêu cầu kỹ thuật trọng tâm:
1. test_batch_code_generator_10000_unique (T-19)
2. test_hash_consistency_canonical_json (T-24)
3. test_harvest_validation_server_side (T-21)
4. test_atomic_harvest_rollback (T-25)
5. test_tamper_detection_three_cases (T-28, T-30)
6. test_handover_flow_full_lifecycle (T-36, T-37, T-38)
Và kiểm tra bổ sung T-16, T-17 (Sản phẩm & Quyền Admin).
"""

from datetime import date, timedelta
import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from app.hash_chain import (
    calculate_event_hash,
    canonical_json,
    record_event,
    verify_batch_chain,
)
from app.models import (
    EVENT_HANDOVER_ACCEPT,
    EVENT_HANDOVER_INIT,
    EVENT_HANDOVER_REJECT,
    EVENT_HARVEST,
    HANDOVER_ACCEPTED,
    HANDOVER_PENDING,
    HANDOVER_REJECTED,
    ROLE_FARMER,
    Batch,
    BatchEvent,
    Handover,
    Organization,
    Plot,
    Product,
    User,
)
from app.security import hash_password
from app.utils.batch_code import FORBIDDEN_CHARS, generate_batch_code
from tests.conftest import TEST_PASSWORD, TEST_USERNAME_ADMIN, TEST_USERNAME_FARMER


# ==============================================================================
# HELPER SETUP FIXTURES
# ==============================================================================

@pytest.fixture()
def setup_sprint2_env(session_factory: sessionmaker[Session]) -> dict[str, int]:
    """Khởi tạo môi trường đa tổ chức với HTX Đồng Tháp và HTX Tiền Giang."""
    with session_factory() as session:
        # Tổ chức 1: Đồng Tháp (đã có từ conftest org_id=1)
        org1 = session.get(Organization, 1)
        if not org1:
            org1 = Organization(id=1, name="HTX Đồng Tháp", code="HTX-DT")
            session.add(org1)
            session.flush()

        # Tổ chức 2: Tiền Giang
        org2 = Organization(
            id=2,
            name="HTX Trái Cây Tiền Giang",
            code="HTX-TG",
            description="Tổ chức đối tác Tiền Giang",
        )
        session.add(org2)
        session.flush()

        # Thêm nông dân Tiền Giang
        farmer_tg = User(
            username="farmer_tg",
            password=hash_password(TEST_PASSWORD),
            role=ROLE_FARMER,
            organization_id=org2.id,
        )
        session.add(farmer_tg)

        # Sản phẩm dùng chung
        prod = Product(
            name="Xoài Cát Chu Cao Lãnh",
            unit="kg",
        )
        session.add(prod)
        session.flush()

        # Thửa đất 1 thuộc Đồng Tháp
        plot1 = Plot(
            name="Thửa 1 - Vườn Xoài Cát Chu",
            location="Xã Mỹ Xương, Cao Lãnh, Đồng Tháp",
            area=2.0,
            owner="HTX Đồng Tháp",
            organization_id=org1.id,
        )
        session.add(plot1)

        # Thửa đất 2 thuộc Tiền Giang
        plot2 = Plot(
            name="Thửa 2 - Vườn Sầu Riêng Ngũ Hiệp",
            location="Cai Lậy, Tiền Giang",
            area=3.5,
            owner="HTX Tiền Giang",
            organization_id=org2.id,
        )
        session.add(plot2)
        session.commit()

        return {
            "org1_id": org1.id,
            "org2_id": org2.id,
            "product_id": prod.id,
            "plot1_id": plot1.id,
            "plot2_id": plot2.id,
        }


# ==============================================================================
# TEST 1: SINH 10,000 MÃ LÔ DUY NHẤT & KHÔNG KÝ TỰ CẤM (T-19)
# ==============================================================================
def test_batch_code_generator_10000_unique() -> None:
    """T-19: Vòng lặp sinh 10,000 mã không trùng, không chứa 0, O, 1, I, L."""
    total_samples = 10000
    generated_codes = set()

    for _ in range(total_samples):
        code = generate_batch_code()
        # 1. Độ dài đúng 8 ký tự
        assert len(code) == 8, f"Mã {code} không đủ 8 ký tự"

        # 2. Không chứa bất kỳ ký tự cấm nào (0, O, 1, I, L)
        assert not any(char in code for char in FORBIDDEN_CHARS), (
            f"Mã {code} chứa ký tự cấm trong {FORBIDDEN_CHARS}"
        )

        # 3. Tất cả ký tự nằm trong bảng chữ cái cho phép
        assert code.isupper() or code.isdigit()

        generated_codes.add(code)

    # 4. Toàn bộ 10,000 mã đều độc nhất (không trùng lặp)
    assert len(generated_codes) == total_samples, "Phát hiện mã bị trùng lặp trong 10,000 mẫu"


# ==============================================================================
# TEST 2: ĐỒNG NHẤT MÃ BĂM VỚI CANONICAL JSON (T-24)
# ==============================================================================
def test_hash_consistency_canonical_json() -> None:
    """T-24: Băm 2 dictionary cùng dữ liệu nhưng đảo thứ tự key -> khẳng định ra cùng hash SHA-256."""
    dict_a = {
        "batch_id": 42,
        "quantity": 1250.5,
        "harvest_date": "2026-04-10",
        "product_info": {
            "name": "Xoài Cát Chu",
            "unit": "kg",
            "certifications": ["VietGAP", "GlobalGAP"],
        },
        "location": "Đồng Tháp",
    }

    # dict_b chứa đúng dữ liệu nhưng các key bị xáo trộn ở cả tầng gốc lẫn tầng lồng nhau
    dict_b = {
        "location": "Đồng Tháp",
        "product_info": {
            "certifications": ["VietGAP", "GlobalGAP"],
            "unit": "kg",
            "name": "Xoài Cát Chu",
        },
        "harvest_date": "2026-04-10",
        "quantity": 1250.5,
        "batch_id": 42,
    }

    # 1. Canonical JSON chuỗi hóa phải giống nhau tuyệt đối
    str_a = canonical_json(dict_a)
    str_b = canonical_json(dict_b)
    assert str_a == str_b

    # 2. Không có khoảng trắng thừa sau dấu phẩy hoặc hai chấm
    assert ": " not in str_a
    assert ", " not in str_a

    # 3. Cùng prev_hash + 2 dict khác thứ tự key -> Cho ra cùng mã băm SHA-256
    prev_hash = "0" * 64
    hash_a = calculate_event_hash(prev_hash, dict_a)
    hash_b = calculate_event_hash(prev_hash, dict_b)

    assert hash_a == hash_b
    assert len(hash_a) == 64
    assert all(c in "0123456789abcdef" for c in hash_a)


# ==============================================================================
# TEST 3: SERVER-SIDE VALIDATION CHO ENDPOINT POST /batches (T-21)
# ==============================================================================
def test_harvest_validation_server_side(client: TestClient, setup_sprint2_env: dict[str, int]) -> None:
    """T-21: Kiểm tra các ca thất bại (ngày tương lai, khối lượng <= 0, chọn thửa của org khác 403) và ca hợp lệ."""
    env = setup_sprint2_env
    farmer_auth = (TEST_USERNAME_FARMER, TEST_PASSWORD)

    # Ca thất bại 1: Ngày thu hoạch ở tương lai
    future_date = (date.today() + timedelta(days=2)).isoformat()
    resp_future = client.post(
        "/batches",
        json={
            "plot_id": env["plot1_id"],
            "product_id": env["product_id"],
            "harvest_date": future_date,
            "initial_quantity": 500.0,
        },
        auth=farmer_auth,
    )
    assert resp_future.status_code == 400
    detail = resp_future.json().get("detail", {})
    detail_str = json.dumps(detail, ensure_ascii=False)
    assert "tương lai" in detail_str.lower()

    # Ca thất bại 2: Khối lượng thu hoạch <= 0
    resp_zero_qty = client.post(
        "/batches",
        json={
            "plot_id": env["plot1_id"],
            "product_id": env["product_id"],
            "harvest_date": date.today().isoformat(),
            "initial_quantity": 0.0,
        },
        auth=farmer_auth,
    )
    assert resp_zero_qty.status_code in (400, 422)

    resp_neg_qty = client.post(
        "/batches",
        json={
            "plot_id": env["plot1_id"],
            "product_id": env["product_id"],
            "harvest_date": date.today().isoformat(),
            "initial_quantity": -150.0,
        },
        auth=farmer_auth,
    )
    assert resp_neg_qty.status_code in (400, 422)

    # Ca thất bại 3: Chọn thửa đất của tổ chức khác (Đồng Tháp cố chọn thửa Tiền Giang) -> 403 Forbidden
    resp_cross_org = client.post(
        "/batches",
        json={
            "plot_id": env["plot2_id"],  # Thửa 2 thuộc org2
            "product_id": env["product_id"],
            "harvest_date": date.today().isoformat(),
            "initial_quantity": 300.0,
        },
        auth=farmer_auth,  # Farmer org1
    )
    assert resp_cross_org.status_code == 403
    assert "tổ chức khác" in resp_cross_org.json()["detail"].lower()

    # Ca thành công: Dữ liệu hợp lệ
    today_str = date.today().isoformat()
    resp_valid = client.post(
        "/batches",
        json={
            "plot_id": env["plot1_id"],
            "product_id": env["product_id"],
            "harvest_date": today_str,
            "initial_quantity": 850.5,
        },
        auth=farmer_auth,
    )
    assert resp_valid.status_code == 201
    batch_data = resp_valid.json()
    assert batch_data["code"] is not None
    assert len(batch_data["code"]) == 8
    assert not any(c in batch_data["code"] for c in FORBIDDEN_CHARS)
    assert batch_data["initial_quantity"] == 850.5
    assert batch_data["remaining_quantity"] == 850.5
    assert batch_data["status"] == "ACTIVE"
    assert batch_data["current_org_id"] == env["org1_id"]


# ==============================================================================
# TEST 4: TRANSACTION NGUYÊN TỬ VÀ ROLLBACK TOÀN DIỆN (T-25)
# ==============================================================================
def test_atomic_harvest_rollback(
    client: TestClient,
    setup_sprint2_env: dict[str, int],
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-25: Cố ý làm gián đoạn transaction sau khi tạo lô -> kiểm tra cả batches lẫn batch_events đều không lưu bản ghi nào."""
    env = setup_sprint2_env
    farmer_auth = (TEST_USERNAME_FARMER, TEST_PASSWORD)

    # Đếm số lượng ban đầu trong database
    with session_factory() as session:
        initial_batches_count = len(list(session.scalars(select(Batch)).all()))
        initial_events_count = len(list(session.scalars(select(BatchEvent)).all()))

    # Giả lập lỗi runtime trong hàm record_event khi đang xử lý POST /batches
    from app.routers import batches as batches_router

    def mock_broken_record_event(*args, **kwargs):
        raise RuntimeError("CỐ Ý GIẢ LẬP LỖI HỆ THỐNG TRONG KHI GHI HASH-CHAIN EVENT")

    monkeypatch.setattr(batches_router, "record_event", mock_broken_record_event)

    # Gửi request tạo lô thu hoạch
    resp = client.post(
        "/batches",
        json={
            "plot_id": env["plot1_id"],
            "product_id": env["product_id"],
            "harvest_date": date.today().isoformat(),
            "initial_quantity": 999.0,
        },
        auth=farmer_auth,
    )
    # Phải trả về lỗi 500 do transaction gặp sự cố
    assert resp.status_code == 500

    # Khẳng định tính nguyên tử (Atomicity): Cả 2 bảng đều không có bản ghi rác lưu lại
    with session_factory() as session:
        current_batches_count = len(list(session.scalars(select(Batch)).all()))
        current_events_count = len(list(session.scalars(select(BatchEvent)).all()))

        assert current_batches_count == initial_batches_count, "Bảng batches bị lưu bản ghi rác khi transaction lỗi"
        assert current_events_count == initial_events_count, "Bảng batch_events bị lưu bản ghi rác khi transaction lỗi"


# ==============================================================================
# TEST 5: PHÁT HIỆN GIAN LẬN TOÀN VẸN CHUỖI 3 TRƯỜNG HỢP (T-28, T-30)
# ==============================================================================
def test_tamper_detection_three_cases(
    session_factory: sessionmaker[Session],
    setup_sprint2_env: dict[str, int],
) -> None:
    """T-30: Kiểm tra 3 ca phát hiện giả mạo chuỗi sự kiện hash-chain:
    - Ca 1: Chuỗi nguyên vẹn 10 sự kiện -> verify_batch_chain trả về is_valid: True.
    - Ca 2: Dùng SQL trực tiếp sửa lén 1 trường trong JSON payload sự kiện số 5 -> phát hiện is_valid: False, chỉ đúng ID sự kiện số 5.
    - Ca 3: Dùng SQL trực tiếp xóa sự kiện số 4 -> phát hiện đứt mạch tại đúng vị trí đó.
    """
    env = setup_sprint2_env
    org_id = env["org1_id"]
    user_id = 1

    # Tạo lô nông sản thử nghiệm
    with session_factory() as session:
        test_batch = Batch(
            code="SPRINT02",
            plot_id=env["plot1_id"],
            product_id=env["product_id"],
            harvest_date=date.today(),
            initial_quantity=1000.0,
            remaining_quantity=1000.0,
            current_org_id=org_id,
            status="ACTIVE",
        )
        session.add(test_batch)
        session.commit()
        batch_id = test_batch.id

        # Tạo chuỗi tuần tự gồm 10 sự kiện hợp lệ
        event_types = [
            "HARVEST",
            "WATERING",
            "FERTILIZING",
            "PRUNING",
            "PEST_CONTROL",
            "INSPECTION",
            "PACKING",
            "COLD_STORAGE",
            "TRANSPORT_DEPART",
            "DELIVERY_RECEIVE",
        ]
        created_events: list[BatchEvent] = []
        for idx, et in enumerate(event_types, start=1):
            evt = record_event(
                db=session,
                batch_id=batch_id,
                event_type=et,
                payload={
                    "step": idx,
                    "event_type": et,
                    "description": f"Hoàn thành công đoạn số {idx}: {et}",
                    "temperature": 12.5 if "COLD" in et else None,
                },
                org_id=org_id,
                user_id=user_id,
            )
            created_events.append(evt)
        session.commit()

        # ----------------------------------------------------------------------
        # Ca 1: Chuỗi nguyên vẹn 10 sự kiện -> is_valid == True
        # ----------------------------------------------------------------------
        res_valid = verify_batch_chain(session, batch_id)
        assert res_valid["is_valid"] is True
        assert res_valid["total_events"] == 10

        # Lưu lại ID của sự kiện số 5 (index 4)
        event5_id = created_events[4].id

        # ----------------------------------------------------------------------
        # Ca 2: Dùng SQL sửa lén payload của sự kiện số 5 (vượt qua ORM listener)
        # ----------------------------------------------------------------------
        session.execute(text("DROP TRIGGER IF EXISTS prevent_batch_events_update"))
        tampered_payload = json.dumps(
            {
                "step": 5,
                "event_type": "PEST_CONTROL",
                "description": "DỮ LIỆU ĐÃ BỊ HACK SỬA LÉN QUA SQL TRỰC TIẾP",
                "temperature": None,
            }
        )
        session.execute(
            text("UPDATE batch_events SET payload = :p WHERE id = :id"),
            {"p": tampered_payload, "id": event5_id},
        )
        session.commit()

        # Dựng lại trigger sau thử nghiệm
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

        # Kiểm tra tính toàn vẹn -> Phải phát hiện đúng ID sự kiện số 5
        res_tamper = verify_batch_chain(session, batch_id)
        assert res_tamper["is_valid"] is False
        assert res_tamper["tampered_event_id"] == event5_id
        assert res_tamper["error_type"] == "HASH_MISMATCH"

    # --------------------------------------------------------------------------
    # Ca 3: Chuỗi đứt mạch khi xóa sự kiện số 4 (trên một lô mới độc lập)
    # --------------------------------------------------------------------------
    with session_factory() as session:
        batch2 = Batch(
            code="CHAINBRK",
            plot_id=env["plot1_id"],
            product_id=env["product_id"],
            harvest_date=date.today(),
            initial_quantity=500.0,
            remaining_quantity=500.0,
            current_org_id=org_id,
            status="ACTIVE",
        )
        session.add(batch2)
        session.commit()

        events_batch2 = []
        for i in range(1, 11):
            e = record_event(
                db=session,
                batch_id=batch2.id,
                event_type=f"STEP_{i}",
                payload={"index": i, "note": f"Sự kiện thứ {i}"},
                org_id=org_id,
                user_id=user_id,
            )
            events_batch2.append(e)
        session.commit()

        event4_id = events_batch2[3].id
        event5_batch2_id = events_batch2[4].id

        # Dùng SQL xóa sự kiện số 4 (tạm thả trigger)
        session.execute(text("DROP TRIGGER IF EXISTS prevent_batch_events_delete"))
        session.execute(text("DELETE FROM batch_events WHERE id = :id"), {"id": event4_id})
        session.commit()

        # Dựng lại trigger delete
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

        # Kiểm tra: Phát hiện đứt mạch tại sự kiện số 5 (do prev_hash trỏ về event 4 đã mất)
        res_broken = verify_batch_chain(session, batch2.id)
        assert res_broken["is_valid"] is False
        assert res_broken["tampered_event_id"] == event5_batch2_id
        assert res_broken["error_type"] == "CHAIN_BROKEN"


# ==============================================================================
# TEST 6: TOÀN BỘ VÒNG ĐỜI BÀN GIAO & TÍNH BẤT BIẾN CHUỖI (T-36, T-37, T-38)
# ==============================================================================
def test_handover_flow_full_lifecycle(
    client: TestClient,
    setup_sprint2_env: dict[str, int],
    session_factory: sessionmaker[Session],
) -> None:
    """T-37, T-38: Luồng bàn giao đầy đủ:
    1. Tạo yêu cầu bàn giao -> ghi HANDOVER_INIT, chủ lô chưa đổi.
    2. Bên nhận thấy trong tab pending.
    3. Bên nhận accept -> đổi batches.current_org_id, ghi HANDOVER_ACCEPT, chuỗi băm nguyên vẹn.
    4. Từ chối thiếu lý do (< 10 ký tự) bị chặn; từ chối hợp lệ giữ nguyên chủ.
    """
    env = setup_sprint2_env
    farmer1_auth = (TEST_USERNAME_FARMER, TEST_PASSWORD)
    farmer2_auth = ("farmer_tg", TEST_PASSWORD)

    # 1. Tạo lô ban đầu thuộc Org 1 (Đồng Tháp)
    create_batch_resp = client.post(
        "/batches",
        json={
            "plot_id": env["plot1_id"],
            "product_id": env["product_id"],
            "harvest_date": date.today().isoformat(),
            "initial_quantity": 600.0,
        },
        auth=farmer1_auth,
    )
    assert create_batch_resp.status_code == 201
    batch_id = create_batch_resp.json()["id"]

    # 2. Farmer 1 gửi bàn giao sang Org 2 (Tiền Giang) (T-36)
    handover_resp = client.post(
        f"/batches/{batch_id}/handover",
        json={
            "to_org_id": env["org2_id"],
            "note": "Bàn giao 600kg xoài sang kho lạnh Tiền Giang",
        },
        auth=farmer1_auth,
    )
    assert handover_resp.status_code == 201
    handover_data = handover_resp.json()
    handover_id = handover_data["id"]
    assert handover_data["status"] == HANDOVER_PENDING

    # Kiểm tra chủ lô hiện tại vẫn là Org 1 (chưa đổi)
    with session_factory() as session:
        batch_db = session.get(Batch, batch_id)
        assert batch_db is not None
        assert batch_db.current_org_id == env["org1_id"]

    # 3. Farmer 2 kiểm tra danh sách chờ xác nhận (T-38)
    pending_resp = client.get("/handovers/pending", auth=farmer2_auth)
    assert pending_resp.status_code == 200
    pending_ids = [h["id"] for h in pending_resp.json()]
    assert handover_id in pending_ids

    # 4. Người ngoài (Org khác hoặc người gửi) không được quyền Accept
    resp_unauth_accept = client.post(f"/handovers/{handover_id}/accept", auth=farmer1_auth)
    assert resp_unauth_accept.status_code == 403

    # 5. Farmer 2 tiếp nhận bàn giao thành công (T-37)
    accept_resp = client.post(f"/handovers/{handover_id}/accept", auth=farmer2_auth)
    assert accept_resp.status_code == 200
    assert accept_resp.json()["status"] == HANDOVER_ACCEPTED

    # Kiểm tra database: batch.current_org_id đã chuyển sang Org 2 (Tiền Giang)
    with session_factory() as session:
        batch_after = session.get(Batch, batch_id)
        assert batch_after is not None
        assert batch_after.current_org_id == env["org2_id"]

        # Kiểm tra toàn vẹn chuỗi: HARVEST -> HANDOVER_INIT -> HANDOVER_ACCEPT
        integrity = verify_batch_chain(session, batch_id)
        assert integrity["is_valid"] is True
        assert integrity["total_events"] == 3

    # --------------------------------------------------------------------------
    # 6. Kiểm tra luồng từ chối (REJECT) và kiểm tra lý do tối thiểu 10 ký tự (T-38)
    # --------------------------------------------------------------------------
    # Tạo yêu cầu bàn giao mới từ Org 2 về Org 1
    handover_back_resp = client.post(
        f"/batches/{batch_id}/handover",
        json={
            "to_org_id": env["org1_id"],
            "note": "Chuyển trả lô về Đồng Tháp để kiểm tra chất lượng",
        },
        auth=farmer2_auth,
    )
    assert handover_back_resp.status_code == 201
    handover_back_id = handover_back_resp.json()["id"]

    # Thử từ chối với lý do quá ngắn (< 10 ký tự) -> Phải bị chặn
    reject_short = client.post(
        f"/handovers/{handover_back_id}/reject",
        json={"reject_reason": "Lỗi hàng"},
        auth=farmer1_auth,
    )
    assert reject_short.status_code in (400, 422)

    # Từ chối với lý do hợp lệ (>= 10 ký tự)
    valid_reason = "Hàng bị trầy xước vỏ và không đạt tiêu chuẩn độ chín yêu cầu"
    reject_valid = client.post(
        f"/handovers/{handover_back_id}/reject",
        json={"reject_reason": valid_reason},
        auth=farmer1_auth,
    )
    assert reject_valid.status_code == 200
    assert reject_valid.json()["status"] == HANDOVER_REJECTED

    # Khẳng định: Sau khi từ chối, lô hàng vẫn thuộc quyền Org 2 (giữ nguyên chủ)
    with session_factory() as session:
        batch_final = session.get(Batch, batch_id)
        assert batch_final is not None
        assert batch_final.current_org_id == env["org2_id"]

        # Toàn bộ chuỗi sự kiện vẫn hoàn toàn nguyên vẹn
        chain_status = verify_batch_chain(session, batch_id)
        assert chain_status["is_valid"] is True
        assert chain_status["total_events"] == 5


# ==============================================================================
# TEST 7: QUẢN LÝ DANH MỤC SẢN PHẨM & PHÂN QUYỀN ADMIN (T-16, T-17)
# ==============================================================================
def test_products_catalog_and_admin_permission(client: TestClient) -> None:
    """T-17: GET /products cho mọi người, POST /products chỉ Admin (Farmer bị 403, trùng tên bị 400)."""
    admin_auth = (TEST_USERNAME_ADMIN, TEST_PASSWORD)
    farmer_auth = (TEST_USERNAME_FARMER, TEST_PASSWORD)

    # 1. Farmer có thể xem danh mục sản phẩm dùng chung
    res_get = client.get("/products", auth=farmer_auth)
    assert res_get.status_code == 200
    assert isinstance(res_get.json(), list)

    # 2. Farmer cố gắng tạo sản phẩm -> 403 Forbidden
    res_farmer_post = client.post(
        "/products",
        json={"name": "Sầu riêng Ri6", "unit": "kg"},
        auth=farmer_auth,
    )
    assert res_farmer_post.status_code == 403

    # 3. Admin tạo sản phẩm thành công -> 201 Created
    res_admin_post = client.post(
        "/products",
        json={"name": "Sầu riêng Ri6", "unit": "kg"},
        auth=admin_auth,
    )
    assert res_admin_post.status_code == 201
    data = res_admin_post.json()
    assert data["name"] == "Sầu riêng Ri6"
    assert data["unit"] == "kg"

    # 4. Kiểm tra trùng tên sản phẩm -> 400 Bad Request
    res_duplicate = client.post(
        "/products",
        json={"name": "Sầu riêng Ri6", "unit": "tấn"},
        auth=admin_auth,
    )
    assert res_duplicate.status_code == 400
    assert "đã tồn tại" in res_duplicate.json()["detail"].lower()
