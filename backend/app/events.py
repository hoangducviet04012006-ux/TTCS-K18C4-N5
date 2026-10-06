"""Ghi & đọc sự kiện của lô nông sản (Batch Event) - Sprint S-11.

Module này là điểm duy nhất chịu trách nhiệm ghi và đọc các sự kiện (batch_events).
Mỗi sự kiện được ghi theo cơ chế **append-only** với mã bămprev_hash và record_hash
tạo thành một chuỗi liên kết (hash chain) đảm bảo tính toàn vẹn dữ liệu.
"""

import hashlib
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record_action
from app.models import ACTION_CREATE, BatchEvent, User


def _naive_utcnow() -> datetime:
    """Thời điểm hiện tại theo UTC, không kèm tzinfo."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def calculate_event_hash(
    batch_id: int,
    event_type: str,
    event_data: str | None,
    created_at: datetime,
    prev_hash: str,
) -> str:
    """Tính toán SHA-256 record_hash cho sự kiện lô nông sản.

    Payload mã hóa dạng: batch_id|event_type|event_data|created_at_iso|prev_hash
    """
    created_at_str = created_at.isoformat()
    raw = f"{batch_id}|{event_type}|{event_data or ''}|{created_at_str}|{prev_hash}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def record_batch_event(
    db: Session,
    batch_id: int,
    event_type: str,
    event_data: str | None = None,
    user: User | None = None,
    user_id: int | None = None,
    from_org_id: int | None = None,
    to_org_id: int | None = None,
    notes: str | None = None,
) -> BatchEvent:
    """Tạo một sự kiện mới cho lô nông sản (append-only).

    Lấy record_hash của sự kiện trước đó của cùng lô làm prev_hash.
    Nếu là sự kiện đầu tiên của lô, prev_hash là 64 ký tự '0'.
    """
    last_event = db.scalar(
        select(BatchEvent)
        .where(BatchEvent.batch_id == batch_id)
        .order_by(BatchEvent.id.desc())
        .limit(1)
    )
    prev_hash = last_event.record_hash if (last_event and last_event.record_hash) else "0" * 64
    now = _naive_utcnow()

    eff_user_id = user.id if user is not None else user_id
    eff_data = event_data if event_data is not None else notes

    record_hash = calculate_event_hash(batch_id, event_type, eff_data, now, prev_hash)

    event = BatchEvent(
        batch_id=batch_id,
        event_type=event_type,
        event_data=eff_data,
        user_id=eff_user_id,
        from_org_id=from_org_id,
        to_org_id=to_org_id,
        notes=notes,
        created_at=now,
        prev_hash=prev_hash,
        record_hash=record_hash,
    )
    db.add(event)
    db.flush()

    if user is not None:
        record_action(db, user, ACTION_CREATE, "batch_event", event.id)

    return event


def fetch_batch_events(
    db: Session,
    batch_id: int | None = None,
    event_type: str | None = None,
    limit: int = 100,
) -> list[BatchEvent]:
    """Đọc danh sách sự kiện lô nông sản."""
    stmt = select(BatchEvent).order_by(BatchEvent.id.asc()).limit(limit)
    if batch_id is not None:
        stmt = stmt.where(BatchEvent.batch_id == batch_id)
    if event_type is not None:
        stmt = stmt.where(BatchEvent.event_type == event_type)

    return list(db.scalars(stmt).all())


__all__ = [
    "calculate_event_hash",
    "fetch_batch_events",
    "record_batch_event",
    "verify_batch_events_integrity",
]


def verify_batch_events_integrity(db: Session, batch_id: int) -> dict:
    """Kiểm tra toàn vẹn chuỗi sự kiện của một lô nông sản (Hash Chain Verification) - Sprint S-12."""
    events = fetch_batch_events(db, batch_id=batch_id, limit=10000)

    if not events:
        return {
            "valid": True,
            "batch_id": batch_id,
            "total_events": 0,
            "message": "Lô nông sản chưa có sự kiện nào trong hệ thống.",
        }

    for idx, event in enumerate(events):
        if idx == 0:
            expected_prev_hash = "0" * 64
            if event.prev_hash != expected_prev_hash:
                return {
                    "valid": False,
                    "batch_id": batch_id,
                    "event_id": event.id,
                    "index": idx,
                    "error_type": "PREV_HASH_MISMATCH",
                    "expected_hash": expected_prev_hash,
                    "actual_hash": event.prev_hash,
                    "message": f"Sự kiện đầu tiên (ID #{event.id}) có prev_hash không đúng chuẩn genesis.",
                }
        else:
            prev_event = events[idx - 1]
            if event.prev_hash != prev_event.record_hash:
                return {
                    "valid": False,
                    "batch_id": batch_id,
                    "event_id": event.id,
                    "index": idx,
                    "error_type": "PREV_HASH_MISMATCH",
                    "expected_hash": prev_event.record_hash,
                    "actual_hash": event.prev_hash,
                    "message": (
                        f"Chuỗi sự kiện bị đứt mạch tại vị trí index {idx} (Event ID #{event.id}). "
                        f"prev_hash của sự kiện hiện tại ({event.prev_hash[:12]}...) không khớp với "
                        f"record_hash của sự kiện trước đó #{prev_event.id} ({prev_event.record_hash[:12]}...). "
                        f"Có thể sự kiện trước đó đã bị xóa hoặc prev_hash bị chỉnh sửa."
                    ),
                }

        eff_data = event.event_data if event.event_data is not None else event.notes
        computed_hash = calculate_event_hash(
            batch_id=event.batch_id,
            event_type=event.event_type,
            event_data=eff_data,
            created_at=event.created_at,
            prev_hash=event.prev_hash,
        )

        if computed_hash != event.record_hash:
            return {
                "valid": False,
                "batch_id": batch_id,
                "event_id": event.id,
                "index": idx,
                "error_type": "RECORD_HASH_MISMATCH",
                "expected_hash": computed_hash,
                "actual_hash": event.record_hash,
                "message": (
                    f"Dữ liệu sự kiện tại vị trí index {idx} (Event ID #{event.id}) đã bị chỉnh sửa hoặc giả mạo. "
                    f"Mã băm tính toán lại ({computed_hash[:12]}...) không khớp với record_hash lưu trong cơ sở dữ liệu ({event.record_hash[:12]}...)."
                ),
            }

    return {
        "valid": True,
        "batch_id": batch_id,
        "total_events": len(events),
        "message": f"Toàn bộ {len(events)} sự kiện của lô #{batch_id} đều hợp lệ và đảm bảo tính toàn vẹn dữ liệu.",
    }


