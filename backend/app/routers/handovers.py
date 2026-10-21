"""Router quản lý bàn giao lô hàng giữa các tổ chức (Handover - T-35, T-36, T-37, T-38).

- POST /batches/{id}/handover: Tạo yêu cầu bàn giao, ghi sự kiện HANDOVER_INIT vào hash-chain.
- GET  /handovers/pending: Lấy danh sách lô đang chờ tổ chức xác nhận.
- POST /handovers/{id}/accept: Tiếp nhận bàn giao (chỉ bên nhận), đổi chủ sở hữu, ghi sự kiện HANDOVER_ACCEPT.
- POST /handovers/{id}/reject: Từ chối bàn giao (chỉ bên nhận), yêu cầu lý do >= 10 ký tự, ghi sự kiện HANDOVER_REJECT.
- POST /handovers/{id}/respond: Tiếp nhận hoặc từ chối bàn giao (tương thích ngược).
- GET  /organizations: Danh sách các tổ chức trong hệ thống.
"""

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.audit import record_action
from app.database import get_db
from app.hash_chain import record_event, event_now as _naive_utcnow
from app.models import (
    EVENT_HANDOVER_ACCEPT,
    EVENT_HANDOVER_INIT,
    EVENT_HANDOVER_REJECT,
    HANDOVER_ACCEPTED,
    HANDOVER_PENDING,
    HANDOVER_REJECTED,
    ROLE_ADMIN,
    ROLE_SYSTEM_ADMIN,
    Batch,
    Handover,
    Organization,
    User,
)
from app.schemas import (
    BatchEventOut,
    HandoverCreate,
    HandoverOut,
    HandoverRejectRequest,
    HandoverRespond,
    OrganizationCreate,
    OrganizationResponse,
)
from app.security import get_current_user, require_admin, require_farmer
from app.services.overdue_job import check_overdue_handovers
from app.services.rbac import check_action_permission

from app.services.recall import ensure_not_recalled

router = APIRouter(tags=["Handovers"])


# ==============================================================================
# 1. TẠO YÊU CẦU BÀN GIAO LÔ NÔNG SẢN (T-36)
# ==============================================================================
@router.post(
    "/batches/{batch_id}/handover",
    response_model=HandoverOut,
    status_code=status.HTTP_201_CREATED,
    summary="Tạo yêu cầu bàn giao lô hàng (T-36)",
    description=(
        "Khởi tạo yêu cầu bàn giao lô nông sản từ tổ chức hiện tại sang tổ chức tiếp nhận.\n\n"
        "- Chặn nếu `to_org_id == from_org_id` (chặn tự bàn giao cho chính mình - HTTP 400).\n"
        "- Chặn nếu lô đang có yêu cầu bàn giao PENDING khác (HTTP 400).\n"
        "- Ghi sự kiện `HANDOVER_INIT` vào hash-chain, lô vẫn thuộc quyền bên giao."
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
    """Tạo yêu cầu bàn giao lô hàng sang tổ chức khác (T-36)."""
    check_action_permission(current_user, "HANDOVER_INIT")
    db.execute(update(Batch).values(status=Batch.status))
    db.expire_all()
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy lô nông sản có id={batch_id}.",
        )

    ensure_not_recalled(db, batch.id)

    # Xác định tổ chức đang nắm giữ lô hàng
    if batch.status == "CONSUMED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Lô hàng đã tiêu thụ (CONSUMED), không thể bàn giao.",
        )
    if batch.status not in ("ACTIVE", "SPLIT") or not batch.remaining_quantity or batch.remaining_quantity <= 0:
        raise HTTPException(400, "Lô đã hết khối lượng hoặc không còn ở trạng thái được bàn giao.")
    holder_org_id = batch.holder_org_id
    if holder_org_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Lô nông sản chưa được liên kết với tổ chức sở hữu nào.",
        )

    # Kiểm tra người dùng có thuộc tổ chức đang giữ lô không
    if current_user.organization_id is None or current_user.organization_id != holder_org_id:
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

    # Chặn tự bàn giao cho chính mình (T-36)
    if payload.to_org_id == holder_org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Không thể bàn giao lô hàng cho chính tổ chức hiện tại.",
        )

    # Chặn nếu lô đang có yêu cầu bàn giao PENDING khác (T-36)
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

    # Ghi sự kiện HANDOVER_INIT vào hash-chain (T-36)
    event_payload = {
        "handover_id": handover.id,
        "batch_code": batch.code,
        "from_org_id": holder_org_id,
        "to_org_id": payload.to_org_id,
        "note": payload.note or "Bàn giao lô nông sản",
    }
    record_event(
        db=db,
        batch_id=batch_id,
        event_type=EVENT_HANDOVER_INIT,
        payload=event_payload,
        org_id=holder_org_id,
        user_id=current_user.id,
    )

    record_action(db, current_user, "update", "handover", handover.id,
                  operation="handover_init", batch_ids=[batch.id])
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


