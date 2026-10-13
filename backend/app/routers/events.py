"""Router quản lý sự kiện của lô nông sản (Batch Event) - Sprint 2 (T-23, T-26, T-28, T-31).

Đặc tính quan trọng:
- Append-only (T-26): Chỉ cung cấp API tạo mới (POST) và đọc (GET).
  Tuyệt đối KHÔNG có bất kỳ API nào cho phép UPDATE (PUT/PATCH) hoặc DELETE sự kiện.
- T-31: GET /batches/{id}/events truy vấn SQL JOIN giữa batch_events, organizations,
  users trong 1 lượt query duy nhất (tránh N+1), sắp xếp timestamp tăng dần.
- T-28 & T-29: GET /batches/{id}/integrity kiểm tra toàn vẹn hash-chain và phát hiện
  chính xác vị trí ID sự kiện bị can thiệp.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.hash_chain import record_event, verify_batch_chain
from app.models import (
    ROLE_ADMIN,
    ROLE_INSPECTOR,
    ROLE_SYSTEM_ADMIN,
    Batch,
    BatchEvent,
    Organization,
    User,
)
from app.schemas import BatchEventCreate, BatchEventOut, BatchIntegrityResponse
from app.security import get_current_user, require_farmer
from app.services.rbac import check_action_permission
from app.services.permissions import can_view_batch
from app.services.rbac import get_handover_cutoff_event_id

router = APIRouter(
    tags=["Batch Events"],
)


def assert_history_access(db: Session, user: User, batch_id: int) -> None:
    if user.role in (ROLE_INSPECTOR, ROLE_SYSTEM_ADMIN, ROLE_ADMIN):
        return
    if not can_view_batch(db, user.organization_id, batch_id, user_role=user.role):
        raise HTTPException(403, "Bạn không có quyền xem lịch sử lô này.")


def redact_event(event: BatchEventOut, user: User) -> BatchEventOut:
    if event.organization_id != user.organization_id:
        public = {"batch_code", "product_id", "plot_id", "quantity", "initial_quantity",
                  "remaining_quantity", "from_org_id", "to_org_id", "parent_batch_id",
                  "parent_batch_ids", "child_batch_ids", "child_codes", "merged_batch_id",
                  "product_name", "total_quantity", "unit", "quantity_taken", "total_split_quantity",
                  "merged_batch_code", "parent_batch_code", "is_overdue"}
        safe_payload = {k: v for k, v in event.payload.items() if k in public}
        if event.event_type == "MERGE":
            safe_payload["parent_batches"] = [
                {k: v for k, v in item.items() if k in {"id", "code", "quantity_taken"}}
                for item in event.payload.get("parent_batches", []) if isinstance(item, dict)
            ]
        return event.model_copy(update={
            "payload": safe_payload,
            "event_data": "Thông tin truy xuất liên tổ chức", "username": None,
            "created_by_user_id": None, "user_id": None, "notes": None,
        })
    return event


@router.post(
    "/batches/{batch_id}/events",
    response_model=BatchEventOut,
    status_code=status.HTTP_201_CREATED,
    summary="Ghi nhận sự kiện mới cho lô nông sản (Append-only - T-23, T-25)",
    description=(
        "Thêm một sự kiện mới vào lịch sử lô nông sản theo cơ chế append-only. "
        "Hệ thống tự động tính toán mã băm SHA-256 (`prev_hash` và `current_hash`) "
        "để liên kết chuỗi dữ liệu bất biến không thể sửa đổi."
    ),
)
@router.post(
    "/api/batches/{batch_id}/events",
    response_model=BatchEventOut,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
def create_batch_event(
    payload: BatchEventCreate,
    batch_id: int = Path(..., ge=1, description="ID lô nông sản cần ghi sự kiện."),
    current_user: User = Depends(require_farmer),
    db: Session = Depends(get_db),
) -> BatchEvent:
    """Ghi thêm một sự kiện cho lô nông sản."""
    check_action_permission(current_user, "EVENT_CREATE")
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy lô nông sản có id={batch_id}.",
        )

    # Kiểm tra phân quyền cách ly tổ chức
    if (
        current_user.organization_id is None
        or batch.current_org_id != current_user.organization_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền thêm sự kiện cho lô nông sản của tổ chức khác.",
        )

    # Chuẩn bị payload có cấu trúc (T-23)
    reserved = {"HARVEST", "HANDOVER_INIT", "HANDOVER_ACCEPT", "HANDOVER_REJECT",
                "SPLIT", "GENESIS_SPLIT", "MERGE", "EXPORT_MERGE", "BATCH_UPDATED", "CONSUMED",
                "RECALL_INIT", "RECALL_AFFECTED", "RECALL_ACKNOWLEDGED", "RECALL_COMPLETED"}
    if not payload.event_type.strip():
        raise HTTPException(400, "Loại sự kiện không được để trống.")
    if payload.event_type.strip().upper() in reserved:
        raise HTTPException(400, "Sự kiện vòng đời chỉ được ghi bởi thao tác nghiệp vụ tương ứng.")
    event_payload: dict[str, Any] = payload.payload or {}
    if not event_payload:
        event_payload = {
            "description": payload.event_data or f"Sự kiện {payload.event_type}",
            "batch_code": batch.code,
        }

    event = record_event(
        db=db,
        batch_id=batch_id,
        event_type=payload.event_type,
        payload=event_payload,
        org_id=batch.current_org_id,
        user_id=current_user.id,
        event_data=payload.event_data,
    )
    db.commit()
    db.refresh(event)
    return event


@router.get(
    "/batches/{batch_id}/events",
    response_model=list[BatchEventOut],
    status_code=status.HTTP_200_OK,
    summary="Lấy dòng thời gian sự kiện của một lô (T-31)",
    description=(
        "Thực hiện câu lệnh SQL JOIN giữa `batch_events`, `organizations`, `users` "
        "trong đúng 1 lượt query duy nhất (tránh lỗi N+1 query), sắp xếp theo timestamp tăng dần."
    ),
)
def list_events_for_batch(
    batch_id: int = Path(..., ge=1, description="ID lô nông sản."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[BatchEventOut]:
    """Xem dòng thời gian sự kiện của lô tối ưu SQL JOIN 1 lượt (T-31)."""
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy lô nông sản có id={batch_id}.",
        )

    assert_history_access(db, current_user, batch_id)

    # T-31: Viết truy vấn SQL JOIN giữa batch_events, organizations, users trong đúng 1 lượt query
    stmt = (
        select(
            BatchEvent,
            Organization.name.label("org_name"),
            User.username.label("user_name"),
        )
        .outerjoin(Organization, BatchEvent.organization_id == Organization.id)
        .outerjoin(User, BatchEvent.created_by_user_id == User.id)
        .where(BatchEvent.batch_id == batch_id)
        .order_by(BatchEvent.timestamp.asc(), BatchEvent.id.asc())
    )

    rows = db.execute(stmt).all()

    # S-23: Tổ chức đã bàn giao chỉ được xem lịch sử tính đến thời điểm bàn giao (theo event.id)
    cutoff_id = get_handover_cutoff_event_id(db, batch_id, current_user.organization_id, current_user.role)
    if cutoff_id is not None:
        rows = [r for r in rows if r[0].id <= cutoff_id]

    results: list[BatchEventOut] = []
    for event, org_name, user_name in rows:
        desc = event.event_data or (
            event.payload.get("event_data")
            or event.payload.get("description")
            if isinstance(event.payload, dict)
            else ""
        ) or ""
        results.append(
            BatchEventOut(
                id=event.id,
                batch_id=event.batch_id,
                event_type=event.event_type,
                payload=event.payload or {},
                event_data=str(desc),
                organization_id=event.organization_id,
                organization_name=org_name or "",
                created_by_user_id=event.created_by_user_id,
                username=user_name or "",
                timestamp=event.timestamp,
                prev_hash=event.prev_hash,
                current_hash=event.current_hash,
                record_hash=event.current_hash,
                created_at=event.timestamp,
                from_org_id=event.from_org_id,
                to_org_id=event.to_org_id,
                notes=event.notes,
            )
        )
    return [redact_event(e, current_user) for e in results]


@router.get(
    "/batches/{batch_id}/integrity",
    response_model=BatchIntegrityResponse,
    status_code=status.HTTP_200_OK,
    summary="Kiểm tra toàn vẹn chuỗi sự kiện của một lô (T-28, T-29)",
    description=(
        "Xác thực toàn bộ cryptographic hash chain SHA-256 của lô nông sản. "
        "Nếu chuỗi nguyên vẹn -> trả về is_valid: True. "
        "Nếu phát hiện bị can thiệp -> trả về is_valid: False, kèm tampered_event_id "
        "và error_type ('HASH_MISMATCH' hoặc 'CHAIN_BROKEN')."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Không tìm thấy lô nông sản."},
    },
)
def check_batch_integrity(
    batch_id: int = Path(..., ge=1, description="ID lô nông sản cần kiểm tra toàn vẹn."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Kiểm tra toàn vẹn chuỗi sự kiện theo T-28."""
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy lô nông sản có id={batch_id}.",
        )

    assert_history_access(db, current_user, batch_id)
    res = verify_batch_chain(db, batch_id=batch_id)
    if not res.get("is_valid", True):
        res = dict(res)
        err = res.get("error_type")
        if err == "HASH_MISMATCH":
            res["error_type"] = "RECORD_HASH_MISMATCH"
        elif err == "CHAIN_BROKEN":
            res["error_type"] = "PREV_HASH_MISMATCH"
    return res


