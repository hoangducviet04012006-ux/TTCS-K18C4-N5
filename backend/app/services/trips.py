"""Dịch vụ nghiệp vụ Quản lý Chuyến xe lạnh (Cold Trips - S-40).

Đảm nhận:
- Quy tắc sinh mã chuyến tự động TRIP-YYYYMMDD-XXXX.
- Kiểm tra toàn diện điều kiện mở chuyến (sở hữu lô, trạng thái lô, thu hồi, trùng chuyến, trùng thùng).
- Ghi nhận sự kiện hash-chain TRIP_DISPATCH và TRIP_DELIVER cho từng lô trong cùng transaction.
- Hỗ trợ tra cứu chuyến đang chạy cho tích hợp cảm biến nhiệt độ S-41.
"""

import secrets
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.audit import record_action
from app.hash_chain import record_event
from app.models import (
    ACTION_CREATE,
    ACTION_UPDATE,
    ROLE_ADMIN,
    ROLE_INSPECTOR,
    ROLE_ORG_ADMIN,
    ROLE_SYSTEM_ADMIN,
    ROLE_TRANSPORTER,
    Batch,
    User,
)
from app.schemas_trips import (
    TripBatchItemResponse,
    TripCompleteRequest,
    TripCreate,
    TripDetailResponse,
    TripResponse,
)
from app.services.permissions import can_view_batch
from app.services.rbac import get_effective_role
from app.services.recall import ensure_not_recalled
from app.trip_models import (
    EVENT_TRIP_DELIVER,
    EVENT_TRIP_DISPATCH,
    TRIP_STATUS_CANCELLED,
    TRIP_STATUS_COMPLETED,
    TRIP_STATUS_IN_TRANSIT,
    ColdTrip,
    ColdTripBatch,
    _naive_utcnow,
)

# Ký tự an toàn sinh mã chuyến (tránh các ký tự dễ nhầm lẫn 0, O, 1, I)
TRIP_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def generate_trip_code(db: Session) -> str:
    """Sinh mã chuyến tự động định dạng TRIP-YYYYMMDD-XXXX."""
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    for _ in range(50):
        random_suffix = "".join(secrets.choice(TRIP_CODE_ALPHABET) for _ in range(4))
        code = f"TRIP-{date_part}-{random_suffix}"
        exists = db.scalar(select(ColdTrip.id).where(ColdTrip.trip_code == code).limit(1))
        if not exists:
            return code
    raise RuntimeError("Không thể sinh mã chuyến ngẫu nhiên duy nhất.")


def check_transporter_permission(user: User) -> None:
    """Kiểm tra quyền mở và thao tác chuyến vận chuyển."""
    role = get_effective_role(user)
    if role not in (ROLE_TRANSPORTER, ROLE_ORG_ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chỉ tài khoản đơn vị vận chuyển (transporter) hoặc quản trị tổ chức mới có quyền mở chuyến.",
        )
    if user.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tài khoản chưa được liên kết với tổ chức vận chuyển nào.",
        )


def find_active_trip_by_container(
    db: Session,
    container_code: str,
    user: User | None = None,
) -> ColdTrip | None:
    """Tìm chuyến xe đang chạy (IN_TRANSIT) của một thùng lạnh cụ thể (phục vụ S-41).

    Nếu cung cấp `user`, hàm sẽ kiểm tra phân quyền RBAC và phạm vi tổ chức (organization scope):
    - Đơn vị vận chuyển chỉ tra cứu được chuyến của tổ chức mình.
    - Inspector và Admin được tra cứu liên tổ chức.
    """
    clean_code = container_code.strip().upper()
    trip = db.scalar(
        select(ColdTrip)
        .options(
            joinedload(ColdTrip.trip_batches),
            joinedload(ColdTrip.transporter_org),
        )
        .where(
            ColdTrip.container_code == clean_code,
            ColdTrip.status == TRIP_STATUS_IN_TRANSIT,
        )
        .limit(1)
    )
    if trip is None:
        return None

    if user is not None:
        role = get_effective_role(user)
        if role not in (ROLE_INSPECTOR, ROLE_SYSTEM_ADMIN, ROLE_ADMIN):
            if user.organization_id is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Tài khoản chưa được liên kết với tổ chức.",
                )
            if trip.transporter_org_id != user.organization_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Bạn không có quyền tra cứu thông tin chuyến xe của tổ chức khác.",
                )

    return trip