# ==============================================================================
# 2. XÁC NHẬN TIẾP NHẬN BÀN GIAO (T-37)
# ==============================================================================
@router.post(
    "/handovers/{handover_id}/accept",
    response_model=HandoverOut,
    status_code=status.HTTP_200_OK,
    summary="Tiếp nhận bàn giao lô hàng (T-37)",
    description=(
        "Chỉ tổ chức tiếp nhận (`to_org_id`) mới được phép gọi API (sai trả về 403 Forbidden).\n\n"
        "Trong 1 transaction duy nhất:\n"
        "- Đổi `batches.current_org_id` sang bên nhận.\n"
        "- Cập nhật `handover.status = ACCEPTED`.\n"
        "- Ghi sự kiện `HANDOVER_ACCEPT` vào hash-chain."
    ),
)
def accept_handover(
    handover_id: int = Path(..., ge=1, description="Mã ID của yêu cầu bàn giao."),
    current_user: User = Depends(require_farmer),
    db: Session = Depends(get_db),
) -> Handover:
    """Tiếp nhận lô hàng bàn giao (T-37)."""
    check_action_permission(current_user, "HANDOVER_RESPOND")
    db.execute(update(Batch).values(status=Batch.status))
    db.expire_all()
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

    # Chỉ bên nhận mới được gọi (sai trả về 403 Forbidden - T-37)
    if current_user.organization_id is None or current_user.organization_id != handover.to_org_id:
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

    ensure_not_recalled(db, batch.id)

    now = _naive_utcnow()
    # 1. Đổi batches.current_org_id sang bên nhận (T-37)
    was_overdue = handover.is_overdue or (now - handover.created_at).total_seconds() >= 48 * 3600
    from app.services.traceability import clear_trace_cache
    clear_trace_cache()
    from app.services.locations import clear_on_handover
    clear_on_handover(db, batch.id)
    batch.current_org_id = handover.to_org_id
    handover.is_overdue = False

    # 2. Cập nhật handover sang ACCEPTED (T-37)
    handover.status = HANDOVER_ACCEPTED
    handover.updated_at = now

    # 3. Ghi sự kiện HANDOVER_ACCEPT vào hash-chain (T-37, T-57)
    event_payload = {
        "handover_id": handover.id,
        "batch_code": batch.code,
        "from_org_id": handover.from_org_id,
        "to_org_id": handover.to_org_id,
        "message": "Đã tiếp nhận bàn giao lô hàng thành công.",
    }
    if was_overdue:
        event_payload["is_overdue"] = True
        event_payload["note"] = "Bàn giao quá hạn 48h được chấp nhận muộn."
    record_event(
        db=db,
        batch_id=batch.id,
        event_type=EVENT_HANDOVER_ACCEPT,
        payload=event_payload,
        org_id=handover.to_org_id,
        user_id=current_user.id,
    )

    record_action(db, current_user, "update", "handover", handover.id,
                  operation="handover_accept", batch_ids=[batch.id])
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


# ==============================================================================
# 3. TỪ CHỐI TIẾP NHẬN BÀN GIAO (T-38)
# ==============================================================================
@router.post(
    "/handovers/{handover_id}/reject",
    response_model=HandoverOut,
    status_code=status.HTTP_200_OK,
    summary="Từ chối bàn giao lô hàng (T-38)",
    description=(
        "Chỉ bên nhận mới được gọi (sai trả về 403 Forbidden).\n\n"
        "Bắt buộc có `reject_reason` dài tối thiểu 10 ký tự.\n"
        "Cập nhật handover sang REJECTED, ghi sự kiện `HANDOVER_REJECT`, lô giữ nguyên chủ."
    ),
)
def reject_handover(
    payload: HandoverRejectRequest,
    handover_id: int = Path(..., ge=1, description="Mã ID của yêu cầu bàn giao."),
    current_user: User = Depends(require_farmer),
    db: Session = Depends(get_db),
) -> Handover:
    """Từ chối nhận bàn giao kèm lý do tối thiểu 10 ký tự (T-38)."""
    check_action_permission(current_user, "HANDOVER_RESPOND")
    db.execute(update(Batch).values(status=Batch.status))
    db.expire_all()
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

    # Chỉ bên nhận mới được gọi (sai trả về 403 - T-38)
    if current_user.organization_id is None or current_user.organization_id != handover.to_org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chỉ thành viên thuộc tổ chức tiếp nhận mới có quyền xử lý yêu cầu bàn giao này.",
        )

    # Kiểm tra độ dài lý do tối thiểu 10 ký tự (T-38)
    reason = payload.reject_reason.strip() if payload.reject_reason else ""
    if len(reason) < 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Lý do từ chối là bắt buộc và phải có tối thiểu 10 ký tự.",
        )

    batch = db.get(Batch, handover.batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lô nông sản #{handover.batch_id} liên quan không tồn tại.",
        )

    now = _naive_utcnow()
    handover.status = HANDOVER_REJECTED
    handover.is_overdue = False
    handover.reject_reason = reason
    handover.updated_at = now

    # Ghi sự kiện HANDOVER_REJECT vào hash-chain, lô giữ nguyên chủ
    event_payload = {
        "handover_id": handover.id,
        "batch_code": batch.code,
        "from_org_id": handover.from_org_id,
        "to_org_id": handover.to_org_id,
        "reject_reason": reason,
    }
    record_event(
        db=db,
        batch_id=batch.id,
        event_type=EVENT_HANDOVER_REJECT,
        payload=event_payload,
        org_id=handover.to_org_id,
        user_id=current_user.id,
    )

    record_action(db, current_user, "update", "handover", handover.id,
                  operation="handover_reject", batch_ids=[batch.id])
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể cập nhật từ chối bàn giao trong cơ sở dữ liệu.",
        ) from exc

    db.refresh(handover)
    return handover


