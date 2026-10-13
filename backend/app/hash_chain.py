"""Module quản lý Cryptographic Hash Chain và tính toàn vẹn bất biến (T-24, T-25, T-28).

Triển khai cấu trúc Hash-Chain dựa trên SHA-256:
- canonical_json: chuẩn hóa JSON payload loại bỏ khoảng trắng và sắp xếp key cố định.
- calculate_event_hash: tính mã băm từ prev_hash và canonical payload.
- record_event: thêm sự kiện mới vào chuỗi trong cùng transaction của caller.
- verify_batch_chain: kiểm tra toàn vẹn và phát hiện vị trí bị can thiệp (HASH_MISMATCH hoặc CHAIN_BROKEN).
"""

import hashlib
import json
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Batch, BatchEvent

GENESIS_HASH: str = "0" * 64
EVENT_TIME: ContextVar[datetime | None] = ContextVar("event_time", default=None)


def event_now() -> datetime:
    return EVENT_TIME.get() or datetime.now(timezone.utc).replace(tzinfo=None)


def canonical_json(data: dict[str, Any]) -> str:
    """Chuẩn hóa dữ liệu JSON payload (T-24).

    Quy tắc:
    - Sắp xếp key tăng dần: sort_keys=True.
    - Loại bỏ khoảng trắng thừa: separators=(',', ':').
    - Mã hóa chuỗi UTF-8 chuẩn (ensure_ascii=False).
    """
    if not isinstance(data, dict):
        data = dict(data) if data is not None else {}
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def calculate_event_hash(prev_hash: str, event_data: dict[str, Any]) -> str:
    """Tính mã băm SHA-256 cho sự kiện (T-24).

    Ghép prev_hash (64 hex) + canonical_json(event_data) rồi tính SHA-256 hex 64 ký tự.
    """
    c_json = canonical_json(event_data)
    combined = prev_hash + c_json
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def record_event(
    db: Session,
    batch_id: int,
    event_type: str,
    payload: dict[str, Any],
    org_id: int,
    user_id: int,
    event_data: str | None = None,
    from_org_id: int | None = None,
    to_org_id: int | None = None,
    notes: str | None = None,
) -> BatchEvent:
    """Ghi nhận một sự kiện mới vào Hash-chain bất biến của lô (T-25).

    Lưu ý:
    - Nhận session `db` từ bên gọi và KHÔNG tự commit riêng lẻ.
    - Lấy current_hash của sự kiện cuối cùng làm prev_hash. Nếu là sự kiện đầu tiên thì dùng GENESIS_HASH.
    - Cập nhật cả các trường tương thích ngược (record_hash, event_data, created_at, user_id).
    """
    db.execute(update(Batch).where(Batch.id == batch_id).values(status=Batch.status))
    now = event_now()
    payload = dict(payload)
    batch = db.get(Batch, batch_id)
    payload.setdefault("unit", batch.unit if batch else "kg")
    last_event = db.scalar(
        select(BatchEvent)
        .where(BatchEvent.batch_id == batch_id)
        .order_by(BatchEvent.id.desc())
        .limit(1)
    )

    prev_hash = last_event.current_hash if (last_event and last_event.current_hash) else GENESIS_HASH

    eff_notes = notes or payload.get("note") or payload.get("notes")
    raw_desc = (
        event_data
        or payload.get("event_data")
        or payload.get("description")
        or eff_notes
        or payload.get("message")
        or f"Sự kiện {event_type}"
    )
    eff_from_org = from_org_id if from_org_id is not None else payload.get("from_org_id", org_id)
    eff_to_org = to_org_id if to_org_id is not None else payload.get("to_org_id")

    payload["_record"] = {"batch_id": batch_id, "event_type": event_type,
                          "organization_id": org_id, "user_id": user_id,
                          "timestamp": now.isoformat(), "event_data": str(raw_desc),
                          "notes": eff_notes, "from_org_id": eff_from_org, "to_org_id": eff_to_org}
    current_hash = calculate_event_hash(prev_hash, payload)

    event = BatchEvent(
        batch_id=batch_id,
        event_type=event_type,
        payload=payload,
        organization_id=org_id,
        created_by_user_id=user_id,
        timestamp=now,
        prev_hash=prev_hash,
        current_hash=current_hash,
        # Các trường tương thích ngược với code cũ / Sprint 1
        user_id=user_id,
        created_at=now,
        record_hash=current_hash,
        event_data=str(raw_desc),
        from_org_id=eff_from_org,
        to_org_id=eff_to_org,
        notes=eff_notes,
    )
    db.add(event)
    db.flush()
    return event


