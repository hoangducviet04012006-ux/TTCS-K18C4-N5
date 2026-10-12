"""Tests for S-33: Đánh dấu lô có sự cố và mở lệnh thu hồi kèm lý do.

Covers all 5 acceptance test cases:
1. Chọn lô hợp lệ, nhập lý do và tạo lệnh thu hồi thành công.
2. Không nhập lý do thu hồi thì hệ thống yêu cầu bổ sung (HTTP 422).
3. Nhập mã lô không tồn tại thì hệ thống thông báo lỗi (HTTP 404).
4. Lô đã có lệnh thu hồi đang xử lý thì không cho tạo lệnh trùng (HTTP 409).
5. Nếu lưu dữ liệu thất bại, hệ thống thông báo lỗi và rollback bảo toàn tính nhất quán.
"""
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.database import Base, create_event_immutability_triggers
from app.hash_chain import verify_batch_chain
from app.main import app
from app.models import AuditLog, Batch, BatchEvent, Organization, User
from app.recall_models import Recall
from app.security import hash_password
from scripts.seed_recall_s39 import seed_recall_s39

PASSWORD = "S33TestPassword123!"
HASHED_PASSWORD = hash_password(PASSWORD)
VALID_REASON = "Phát hiện dư lượng thuốc BVTV vượt ngưỡng cho phép trong mẫu kiểm tra định kỳ."


