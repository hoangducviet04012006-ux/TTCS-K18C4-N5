"""Ghi & đọc lịch sử thao tác (audit log) - Sprint 7.

Module này là **điểm duy nhất** biết cách ghi/đọc bảng ``audit_logs``, nhờ vậy
router nghiệp vụ chỉ cần gọi một hàm ngắn gọn:

- ``record_action(...)``: thêm 1 dòng log vào **session đang mở** của thao tác
  (không tự commit) -> log và dữ liệu nghiệp vụ được commit trong *cùng một
  transaction*. Hệ quả: thao tác thành công thì chắc chắn có log, thao tác thất
  bại (404/403/500) thì **không** để lại log rác.
- ``fetch_audit_logs(...)``: đọc log cho API ``GET /audit-logs`` (chỉ admin),
  sắp xếp **mới nhất trước** kèm bộ lọc ``entity`` / ``user_id`` / ``limit``.

Ví dụ dùng trong router::

    from app.audit import record_action
    from app.models import ACTION_CREATE, ENTITY_FARM

    db.add(farm)
    db.flush()  # cần `id` trước khi ghi log
    record_action(db, current_user, ACTION_CREATE, ENTITY_FARM, farm.id)
    db.commit()
"""

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import AuditLog, User

#: Số dòng log trả về mặc định cho một lần gọi ``GET /audit-logs``.
DEFAULT_AUDIT_LOG_LIMIT: int = 100

#: Số dòng log tối đa client được yêu cầu (chặn ``?limit=100000``).
MAX_AUDIT_LOG_LIMIT: int = 500


def calculate_hash(prev_hash: str, payload: dict) -> str:
    """Tính mã băm (SHA-256) với chuẩn hóa nội dung JSON."""
    canonical_json = json.dumps(payload, separators=(',', ':'), sort_keys=True)
    return hashlib.sha256(f"{prev_hash}{canonical_json}".encode("utf-8")).hexdigest()


def record_action(
    db: Session,
    user: User,
    action: str,
    entity: str,
    entity_id: int,
) -> AuditLog:
    """Thêm 1 bản ghi lịch sử vào session hiện tại (**chưa** commit).

    Hàm được gọi ngay trước ``db.commit()`` của thao tác nghiệp vụ, nên nếu
    thao tác thất bại (rollback) thì dòng log cũng bị huỷ theo - nhờ vậy lịch
    sử chỉ chứa những thao tác **thực sự đã xảy ra**.

    Args:
        db: Session SQLAlchemy của request (dependency ``get_db``).
        user: Tài khoản đã thực hiện thao tác (lấy ``id`` ghi vào cột ``user_id``).
        action: Hành động - dùng hằng số ``ACTION_CREATE`` / ``ACTION_UPDATE`` /
            ``ACTION_DELETE`` trong ``app/models.py``.
        entity: Loại dữ liệu bị tác động - ``ENTITY_FARM`` hoặc ``ENTITY_BATCH``.
        entity_id: ID bản ghi bị tác động (phải là ID **thật** của bản ghi; với
            thao tác tạo mới, gọi ``db.flush()`` trước để có ``id``).

    Returns:
        AuditLog: Đối tượng vừa được ``db.add()`` (``id``/``created_at`` chỉ có
        giá trị sau khi commit).
    """
    last_log = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(1)).first()
    prev_hash = last_log.hash if last_log else "0" * 64

    payload = {
        "action": action,
        "entity": entity,
        "entity_id": entity_id,
        "user_id": user.id,
    }
    current_hash = calculate_hash(prev_hash, payload)

    log = AuditLog(
        user_id=user.id,
        action=action,
        entity=entity,
        entity_id=entity_id,
        prev_hash=prev_hash,
        hash=current_hash,
    )
    db.add(log)
    return log