def _validate_batch_for_trip(db: Session, user: User, batch_id: int) -> Batch:
    """Kiểm tra toàn diện điều kiện hợp lệ của lô nông sản trước khi gán vào chuyến xe."""
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy lô nông sản có id={batch_id}.",
        )

    # Chặn lô đang bị cách ly hoặc thu hồi (S-33 / Recall)
    ensure_not_recalled(db, batch.id)

    # Chặn lô không thuộc tổ chức đang trực tiếp nắm giữ
    if batch.current_org_id != user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Lô nông sản #{batch.code} thuộc tổ chức khác, bạn không có quyền mở chuyến.",
        )

    # Chặn lô không ở trạng thái hợp lệ
    if batch.status == "CONSUMED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Lô nông sản #{batch.code} đã tiêu thụ hết (CONSUMED), không thể đưa vào chuyến xe.",
        )
    if batch.status not in ("ACTIVE", "SPLIT") or not batch.remaining_quantity or batch.remaining_quantity <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Lô nông sản #{batch.code} ở trạng thái '{batch.status}' hoặc đã hết khối lượng.",
        )

    # Chặn lô đang có yêu cầu bàn giao chờ xác nhận (PENDING)
    if batch.pending_handover is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Lô nông sản #{batch.code} đang có yêu cầu bàn giao chờ duyệt, không thể đưa vào chuyến xe.",
        )

    # Ràng buộc S-16: Một lô không được nằm trong hai chuyến IN_TRANSIT đồng thời
    running_trip_for_batch = db.scalar(
        select(ColdTrip)
        .join(ColdTripBatch, ColdTripBatch.trip_id == ColdTrip.id)
        .where(
            ColdTripBatch.batch_id == batch.id,
            ColdTrip.status == TRIP_STATUS_IN_TRANSIT,
        )
        .limit(1)
    )
    if running_trip_for_batch is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Lô nông sản #{batch.code} hiện đang nằm trong một chuyến xe khác đang chạy "
                f"(mã chuyến: {running_trip_for_batch.trip_code})."
            ),
        )

    return batch