@pytest.fixture
def engine(tmp_path):
    """Seed memory and backup to a fresh test file with foreign keys and triggers."""
    memory = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(memory)
    with Session(memory) as db:
        seed_recall_s39(db)
        orgs = {org.code: org.id for org in db.scalars(select(Organization)).all()}
        roles = [
            ("inspector", "inspector", None),
            ("farm_admin", "org_admin", orgs["ORG-FARM"]),
            ("proc_admin", "org_admin", orgs["ORG-PROC"]),
            ("dist_admin", "org_admin", orgs["ORG-DIST"]),
            ("farmer", "farmer", orgs["ORG-FARM"]),
        ]
        db.add_all([
            User(
                username=name,
                email=name + "@s33.invalid",
                password=HASHED_PASSWORD,
                role=role,
                organization_id=org,
            )
            for name, role, org in roles
        ])
        db.commit()

    path = tmp_path / "s33_recall_test.db"
    raw = memory.raw_connection()
    with sqlite3.connect(path) as disk:
        raw.driver_connection.backup(disk)
    raw.close()
    memory.dispose()

    engine = create_engine(
        "sqlite:///" + path.as_posix(),
        connect_args={"check_same_thread": False, "timeout": 10},
    )

    @event.listens_for(engine, "connect")
    def enable_fk(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    create_event_immutability_triggers(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def ids(session_factory):
    with session_factory() as db:
        return {batch.code: batch.id for batch in db.scalars(select(Batch)).all()}


@pytest.fixture
def users():
    return []


# ==============================================================================
# TRƯỜNG HỢP KIỂM THỬ 1: Chọn lô hợp lệ, nhập lý do và tạo lệnh thu hồi thành công
# ==============================================================================
def test_case_1_valid_batch_and_reason_creates_recall_successfully(client, ids, session_factory):
    """TC1: Cho phép người dùng tìm kiếm/chọn lô hợp lệ, nhập lý do (>= 20 ký tự)

    và tạo lệnh thu hồi thành công với mã riêng, trạng thái OPEN, ghi sự kiện
    và audit log phục vụ truy vết.
    """
    root_code = "S39-ROOT-A"
    root_id = ids[root_code]

    # Kiểm tra tạo lệnh qua batch_code
    response = client.post(
        "/recalls",
        json={"batch_code": root_code, "reason": VALID_REASON},
        auth=("inspector", PASSWORD),
        headers={"Idempotency-Key": "tc1-by-code"},
    )
    assert response.status_code == 201, response.text
    data = response.json()

    # Kiểm tra các thông tin bắt buộc của lệnh thu hồi (S-33)
    assert data["id"] > 0
    assert data["recall_code"].startswith("REC-")
    assert data["root_batch_id"] == root_id
    assert data["batch_code"] == root_code
    assert data["reason"] == VALID_REASON
    assert data["status"] == "OPEN"
    assert data["incident_status"] == "Có sự cố"
    assert data["created_at"] is not None
    assert data["created_by_user_id"] is not None
    assert data["quarantined"] is True

    # Kiểm tra ghi nhận vào cơ sở dữ liệu và truy vết
    with session_factory() as db:
        # 1. Bản ghi Recall trong DB
        db_recall = db.get(Recall, data["id"])
        assert db_recall is not None
        assert db_recall.root_batch_id == root_id
        assert db_recall.status == "OPEN"
        assert db_recall.reason == VALID_REASON

        # 2. Sự kiện RECALL_INIT được ghi vào hash chain của lô
        events = db.scalars(
            select(BatchEvent)
            .where(BatchEvent.batch_id == root_id, BatchEvent.event_type == "RECALL_INIT")
        ).all()
        assert len(events) == 1
        init_event = events[0]
        assert init_event.payload["recall_id"] == data["id"]
        assert init_event.payload["recall_code"] == data["recall_code"]
        assert init_event.payload["reason"] == VALID_REASON

        # Chuỗi băm vẫn toàn vẹn
        chain_verification = verify_batch_chain(db, root_id)
        assert chain_verification["is_valid"] is True

        # 3. Ghi nhận AuditLog phục vụ truy vết người thực hiện
        audit = db.scalar(
            select(AuditLog).where(AuditLog.entity == "recall", AuditLog.entity_id == data["id"])
        )
        assert audit is not None
        assert audit.action == "CREATE"


# ==============================================================================
# TRƯỜNG HỢP KIỂM THỬ 2: Không nhập lý do thu hồi thì hệ thống yêu cầu bổ sung
# ==============================================================================
def test_case_2_missing_or_short_reason_requires_supplement(client, ids, session_factory):
    """TC2: Bắt buộc nhập lý do thu hồi (>= 20 ký tự).

    Nếu không nhập, để trống hoặc nhập quá ngắn thì hệ thống từ chối (422)
    và yêu cầu bổ sung.
    """
    root_id = ids["S39-ROOT-A"]

    invalid_reasons = [
        "",                     # Rỗng
        "   ",                  # Toàn khoảng trắng
        "Hàng hỏng",            # Quá ngắn (< 20 ký tự)
        "1234567890123456789",  # 19 ký tự
    ]

    for idx, bad_reason in enumerate(invalid_reasons):
        res = client.post(
            "/recalls",
            json={"root_batch_id": root_id, "reason": bad_reason},
            auth=("inspector", PASSWORD),
            headers={"Idempotency-Key": f"tc2-bad-reason-{idx}"},
        )
        assert res.status_code == 422, f"Failed for reason: {bad_reason!r}"

    # Kiểm tra không gửi trường reason
    res_missing = client.post(
        "/recalls",
        json={"root_batch_id": root_id},
        auth=("inspector", PASSWORD),
        headers={"Idempotency-Key": "tc2-missing-reason"},
    )
    assert res_missing.status_code == 422

    # Cơ sở dữ liệu hoàn toàn không có lệnh recall nào được tạo
    with session_factory() as db:
        assert db.scalar(select(Recall).where(Recall.root_batch_id == root_id)) is None


# ==============================================================================
# TRƯỜNG HỢP KIỂM THỬ 3: Nhập mã lô không tồn tại thì hệ thống thông báo lỗi
# ==============================================================================
def test_case_3_non_existent_batch_returns_error(client, session_factory):
    """TC3: Nhập mã lô không tồn tại (hoặc ID không tồn tại) thì hệ thống báo lỗi 404."""
    # 1. Nhập mã lô dạng chuỗi không tồn tại
    res_code = client.post(
        "/recalls",
        json={"batch_code": "BATCH-NONEXISTENT-999", "reason": VALID_REASON},
        auth=("inspector", PASSWORD),
        headers={"Idempotency-Key": "tc3-code-404"},
    )
    assert res_code.status_code == 404
    assert "Mã lô không tồn tại" in res_code.text

    # 2. Nhập ID lô không tồn tại
    res_id = client.post(
        "/recalls",
        json={"root_batch_id": 999999, "reason": VALID_REASON},
        auth=("inspector", PASSWORD),
        headers={"Idempotency-Key": "tc3-id-404"},
    )
    assert res_id.status_code == 404
    assert "Batch not found" in res_id.text


# ==============================================================================
# TRƯỜNG HỢP KIỂM THỬ 4: Lô đã có lệnh thu hồi đang xử lý thì không cho tạo trùng
# ==============================================================================
def test_case_4_duplicate_recall_on_same_batch_rejected(client, ids, session_factory):
    """TC4: Kiểm tra mã lô và không cho tạo lệnh thu hồi trùng lặp cho cùng một lô

    khi lệnh trước đó vẫn đang được xử lý (trạng thái OPEN).
    Trả về mã 409 Conflict kèm recall_code của lệnh đang mở.
    """
    root_id = ids["S39-ROOT-A"]

    # Tạo lệnh thứ nhất thành công
    res1 = client.post(
        "/recalls",
        json={"root_batch_id": root_id, "reason": VALID_REASON},
        auth=("inspector", PASSWORD),
        headers={"Idempotency-Key": "tc4-first-command"},
    )
    assert res1.status_code == 201
    first_code = res1.json()["recall_code"]

    # Cố gắng tạo lệnh thứ hai cho cùng một lô khi lệnh 1 đang OPEN
    res2 = client.post(
        "/recalls",
        json={"root_batch_id": root_id, "reason": VALID_REASON + " Lần tạo thứ hai thử nghiệm."},
        auth=("inspector", PASSWORD),
        headers={"Idempotency-Key": "tc4-second-command"},
    )
    assert res2.status_code == 409
    error_data = res2.json()
    assert error_data["detail"]["code"] == "ROOT_ALREADY_RECALLED"
    assert error_data["detail"]["recall_code"] == first_code

    # Thử lại với batch_code thay vì root_batch_id
    res3 = client.post(
        "/recalls",
        json={"batch_code": "S39-ROOT-A", "reason": VALID_REASON + " Lần tạo thứ ba bằng mã lô."},
        auth=("inspector", PASSWORD),
        headers={"Idempotency-Key": "tc4-third-command"},
    )
    assert res3.status_code == 409
    assert res3.json()["detail"]["recall_code"] == first_code

    # Xác nhận DB chỉ có duy nhất 1 lệnh recall cho lô này
    with session_factory() as db:
        recalls = db.scalars(select(Recall).where(Recall.root_batch_id == root_id)).all()
        assert len(recalls) == 1


# ==============================================================================
# TRƯỜNG HỢP KIỂM THỬ 5: Nếu lưu dữ liệu thất bại, hệ thống thông báo lỗi và rollback
# ==============================================================================
def test_case_5_save_failure_rolls_back_consistently(client, ids, session_factory):
    """TC5: Nếu lưu dữ liệu thất bại trong quá trình thực hiện transaction,

    hệ thống thông báo lỗi và rollback toàn bộ, không để lại dữ liệu rác hay
    trạng thái không nhất quán.
    """
    root_id = ids["S39-ROOT-A"]

    # Đếm số lượng ban đầu trước khi gọi
    with session_factory() as db:
        initial_recall_count = len(db.scalars(select(Recall)).all())
        initial_event_count = len(db.scalars(select(BatchEvent)).all())
        initial_audit_count = len(db.scalars(select(AuditLog)).all())

    # Giả lập lỗi ở bước ghi sự kiện hash chain
    with patch("app.services.recall.event", side_effect=RuntimeError("Simulated DB Disk Full or Failure")):
        with pytest.raises(RuntimeError):
            client.post(
                "/recalls",
                json={"root_batch_id": root_id, "reason": VALID_REASON},
                auth=("inspector", PASSWORD),
                headers={"Idempotency-Key": "tc5-failing-save"},
            )

    # Kiểm tra tính toàn vẹn và nhất quán sau lỗi: Toàn bộ đã rollback
    with session_factory() as db:
        current_recall_count = len(db.scalars(select(Recall)).all())
        current_event_count = len(db.scalars(select(BatchEvent)).all())
        current_audit_count = len(db.scalars(select(AuditLog)).all())

        assert current_recall_count == initial_recall_count, "Không được tạo Recall khi gặp lỗi"
        assert current_event_count == initial_event_count, "Không được tạo sự kiện nửa chừng"
        assert current_audit_count == initial_audit_count, "Không được ghi audit log khi rollback"

        # Chuỗi băm của lô vẫn hoàn toàn nguyên vẹn
        assert verify_batch_chain(db, root_id)["is_valid"] is True
