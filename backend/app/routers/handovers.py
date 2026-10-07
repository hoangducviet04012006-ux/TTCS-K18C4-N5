"""Router quản lý bàn giao lô hàng (Handover) và sự kiện lô hàng (BatchEvent).

Triển khai chức năng Bàn giao lô hàng (SCRUM-27 / S-15 và SCRUM-28 / S-16):
- POST /api/batches/{batch_id}/handover: Tạo yêu cầu bàn giao lô nông sản.
- GET  /api/handovers/pending          : Lấy danh sách lô đang chờ tổ chức xác nhận.
- POST /api/handovers/{id}/respond     : Tiếp nhận (ACCEPT) hoặc từ chối (REJECT) bàn giao.
- GET  /organizations                  : Lấy danh sách tổ chức để chọn bên nhận.
- GET  /batches/{batch_id}/events      : Lấy lịch sử sự kiện vòng đời lô hàng.
"""

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    EVENT_HANDOVER_ACCEPTED,
    EVENT_HANDOVER_PENDING,
    EVENT_HANDOVER_REJECTED,
    HANDOVER_ACCEPTED,
    HANDOVER_PENDING,
    HANDOVER_REJECTED,
    Batch,
    BatchEvent,
    Handover,
    Organization,
    User,
    _naive_utcnow,
)
from app.schemas import (
    BatchEventOut,
    HandoverCreate,
    HandoverOut,
    HandoverRespond,
    OrganizationResponse,
)
from app.security import require_farmer

router = APIRouter(tags=["Handovers"])


# -------------------------------------------------- 1. Bàn giao lô hàng ---
@router.post(
    "/batches/{batch_id}/handover",
    response_model=HandoverOut,
    status_code=status.HTTP_201_CREATED,
    summary="Tạo yêu cầu bàn giao lô hàng",
    description=(
        "Khởi tạo yêu cầu bàn giao lô nông sản từ tổ chức hiện tại sang tổ chức tiếp nhận.\n\n"
        "- Người gửi phải thuộc tổ chức đang nắm giữ lô hàng.\n"
        "- Không thể bàn giao cho chính mình.\n"
        "- Mỗi lô chỉ có tối đa 1 yêu cầu bàn giao ở trạng thái PENDING.\n"
        "- Ghi nhận 1 bản ghi sự kiện `HANDOVER_PENDING` vào bảng `batch_events`."
    ),
)
@router.post(
    "/api/batches/{batch_id}/handover",
    response_model=HandoverOut,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
def create_handover(
    payload: HandoverCreate,
    batch_id: int = Path(..., ge=1, description="Mã ID của lô hàng cần bàn giao."),
    current_user: User = Depends(require_farmer),
    db: Session = Depends(get_db),
) -> Handover:
    """Khởi tạo yêu cầu bàn giao lô hàng sang tổ chức khác."""
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy lô nông sản có id={batch_id}.",
        )

    # Xác định tổ chức đang nắm giữ lô hàng
    holder_org_id = batch.holder_org_id
    if holder_org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Lô nông sản chưa được liên kết với tổ chức sở hữu nào.",
        )

    # Kiểm tra người dùng có thuộc tổ chức đang giữ lô không
    if current_user.organization_id is not None and current_user.organization_id != holder_org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền bàn giao lô nông sản thuộc sở hữu của tổ chức khác.",
        )

    # Kiểm tra tổ chức tiếp nhận
    target_org = db.get(Organization, payload.to_org_id)
    if target_org is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy tổ chức tiếp nhận có id={payload.to_org_id}.",
        )

    # Kiểm tra không bàn giao cho chính mình
    if payload.to_org_id == holder_org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Không thể bàn giao lô hàng cho chính tổ chức hiện tại.",
        )

    # Kiểm tra lô chưa có bàn giao nào đang ở trạng thái PENDING
    existing_pending = db.scalar(
        select(Handover).where(
            Handover.batch_id == batch_id,
            Handover.status == HANDOVER_PENDING,
        )
    )
    if existing_pending is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Lô hàng này đang có một yêu cầu bàn giao ở trạng thái PENDING chờ xử lý.",
        )

    now = _naive_utcnow()
    handover = Handover(
        batch_id=batch_id,
        from_org_id=holder_org_id,
        to_org_id=payload.to_org_id,
        status=HANDOVER_PENDING,
        created_at=now,
        updated_at=now,
    )
    db.add(handover)
    db.flush()

    from app.events import record_batch_event
    record_batch_event(
        db=db,
        batch_id=batch_id,
        event_type=EVENT_HANDOVER_PENDING,
        user=current_user,
        from_org_id=holder_org_id,
        to_org_id=payload.to_org_id,
        notes=payload.note,
        event_data=payload.note,
    )

    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể tạo yêu cầu bàn giao trong cơ sở dữ liệu.",
        ) from exc

    db.refresh(handover)
    return handover


# ---------------------------------------- 2. Lấy danh sách lô chờ nhận ---
@router.get(
    "/handovers/pending",
    response_model=list[HandoverOut],
    status_code=status.HTTP_200_OK,
    summary="Lấy danh sách bàn giao chờ xác nhận",
    description="Trả về các bàn giao gửi đến tổ chức của người dùng hiện tại đang ở trạng thái PENDING.",
)
@router.get(
    "/api/handovers/pending",
    response_model=list[HandoverOut],
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
def list_pending_handovers(
    current_user: User = Depends(require_farmer),
    db: Session = Depends(get_db),
) -> list[Handover]:
    """Danh sách các yêu cầu bàn giao gửi đến tổ chức của user đang chờ duyệt."""
    if current_user.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tài khoản chưa được liên kết với tổ chức nào.",
        )

    handovers = list(
        db.scalars(
            select(Handover)
            .where(
                Handover.to_org_id == current_user.organization_id,
                Handover.status == HANDOVER_PENDING,
            )
            .order_by(Handover.created_at.desc())
        ).all()
    )
    return handovers


