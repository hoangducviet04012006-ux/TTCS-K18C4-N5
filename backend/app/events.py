"""Ghi & đọc sự kiện của lô nông sản (Batch Event) - Tương thích ngược Sprint S-11 & Sprint 2.

Module này điều phối với app.hash_chain để ghi và đọc các sự kiện batch_events.
Mỗi sự kiện được ghi theo cơ chế append-only với mã băm prev_hash và current_hash/record_hash
tạo thành một chuỗi liên kết (hash chain) đảm bảo tính toàn vẹn dữ liệu.
"""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record_action
from app.hash_chain import (
    calculate_event_hash as hash_chain_calc,
    record_event,
    verify_batch_chain,
)
from app.models import ACTION_CREATE, BatchEvent, User


def _naive_utcnow() -> datetime:
    """Thời điểm hiện tại theo UTC, không kèm tzinfo."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def calculate_event_hash(*args, **kwargs) -> str:
    """Tính toán mã băm cho sự kiện.

    Hỗ trợ 2 chữ ký:
    1. Chữ ký Sprint 2 (T-24): calculate_event_hash(prev_hash: str, event_data: dict) -> str
    2. Chữ ký Sprint 1 (S-11): calculate_event_hash(batch_id, event_type, event_data, created_at, prev_hash) -> str
    """
    if len(args) == 2 and isinstance(args[0], str) and isinstance(args[1], dict):
        return hash_chain_calc(args[0], args[1])
    if "prev_hash" in kwargs and "event_data" in kwargs and isinstance(kwargs["event_data"], dict):
        return hash_chain_calc(kwargs["prev_hash"], kwargs["event_data"])

    # Fallback cho Sprint 2 dict payload
    if len(args) >= 5:
        batch_id, event_type, event_data, created_at, prev_hash = args[:5]
        payload = {"event_data": event_data, "event_type": event_type, "batch_id": batch_id}
        return hash_chain_calc(prev_hash, payload)

    return ""


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
    payload: dict[str, Any] | None = None,
) -> BatchEvent:
    """Tạo một sự kiện mới cho lô nông sản (append-only)."""
    eff_user_id = user.id if user is not None else (user_id or 1)
    eff_org_id = from_org_id or (user.organization_id if user else 1) or 1
    raw_desc = event_data if event_data is not None else (notes or f"Sự kiện {event_type}")

    evt_payload = payload or {
        "event_data": raw_desc,
        "description": raw_desc,
        "event_type": event_type,
    }

    event = record_event(
        db=db,
        batch_id=batch_id,
        event_type=event_type,
        payload=evt_payload,
        org_id=eff_org_id,
        user_id=eff_user_id,
        event_data=raw_desc,
        from_org_id=from_org_id,
        to_org_id=to_org_id,
        notes=notes,
    )

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


def verify_batch_events_integrity(db: Session, batch_id: int) -> dict:
    """Kiểm tra toàn vẹn chuỗi sự kiện của một lô nông sản.

    Ánh xạ kết quả sang cả chuẩn Sprint 1 và Sprint 2.
    """
    res = verify_batch_chain(db, batch_id)
    if not res.get("valid", True):
        # Đồng bộ error_type cho các test cũ S-12
        err = res.get("error_type")
        if err == "HASH_MISMATCH":
            res["error_type"] = "RECORD_HASH_MISMATCH"
        elif err == "CHAIN_BROKEN":
            res["error_type"] = "PREV_HASH_MISMATCH"
    return res


__all__ = [
    "calculate_event_hash",
    "fetch_batch_events",
    "record_batch_event",
    "verify_batch_events_integrity",
]