def fetch_audit_logs(
    db: Session,
    entity: str | None = None,
    user_id: int | None = None,
    limit: int = DEFAULT_AUDIT_LOG_LIMIT,
) -> list[AuditLog]:
    """Đọc bảng ``audit_logs`` cho API ``GET /audit-logs`` (chỉ admin gọi được).

    Args:
        db: Session SQLAlchemy của request.
        entity: Lọc theo loại dữ liệu (``"farm"`` / ``"batch"``); ``None`` = lấy tất cả.
        user_id: Lọc theo người thực hiện; ``None`` = lấy tất cả.
        limit: Số dòng tối đa trả về (mặc định ``DEFAULT_AUDIT_LOG_LIMIT``).

    Returns:
        list[AuditLog]: Log **mới nhất trước** (giảm dần theo ``id``). Dùng
        ``id`` giảm dần thay vì ``created_at`` vì các log trong cùng một giây
        vẫn được sắp xếp đúng thứ tự phát sinh.
    """
    statement = (
        select(AuditLog)
        # Nạp sẵn tài khoản để serialize `email` mà không phát sinh truy vấn phụ.
        .options(joinedload(AuditLog.user))
        .order_by(AuditLog.id.desc())
        .limit(limit)
    )

    if entity is not None:
        statement = statement.where(AuditLog.entity == entity)
    if user_id is not None:
        statement = statement.where(AuditLog.user_id == user_id)

    return list(db.scalars(statement).all())


def verify_hash_chain(db: Session) -> list[dict]:
    """Kiểm tra toàn vẹn chuỗi băm của toàn bộ bảng audit_logs."""
    logs = db.scalars(select(AuditLog).order_by(AuditLog.id.asc())).all()
    prev_hash = "0" * 64
    errors = []

    for log in logs:
        payload = {
            "action": log.action,
            "entity": log.entity,
            "entity_id": log.entity_id,
            "user_id": log.user_id,
        }
        expected_hash = calculate_hash(prev_hash, payload)

        if log.prev_hash != prev_hash or log.hash != expected_hash:
            errors.append({
                "id": log.id,
                "error": "Hash mismatch",
                "expected_prev": prev_hash,
                "actual_prev": log.prev_hash,
                "expected_hash": expected_hash,
                "actual_hash": log.hash
            })

        prev_hash = log.hash

    return errors


from app.models import BatchEvent

def record_batch_event(db: Session, batch_id: int, event_type: str, payload: dict) -> BatchEvent:
    """Ghi nhận một sự kiện thay đổi của lô nông sản (Event Sourcing)."""
    last_event = db.scalars(
        select(BatchEvent)
        .where(BatchEvent.batch_id == batch_id)
        .order_by(BatchEvent.id.desc())
        .limit(1)
    ).first()
    previous_hash = last_event.current_hash if last_event else "0" * 64

    payload_str = json.dumps(payload, separators=(',', ':'), sort_keys=True)
    current_hash = calculate_hash(previous_hash, payload)

    event = BatchEvent(
        batch_id=batch_id,
        event_type=event_type,
        payload=payload_str,
        previous_hash=previous_hash,
        current_hash=current_hash,
    )
    db.add(event)
    return event

def verify_batch_chain(db: Session, batch_id: int) -> list[dict]:
    """Kiểm tra tính toàn vẹn chuỗi sự kiện của một lô cụ thể."""
    events = db.scalars(
        select(BatchEvent)
        .where(BatchEvent.batch_id == batch_id)
        .order_by(BatchEvent.id.asc())
    ).all()
    previous_hash = "0" * 64
    errors = []

    for event in events:
        payload = json.loads(event.payload)
        expected_hash = calculate_hash(previous_hash, payload)

        if event.previous_hash != previous_hash or event.current_hash != expected_hash:
            errors.append({
                "id": event.id,
                "error": "Hash mismatch",
                "expected_prev": previous_hash,
                "actual_prev": event.previous_hash,
                "expected_hash": expected_hash,
                "actual_hash": event.current_hash
            })
        previous_hash = event.current_hash
    return errors


__all__ = [
    "DEFAULT_AUDIT_LOG_LIMIT",
    "MAX_AUDIT_LOG_LIMIT",
    "calculate_hash",
    "fetch_audit_logs",
    "record_action",
    "verify_hash_chain",
    "record_batch_event",
    "verify_batch_chain",
]