# -------------------------------- 3. Phản hồi yêu cầu (Accept / Reject) ---
@router.post(
    "/handovers/{handover_id}/respond",
    response_model=HandoverOut,
    status_code=status.HTTP_200_OK,
    summary="Phản hồi yêu cầu bàn giao",
    description=(
        "Chấp nhận (ACCEPT) hoặc từ chối (REJECT) yêu cầu bàn giao lô hàng.\n\n"
        "- Người gọi phải thuộc tổ chức tiếp nhận (`to_org_id`).\n"
        "- Yêu cầu bàn giao phải đang ở trạng thái PENDING.\n"
        "- Nếu ACCEPT: cập nhật `status = ACCEPTED`, đổi `batches.current_org_id = to_org_id`, "
        "ghi sự kiện `HANDOVER_ACCEPTED`.\n"
        "- Nếu REJECT: kiểm tra lý do từ chối (≥ 10 ký tự), cập nhật `status = REJECTED`, "
        "giữ nguyên chủ sở hữu lô, ghi sự kiện `HANDOVER_REJECTED`."
    ),
)
@router.post(
    "/api/handovers/{handover_id}/respond",
    response_model=HandoverOut,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
def respond_handover(
    payload: HandoverRespond,
    handover_id: int = Path(..., ge=1, description="Mã ID của yêu cầu bàn giao."),
    current_user: User = Depends(require_farmer),
    db: Session = Depends(get_db),
) -> Handover:
    """Xử lý tiếp nhận hoặc từ chối bàn giao trong transaction an toàn."""
    handover = db.get(Handover, handover_id)
    if handover is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy yêu cầu bàn giao có id={handover_id}.",
        )

    if handover.status != HANDOVER_PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Yêu cầu bàn giao này đã ở trạng thái {handover.status}, không thể xử lý lại.",
        )

    if current_user.organization_id is not None and current_user.organization_id != handover.to_org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chỉ thành viên thuộc tổ chức tiếp nhận mới có quyền xử lý yêu cầu bàn giao này.",
        )

    batch = db.get(Batch, handover.batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lô nông sản #{handover.batch_id} liên quan không tồn tại.",
        )

    now = _naive_utcnow()
    from app.events import record_batch_event
    handover.updated_at = now

    action = payload.action.strip().upper()

    if action == "ACCEPT":
        handover.status = HANDOVER_ACCEPTED
        batch.current_org_id = handover.to_org_id
        record_batch_event(
            db=db,
            batch_id=batch.id,
            event_type=EVENT_HANDOVER_ACCEPTED,
            user=current_user,
            from_org_id=handover.from_org_id,
            to_org_id=handover.to_org_id,
            notes="Đã tiếp nhận bàn giao lô hàng thành công.",
            event_data="Đã tiếp nhận bàn giao lô hàng thành công.",
        )
    elif action == "REJECT":
        if not payload.reject_reason or len(payload.reject_reason.strip()) < 10:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Lý do từ chối là bắt buộc và phải có tối thiểu 10 ký tự.",
            )
        handover.status = HANDOVER_REJECTED
        handover.reject_reason = payload.reject_reason.strip()
        record_batch_event(
            db=db,
            batch_id=batch.id,
            event_type=EVENT_HANDOVER_REJECTED,
            user=current_user,
            from_org_id=handover.from_org_id,
            to_org_id=handover.to_org_id,
            notes=payload.reject_reason.strip(),
            event_data=payload.reject_reason.strip(),
        )

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Hành động không hợp lệ. Chỉ chấp nhận 'ACCEPT' hoặc 'REJECT'.",
        )

    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể cập nhật trạng thái bàn giao trong cơ sở dữ liệu.",
        ) from exc

    db.refresh(handover)
    return handover


# --------------------------------------------- 4. Danh sách tổ chức ---
@router.get(
    "/organizations",
    response_model=list[OrganizationResponse],
    status_code=status.HTTP_200_OK,
    summary="Lấy danh sách tổ chức",
    description="Trả về danh sách các tổ chức / hợp tác xã trong hệ thống (dùng cho dropdown chọn bên nhận).",
)
@router.get(
    "/api/organizations",
    response_model=list[OrganizationResponse],
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
def list_organizations(
    current_user: User = Depends(require_farmer),
    db: Session = Depends(get_db),
) -> list[Organization]:
    """Danh sách các tổ chức trong hệ thống."""
    _ = current_user
    return list(db.scalars(select(Organization).order_by(Organization.id)).all())


# ------------------------------------------- 5. Lịch sử sự kiện lô hàng ---
@router.get(
    "/batches/{batch_id}/events",
    response_model=list[BatchEventOut],
    status_code=status.HTTP_200_OK,
    summary="Lấy sự kiện vòng đời của lô hàng",
    description="Trả về toàn bộ sự kiện truy xuất nguồn gốc (tạo mới, bàn giao, tiếp nhận, từ chối...) của lô hàng.",
)
@router.get(
    "/api/batches/{batch_id}/events",
    response_model=list[BatchEventOut],
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
def list_batch_events(
    batch_id: int = Path(..., ge=1, description="Mã ID của lô hàng."),
    db: Session = Depends(get_db),
) -> list[BatchEvent]:
    """Lấy danh sách các sự kiện vòng đời của lô hàng."""
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy lô nông sản có id={batch_id}.",
        )
    return list(
        db.scalars(
            select(BatchEvent)
            .where(BatchEvent.batch_id == batch_id)
            .order_by(BatchEvent.created_at.desc())
        ).all()
    )