def create_cold_trip(db: Session, user: User, payload: TripCreate) -> ColdTrip:
    """Tạo mới chuyến vận chuyển chuỗi lạnh, gắn nhiều lô và 1 thùng lạnh (S-40)."""
    check_transporter_permission(user)

    container_code = payload.container_code.strip().upper()

    # 1. Ràng buộc: Một thùng lạnh không được nằm trong hai chuyến IN_TRANSIT đồng thời
    active_container_trip = find_active_trip_by_container(db, container_code)
    if active_container_trip is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Thùng lạnh '{container_code}' hiện đang trong hành trình của một chuyến xe khác "
                f"chưa kết thúc (mã chuyến: {active_container_trip.trip_code})."
            ),
        )

    # 2. Xử lý mã chuyến
    if payload.trip_code and payload.trip_code.strip():
        trip_code = payload.trip_code.strip().upper()
        existing = db.scalar(select(ColdTrip.id).where(ColdTrip.trip_code == trip_code).limit(1))
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Mã chuyến '{trip_code}' đã tồn tại trong hệ thống. Vui lòng chọn mã khác.",
            )
    else:
        trip_code = generate_trip_code(db)

    # 3. Kiểm tra tính hợp lệ của toàn bộ các lô được chọn
    target_batches: list[Batch] = [_validate_batch_for_trip(db, user, b_id) for b_id in payload.batch_ids]
    now_time = _naive_utcnow()

    # 4. Tạo bản ghi ColdTrip
    trip = ColdTrip(
        trip_code=trip_code,
        container_code=container_code,
        transporter_org_id=user.organization_id,
        status=TRIP_STATUS_IN_TRANSIT,
        driver_name=payload.driver_name.strip() if payload.driver_name else None,
        vehicle_plate=payload.vehicle_plate.strip() if payload.vehicle_plate else None,
        start_location=payload.start_location.strip() if payload.start_location else None,
        destination_location=payload.destination_location.strip() if payload.destination_location else None,
        start_time=now_time,
        notes=payload.notes.strip() if payload.notes else None,
        created_by_user_id=user.id,
        created_at=now_time,
        updated_at=now_time,
    )
    db.add(trip)
    db.flush()

    # 5. Gán các lô vào chuyến và ghi sự kiện hash-chain cho từng lô
    for batch in target_batches:
        trip_batch = ColdTripBatch(
            trip_id=trip.id,
            batch_id=batch.id,
            attached_at=now_time,
            notes=f"Lên xe chuyến {trip.trip_code} - Thùng {trip.container_code}",
        )
        db.add(trip_batch)

        # Ghi sự kiện TRIP_DISPATCH vào hash-chain bất biến của lô
        event_payload = {
            "trip_id": trip.id,
            "trip_code": trip.trip_code,
            "container_code": trip.container_code,
            "driver_name": trip.driver_name,
            "vehicle_plate": trip.vehicle_plate,
            "start_location": trip.start_location,
            "destination_location": trip.destination_location,
            "action": EVENT_TRIP_DISPATCH,
            "description": f"Lên xe khởi hành chuyến lạnh {trip.trip_code} (thùng: {trip.container_code})",
        }
        record_event(
            db=db,
            batch_id=batch.id,
            event_type=EVENT_TRIP_DISPATCH,
            payload=event_payload,
            org_id=user.organization_id,
            user_id=user.id,
            event_data=f"Khởi hành chuyến lạnh {trip.trip_code} (thùng: {trip.container_code})",
        )

    # 6. Ghi nhật ký thao tác (AuditLog)
    record_action(
        db,
        user,
        ACTION_CREATE,
        "cold_trip",
        trip.id,
        operation="TRIP_DISPATCH",
        batch_ids=[b.id for b in target_batches],
    )

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        err_msg = str(exc).lower()
        if "uq_cold_trips_active_container" in err_msg or "container_code" in err_msg:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Thùng lạnh '{trip.container_code}' hiện đang trong hành trình của một chuyến xe khác chưa kết thúc.",
            )
        if "uq_cold_trip_batches_active_batch" in err_msg or "batch_id" in err_msg:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Một trong các lô nông sản được chọn hiện đang nằm trong chuyến xe khác đang chạy.",
            )
        if "trip_code" in err_msg:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Mã chuyến '{trip.trip_code}' đã tồn tại trong hệ thống. Vui lòng chọn mã khác.",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ràng buộc dữ liệu chuyến xe không hợp lệ hoặc bị trùng lặp.",
        )

    db.refresh(trip)
    return trip


def complete_cold_trip(db: Session, user: User, trip_id: int, payload: TripCompleteRequest | None = None) -> ColdTrip:
    """Kết thúc chuyến vận chuyển chuỗi lạnh, hạ hàng / xuống xe (S-40)."""
    check_transporter_permission(user)

    trip = db.get(ColdTrip, trip_id)
    if trip is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy chuyến xe có id={trip_id}.",
        )

    role = get_effective_role(user)
    if role != ROLE_SYSTEM_ADMIN and trip.transporter_org_id != user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền kết thúc chuyến xe của tổ chức khác.",
        )

    if trip.status != TRIP_STATUS_IN_TRANSIT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Chuyến xe hiện đang ở trạng thái '{trip.status}', không thể kết thúc.",
        )

    end_time = _naive_utcnow()
    trip.status = TRIP_STATUS_COMPLETED
    trip.end_time = end_time
    trip.updated_at = end_time

    if payload and payload.notes:
        note_str = payload.notes.strip()
        trip.notes = f"{trip.notes or ''}\n[Hạ hàng]: {note_str}".strip()

    # Cập nhật thời điểm dỡ hàng và ghi sự kiện TRIP_DELIVER vào chuỗi của từng lô
    for tb in trip.trip_batches:
        tb.detached_at = end_time
        batch = db.get(Batch, tb.batch_id)
        if batch:
            event_payload = {
                "trip_id": trip.id,
                "trip_code": trip.trip_code,
                "container_code": trip.container_code,
                "destination_location": trip.destination_location,
                "action": EVENT_TRIP_DELIVER,
                "description": f"Hoàn thành chuyến lạnh {trip.trip_code}, dỡ hàng xuống xe an toàn",
            }
            record_event(
                db=db,
                batch_id=batch.id,
                event_type=EVENT_TRIP_DELIVER,
                payload=event_payload,
                org_id=user.organization_id,
                user_id=user.id,
                event_data=f"Hoàn thành chuyến lạnh {trip.trip_code}",
            )

    record_action(
        db,
        user,
        ACTION_UPDATE,
        "cold_trip",
        trip.id,
        operation="TRIP_DELIVER",
        batch_ids=[tb.batch_id for tb in trip.trip_batches],
    )

    db.commit()
    db.refresh(trip)
    return trip