def verify_batch_chain(db: Session, batch_id: int) -> dict[str, Any]:
    """Kiểm tra tính toàn vẹn chuỗi sự kiện của lô nông sản (T-28).

    Duyệt tuần tự toàn bộ sự kiện theo id tăng dần:
    1. Kiểm tra liên kết chuỗi prev_hash:
       - Sự kiện đầu tiên: prev_hash phải là genesis hash ("0" * 64).
       - Sự kiện sau: prev_hash phải khớp current_hash của sự kiện liền kề trước.
       Nếu sai lệch (do xóa bản ghi hoặc sửa prev_hash) -> trả về CHAIN_BROKEN.
    2. Băm lại canonical JSON payload và so khớp với current_hash:
       Nếu sai lệch (do sửa lén trường dữ liệu trong payload hoặc event_data) -> trả về HASH_MISMATCH.

    Returns:
        dict:
            Nếu hợp lệ: {"is_valid": True, "valid": True, "batch_id": batch_id, "total_events": n}
            Nếu lỗi: trả is_valid=False, batch_id, tampered_event_id và error_type
            (HASH_MISMATCH hoặc CHAIN_BROKEN).
    """
    events = list(
        db.scalars(
            select(BatchEvent)
            .where(BatchEvent.batch_id == batch_id)
            .order_by(BatchEvent.id.asc())
        ).all()
    )

    if not events:
        return {
            "is_valid": True,
            "valid": True,
            "batch_id": batch_id,
            "total_events": 0,
            "message": "Lô chưa có sự kiện nào trong hệ thống.",
        }

    for idx, event in enumerate(events):
        # 1. Kiểm tra tính liên tục của prev_hash
        if idx == 0:
            if event.prev_hash != GENESIS_HASH:
                return {
                    "is_valid": False,
                    "valid": False,
                    "batch_id": batch_id,
                    "tampered_event_id": event.id,
                    "event_id": event.id,
                    "index": idx,
                    "error_type": "CHAIN_BROKEN",
                    "expected_hash": GENESIS_HASH,
                    "actual_hash": event.prev_hash,
                    "message": f"Sự kiện đầu tiên (ID #{event.id}) không khớp Genesis Hash.",
                }
        else:
            prev_event = events[idx - 1]
            valid_prev = event.prev_hash == prev_event.current_hash
            if not valid_prev:
                expected = prev_event.current_hash or prev_event.record_hash
                return {
                    "is_valid": False,
                    "valid": False,
                    "batch_id": batch_id,
                    "tampered_event_id": event.id,
                    "event_id": event.id,
                    "index": idx,
                    "error_type": "CHAIN_BROKEN",
                    "expected_hash": expected,
                    "actual_hash": event.prev_hash,
                    "message": (
                        f"Chuỗi sự kiện bị đứt mạch tại vị trí index {idx} (Event ID #{event.id}). "
                        f"prev_hash không khớp với current_hash của sự kiện #{prev_event.id}."
                    ),
                }

        # 2. Kiểm tra tính toàn vẹn payload và event_data
        payload_data = event.payload if isinstance(event.payload, dict) else {}
        computed_hash = calculate_event_hash(event.prev_hash, payload_data)

        # Phát hiện nếu event_data bị can thiệp qua SQL trực tiếp
        data_in_payload = (
            payload_data.get("description")
            or payload_data.get("event_data")
            or payload_data.get("note")
            or payload_data.get("message")
        )
        event_data_tampered = (
            event.event_data is not None
            and data_in_payload is not None
            and event.event_data != str(data_in_payload)
        )

        metadata = payload_data.get("_record")
        metadata_tampered = metadata is not None and any([
            metadata.get("batch_id") != event.batch_id,
            metadata.get("event_type") != event.event_type,
            metadata.get("organization_id") != event.organization_id,
            metadata.get("user_id") != event.created_by_user_id,
            metadata.get("timestamp") != event.timestamp.isoformat(),
            metadata.get("event_data") != event.event_data,
            metadata.get("notes") != event.notes,
            metadata.get("from_org_id") != event.from_org_id,
            metadata.get("to_org_id") != event.to_org_id,
            event.record_hash != event.current_hash,
            event.user_id != event.created_by_user_id,
            event.created_at != event.timestamp,
        ])
        if computed_hash != event.current_hash or (event_data_tampered and metadata is None) or metadata_tampered:
            return {
                "is_valid": False,
                "valid": False,
                "batch_id": batch_id,
                "tampered_event_id": event.id,
                "event_id": event.id,
                "index": idx,
                "error_type": "HASH_MISMATCH",
                "expected_hash": computed_hash,
                "actual_hash": "TAMPERED_DATA" if event_data_tampered else event.current_hash,
                "message": (
                    f"Dữ liệu payload của sự kiện index {idx} (Event ID #{event.id}) đã bị chỉnh sửa hoặc giả mạo trái phép. "
                    f"Mã băm tính toán lại không khớp current_hash lưu trữ."
                ),
            }

    return {
        "is_valid": True,
        "valid": True,
        "batch_id": batch_id,
        "total_events": len(events),
        "message": f"Toàn bộ {len(events)} sự kiện của lô #{batch_id} đều toàn vẹn và hợp lệ.",
    }