@router.get(
    "/events/verify/{batch_id}",
    response_model=BatchIntegrityResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
def check_batch_integrity_alias(
    batch_id: int = Path(..., ge=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Alias kiểm tra toàn vẹn."""
    return check_batch_integrity(batch_id=batch_id, current_user=current_user, db=db)


@router.get(
    "/events",
    response_model=list[BatchEventOut],
    status_code=status.HTTP_200_OK,
    summary="Xem toàn bộ danh sách sự kiện lô nông sản",
)
def list_all_events(
    batch_id: int | None = Query(default=None, ge=1, description="Lọc theo ID lô."),
    event_type: str | None = Query(default=None, description="Lọc theo loại sự kiện."),
    limit: int = Query(default=100, ge=1, le=500, description="Số lượng sự kiện tối đa."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[BatchEvent]:
    """Lấy danh sách sự kiện."""
    if batch_id is not None:
        assert_history_access(db, current_user, batch_id)
    accessible = [bid for bid in db.scalars(select(Batch.id)).all()
                  if can_view_batch(db, current_user.organization_id, bid)]
    stmt = select(BatchEvent).where(BatchEvent.batch_id.in_(accessible)).order_by(BatchEvent.id.asc()).limit(limit)
    if batch_id is not None:
        stmt = stmt.where(BatchEvent.batch_id == batch_id)
    if event_type is not None:
        stmt = stmt.where(BatchEvent.event_type == event_type)
    return [redact_event(BatchEventOut.model_validate(e), current_user) for e in db.scalars(stmt).all()]


@router.get(
    "/events/{event_id}",
    response_model=BatchEventOut,
    status_code=status.HTTP_200_OK,
    summary="Xem chi tiết một sự kiện",
)
def get_event_detail(
    event_id: int = Path(..., ge=1, description="ID sự kiện."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BatchEvent:
    """Xem chi tiết sự kiện theo ID."""
    event = db.get(BatchEvent, event_id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy sự kiện có id={event_id}.",
        )
    assert_history_access(db, current_user, event.batch_id)

    # S-23: Kiểm tra giới hạn thời điểm bàn giao đối với sự kiện chi tiết (theo event.id)
    cutoff_id = get_handover_cutoff_event_id(db, event.batch_id, current_user.organization_id, current_user.role)
    if cutoff_id is not None and event.id > cutoff_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền xem sự kiện diễn ra sau khi tổ chức đã bàn giao lô này.",
        )

    return redact_event(BatchEventOut.model_validate(event), current_user)