def cancel_cold_trip(db: Session, user: User, trip_id: int, reason: str | None = None) -> ColdTrip:
    """Hủy chuyến xe lạnh và giải phóng các lô (S-40)."""
    check_transporter_permission(user)

    trip = db.get(ColdTrip, trip_id)
    if trip is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy chuyến xe có id={trip_id}.",
        )

    role = get_effective_role(user)
    if role != ROLE_SYSTEM_ADMIN and trip.transporter_org_id != user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền hủy chuyến xe của tổ chức khác.",
        )

    if trip.status != TRIP_STATUS_IN_TRANSIT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Chuyến xe hiện đang ở trạng thái '{trip.status}', không thể hủy.",
        )

    cancel_time = _naive_utcnow()
    trip.status = TRIP_STATUS_CANCELLED
    trip.end_time = cancel_time
    trip.updated_at = cancel_time
    if reason and reason.strip():
        trip.notes = f"{trip.notes or ''}\n[Hủy chuyến]: {reason.strip()}".strip()

    # Giải phóng các lô khỏi chuyến xe bằng cách đánh dấu thời điểm tách rời
    for tb in trip.trip_batches:
        tb.detached_at = cancel_time

    record_action(
        db,
        user,
        ACTION_UPDATE,
        "cold_trip",
        trip.id,
        operation="TRIP_CANCEL",
        batch_ids=[tb.batch_id for tb in trip.trip_batches],
    )

    db.commit()
    db.refresh(trip)
    return trip


def list_cold_trips(
    db: Session,
    user: User,
    status_filter: str | None = None,
    container_code: str | None = None,
    limit: int = 50,
    skip: int = 0,
) -> list[ColdTrip]:
    """Lấy danh sách các chuyến vận chuyển có phân quyền."""
    role = get_effective_role(user)

    stmt = select(ColdTrip).options(
        joinedload(ColdTrip.trip_batches),
        joinedload(ColdTrip.transporter_org),
    )

    # Phân quyền: Transporter & Org Admin chỉ xem chuyến của tổ chức mình;
    # Inspector & System Admin được xem toàn bộ liên tổ chức.
    if role not in (ROLE_INSPECTOR, ROLE_SYSTEM_ADMIN, ROLE_ADMIN):
        if user.organization_id is None:
            return []
        stmt = stmt.where(ColdTrip.transporter_org_id == user.organization_id)

    if status_filter:
        stmt = stmt.where(ColdTrip.status == status_filter.strip().upper())

    if container_code:
        stmt = stmt.where(ColdTrip.container_code == container_code.strip().upper())

    stmt = stmt.order_by(ColdTrip.created_at.desc()).offset(skip).limit(min(limit, 100))
    return list(db.scalars(stmt).unique().all())