# ==============================================================================
# 4. TƯƠNG THÍCH NGƯỢC: POST /handovers/{id}/respond
# ==============================================================================
@router.post(
    "/handovers/{handover_id}/respond",
    response_model=HandoverOut,
    status_code=status.HTTP_200_OK,
    summary="Phản hồi yêu cầu bàn giao (tương thích ngược)",
    include_in_schema=False,
)
@router.post(
    "/api/handovers/{handover_id}/respond",
    response_model=HandoverOut,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
def respond_handover_legacy(
    payload: HandoverRespond,
    handover_id: int = Path(..., ge=1),
    current_user: User = Depends(require_farmer),
    db: Session = Depends(get_db),
) -> Handover:
    """Tương thích ngược cho các test Sprint 1."""
    action = payload.action.strip().upper()
    if action == "ACCEPT":
        return accept_handover(handover_id=handover_id, current_user=current_user, db=db)
    elif action == "REJECT":
        req = HandoverRejectRequest(reject_reason=payload.reject_reason or "")
        return reject_handover(payload=req, handover_id=handover_id, current_user=current_user, db=db)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Hành động không hợp lệ.",
        )


# ==============================================================================
# 5. DANH SÁCH BÀN GIAO CHỜ XÁC NHẬN (T-38)
# ==============================================================================
@router.get(
    "/handovers/pending",
    response_model=list[HandoverOut],
    status_code=status.HTTP_200_OK,
    summary="Lấy danh sách bàn giao chờ xác nhận (T-38)",
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

    # Tự động quét và đánh dấu các bàn giao quá hạn 48h (T-56)
    check_overdue_handovers(db)

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


@router.post(
    "/handovers/check-overdue",
    summary="Quét và cập nhật cờ quá hạn 48 giờ cho các bàn giao (T-56)",
)
def run_check_overdue(
    current_user: User = Depends(require_farmer),
    db: Session = Depends(get_db),
) -> dict:
    """Kích hoạt tác vụ quét bàn giao quá hạn (T-56)."""
    _ = current_user
    count = check_overdue_handovers(db)
    return {"message": f"Đã quét và gắn cờ {count} yêu cầu bàn giao quá hạn 48h.", "overdue_count": count}


# ==============================================================================
# 6. DANH SÁCH & QUẢN LÝ TỔ CHỨC
# ==============================================================================
@router.get(
    "/organizations",
    response_model=list[OrganizationResponse],
    status_code=status.HTTP_200_OK,
    summary="Lấy danh sách tổ chức",
)
@router.get(
    "/api/organizations",
    response_model=list[OrganizationResponse],
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
def list_organizations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Organization]:
    """Danh sách các tổ chức trong hệ thống."""
    _ = current_user
    return list(db.scalars(select(Organization).order_by(Organization.id)).all())


@router.post(
    "/organizations",
    response_model=OrganizationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Tạo tổ chức mới (System Admin)",
)
def create_organization(
    payload: OrganizationCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Organization:
    """Tạo tổ chức mới, chỉ dành cho system_admin / admin."""
    if current_user.role not in (ROLE_SYSTEM_ADMIN, ROLE_ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chỉ quản trị hệ thống (system_admin) được phép tạo tổ chức mới.",
        )
    existing = db.scalar(select(Organization).where(Organization.code == payload.code))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Mã tổ chức '{payload.code}' đã tồn tại.",
        )
    org = Organization(name=payload.name, code=payload.code, description=payload.description)
    db.add(org)
    db.commit()
    db.refresh(org)
    record_action(db, current_user, "create", "organization", org.id)
    return org


# ==============================================================================
# 7. TƯƠNG THÍCH NGƯỢC: GET /api/batches/{batch_id}/events (SẮP XẾP MỚI NHẤT TRƯỚC)
# ==============================================================================
@router.get(
    "/api/batches/{batch_id}/events",
    response_model=list[BatchEventOut],
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
def list_batch_events_legacy_api(
    batch_id: int = Path(..., ge=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[BatchEventOut]:
    from app.routers.events import list_events_for_batch
    return list(reversed(list_events_for_batch(batch_id=batch_id, current_user=current_user, db=db)))
