"""Router quản lý sự kiện của lô nông sản (Batch Event) - Sprint S-11.

Đặc tính quan trọng:
- **Append-only**: Chỉ cung cấp API tạo mới (POST) và đọc (GET).
- **Tuyệt đối KHÔNG có API UPDATE (PUT/PATCH) hoặc DELETE** cho sự kiện.
"""

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.events import fetch_batch_events, record_batch_event, verify_batch_events_integrity
from app.models import Batch, BatchEvent, Farm, User
from app.schemas import BatchEventCreate, BatchEventResponse, BatchIntegrityResponse
from app.security import require_farmer


router = APIRouter(
    tags=["Batch Events"],
)


@router.post(
    "/batches/{batch_id}/events",
    response_model=BatchEventResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ghi nhận sự kiện mới cho lô nông sản (Append-only)",
    description=(
        "Thêm một sự kiện mới vào lịch sử lô nông sản theo cơ chế append-only. "
        "Hệ thống tự động tính toán mã băm SHA-256 (`prev_hash` và `record_hash`) "
        "để liên kết chuỗi dữ liệu không thể sửa đổi."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Chưa đăng nhập."},
        status.HTTP_403_FORBIDDEN: {"description": "Không có quyền thực hiện."},
        status.HTTP_404_NOT_FOUND: {"description": "Không tìm thấy lô nông sản."},
    },
)
def create_batch_event(
    payload: BatchEventCreate,
    batch_id: int = Path(..., ge=1, description="ID lô nông sản cần ghi sự kiện."),
    current_user: User = Depends(require_farmer),
    db: Session = Depends(get_db),
) -> BatchEvent:
    """Ghi thêm một sự kiện cho lô nông sản.

    Args:
        payload: Dữ liệu sự kiện (event_type, event_data).
        batch_id: ID lô nông sản.
        current_user: Người dùng hiện tại.
        db: Session DB.

    Returns:
        BatchEvent: Bản ghi sự kiện vừa được append.
    """
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy lô nông sản có id={batch_id}.",
        )

    # Kiểm tra phân quyền cách ly tổ chức
    farm = db.get(Farm, batch.farm_id)
    if farm and current_user.organization_id is not None and farm.organization_id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền thêm sự kiện cho lô nông sản của tổ chức khác.",
        )

    event = record_batch_event(
        db=db,
        batch_id=batch_id,
        event_type=payload.event_type,
        event_data=payload.event_data,
        user=current_user,
    )
    db.commit()
    db.refresh(event)
    return event


@router.get(
    "/batches/{batch_id}/events",
    response_model=list[BatchEventResponse],
    status_code=status.HTTP_200_OK,
    summary="Lấy danh sách sự kiện của một lô nông sản",
    description="Trả về danh sách sự kiện của lô theo thứ tự tăng dần.",
)
def list_events_for_batch(
    batch_id: int = Path(..., ge=1, description="ID lô nông sản."),
    db: Session = Depends(get_db),
) -> list[BatchEvent]:
    """Xem lịch sử sự kiện của một lô."""
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy lô nông sản có id={batch_id}.",
        )

    return fetch_batch_events(db, batch_id=batch_id)


@router.get(
    "/events",
    response_model=list[BatchEventResponse],
    status_code=status.HTTP_200_OK,
    summary="Xem toàn bộ danh sách sự kiện lô nông sản",
    description="Trả về danh sách tất cả sự kiện, hỗ trợ lọc theo batch_id, event_type.",
)
def list_all_events(
    batch_id: int | None = Query(default=None, ge=1, description="Lọc theo ID lô."),
    event_type: str | None = Query(default=None, description="Lọc theo loại sự kiện."),
    limit: int = Query(default=100, ge=1, le=500, description="Số lượng sự kiện tối đa."),
    db: Session = Depends(get_db),
) -> list[BatchEvent]:
    """Lấy danh sách sự kiện."""
    return fetch_batch_events(db, batch_id=batch_id, event_type=event_type, limit=limit)


@router.get(
    "/events/{event_id}",
    response_model=BatchEventResponse,
    status_code=status.HTTP_200_OK,
    summary="Xem chi tiết một sự kiện",
    description="Trả về chi tiết sự kiện theo ID.",
)
def get_event_detail(
    event_id: int = Path(..., ge=1, description="ID sự kiện."),
    db: Session = Depends(get_db),
) -> BatchEvent:
    """Xem chi tiết sự kiện theo ID."""
    event = db.get(BatchEvent, event_id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy sự kiện có id={event_id}.",
        )
    return event


@router.get(
    "/batches/{batch_id}/integrity",
    response_model=BatchIntegrityResponse,
    status_code=status.HTTP_200_OK,
    summary="Kiểm tra toàn vẹn chuỗi sự kiện của một lô (Hash Chain Integrity Check)",
    description=(
        "Kiểm tra cryptographic hash chain của toàn bộ sự kiện thuộc lô nông sản. "
        "Trả về `valid: true` nếu chuỗi toàn vẹn; trả về `valid: false` kèm `event_id`, "
        "`index`, `error_type`, `expected_hash`, `actual_hash` nếu phát hiện dữ liệu bị sửa/xoá."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Không tìm thấy lô nông sản."},
    },
)
@router.get(
    "/events/verify/{batch_id}",
    response_model=BatchIntegrityResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
def check_batch_integrity(
    batch_id: int = Path(..., ge=1, description="ID lô nông sản cần kiểm tra toàn vẹn."),
    db: Session = Depends(get_db),
) -> dict:
    """Kiểm tra toàn vẹn chuỗi sự kiện của lô nông sản."""
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy lô nông sản có id={batch_id}.",
        )

    return verify_batch_events_integrity(db, batch_id=batch_id)