def get_cold_trip_detail(db: Session, user: User, trip_id: int) -> ColdTrip:
    """Lấy chi tiết chuyến xe kèm danh sách các lô hàng."""
    role = get_effective_role(user)

    trip = db.scalar(
        select(ColdTrip)
        .options(
            joinedload(ColdTrip.trip_batches).joinedload(ColdTripBatch.batch).joinedload(Batch.product),
            joinedload(ColdTrip.transporter_org),
        )
        .where(ColdTrip.id == trip_id)
        .limit(1)
    )

    if trip is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy chuyến xe có id={trip_id}.",
        )

    # Kiểm tra quyền xem
    if role not in (ROLE_INSPECTOR, ROLE_SYSTEM_ADMIN, ROLE_ADMIN):
        if user.organization_id is None:
            raise HTTPException(status_code=403, detail="Tài khoản chưa được liên kết với tổ chức.")
        # Được xem nếu là tổ chức vận chuyển hoặc có lô liên quan theo phả hệ
        if trip.transporter_org_id != user.organization_id:
            # Kiểm tra xem tổ chức này có quyền xem ít nhất một lô trên chuyến không
            has_view_perm = any(
                can_view_batch(db, user.organization_id, tb.batch_id, role)
                for tb in trip.trip_batches
            )
            if not has_view_perm:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Bạn không có quyền truy cập thông tin chuyến xe của tổ chức khác.",
                )

    return trip


def build_trip_response(trip: ColdTrip) -> TripResponse:
    """Chuyển đổi ColdTrip ORM sang TripResponse schema."""
    return TripResponse(
        id=trip.id,
        trip_code=trip.trip_code,
        container_code=trip.container_code,
        transporter_org_id=trip.transporter_org_id,
        transporter_org_name=trip.transporter_org.name if trip.transporter_org else None,
        status=trip.status,
        driver_name=trip.driver_name,
        vehicle_plate=trip.vehicle_plate,
        start_location=trip.start_location,
        destination_location=trip.destination_location,
        start_time=trip.start_time,
        end_time=trip.end_time,
        notes=trip.notes,
        batch_count=len(trip.trip_batches),
        violation_count=len(trip.violations) if hasattr(trip, "violations") else 0,
        created_at=trip.created_at,
    )


def _build_batch_item(tb: ColdTripBatch, is_full_access: bool) -> TripBatchItemResponse:
    """Chuyển đổi ColdTripBatch ORM sang schema TripBatchItemResponse."""
    batch = tb.batch
    product_name = ""
    qty = 0.0
    unit = "kg"
    batch_code = ""

    if batch:
        batch_code = batch.code
        unit = batch.unit
        qty = float(batch.remaining_quantity or 0.0)
        if batch.product:
            product_name = batch.product.name
        elif batch.product_name:
            product_name = batch.product_name

    return TripBatchItemResponse(
        batch_id=tb.batch_id,
        batch_code=batch_code,
        product_name=product_name,
        quantity=qty,
        unit=unit,
        attached_at=tb.attached_at,
        detached_at=tb.detached_at,
        notes=tb.notes if is_full_access else None,
    )


def build_trip_detail_response(
    trip: ColdTrip,
    user: User | None = None,
    db: Session | None = None,
) -> TripDetailResponse:
    """Chuyển đổi ColdTrip ORM sang TripDetailResponse schema kèm phân quyền dữ liệu lô (S-40)."""
    is_full_access = True
    visible_trip_batches = list(trip.trip_batches)

    if user is not None and db is not None:
        role = get_effective_role(user)
        if (
            role not in (ROLE_INSPECTOR, ROLE_SYSTEM_ADMIN, ROLE_ADMIN)
            and trip.transporter_org_id != user.organization_id
        ):
            is_full_access = False
            visible_trip_batches = [
                tb for tb in trip.trip_batches
                if can_view_batch(db, user.organization_id, tb.batch_id, role)
            ]

    batch_items = [_build_batch_item(tb, is_full_access) for tb in visible_trip_batches]

    if not is_full_access:
        # Không tiết lộ thông tin tài xế, biển số, ghi chú nội bộ và tổng số lượng lô của tổ chức khác
        return TripDetailResponse(
            id=trip.id,
            trip_code=trip.trip_code,
            container_code=trip.container_code,
            transporter_org_id=trip.transporter_org_id,
            transporter_org_name=trip.transporter_org.name if trip.transporter_org else None,
            status=trip.status,
            driver_name=None,
            vehicle_plate=None,
            start_location=trip.start_location,
            destination_location=trip.destination_location,
            start_time=trip.start_time,
            end_time=trip.end_time,
            notes=None,
            batch_count=len(batch_items),
            created_at=trip.created_at,
            batches=batch_items,
        )

    base = build_trip_response(trip)
    return TripDetailResponse(
        **base.model_dump(),
        batches=batch_items,
    )
