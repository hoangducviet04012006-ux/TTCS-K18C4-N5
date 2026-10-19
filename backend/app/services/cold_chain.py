"""Dịch vụ giám sát Chuỗi lạnh & Xử lý Vi phạm Nhiệt độ (Cold Chain Monitoring - S-41, S-43, S-45).

Chức năng chính:
1. S-45: Khi phát hiện vi phạm nhiệt độ (vượt ngưỡng hoặc kéo dài trên 30 phút theo S-43):
   - Tự động ghi nhận sự kiện TEMPERATURE_VIOLATION vào Cryptographic Hash-Chain của mọi lô đang chở trên chuyến.
   - Cập nhật cờ cảnh báo `has_temperature_violation = True` và tăng `temperature_violation_count` trên từng lô.
   - Ghi nhật ký thao tác kiểm toán (AuditLog) cho cả chuyến và từng lô hàng.
   - Đảm bảo tính nhất quán dữ liệu, transaction nguyên tử (atomic commit / rollback).
2. S-41: Ghi nhận số đo cảm biến nhiệt độ từ IoT, tự động bỏ qua số đo cũ hơn hoặc trùng mốc thời gian.
3. S-43: Thuật toán cửa sổ trượt phát hiện vi phạm kéo dài >= 30 phút, gộp 2 lần vượt cách nhau < 5 phút.
"""

from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.audit import record_action
from app.hash_chain import record_event
from app.models import (
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
    BatchViolationSummary,
    TemperatureLogCreate,
    TemperatureViolationCreate,
    TemperatureViolationResponse,
)
from app.services.permissions import can_view_batch
from app.services.rbac import get_effective_role
from app.trip_models import (
    EVENT_TEMPERATURE_VIOLATION,
    TRIP_STATUS_IN_TRANSIT,
    ColdTrip,
    ColdTripBatch,
    TemperatureLog,
    TemperatureViolation,
    _naive_utcnow,
)


def _check_violation_recording_permission(user: User, trip: ColdTrip) -> None:
    """Kiểm tra quyền ghi nhận vi phạm nhiệt độ:

    - Transporter / Org Admin thuộc tổ chức vận chuyển của chuyến.
    - Inspector và System Admin (quyền thanh tra liên tổ chức).
    """
    role = get_effective_role(user)
    if role in (ROLE_INSPECTOR, ROLE_SYSTEM_ADMIN, ROLE_ADMIN):
        return
    if role in (ROLE_TRANSPORTER, ROLE_ORG_ADMIN):
        if user.organization_id is not None and user.organization_id == trip.transporter_org_id:
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền thao tác trên chuyến xe của tổ chức vận chuyển khác.",
        )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Chỉ đơn vị vận chuyển hoặc thanh tra viên mới có quyền ghi nhận vi phạm nhiệt độ.",
    )


def record_temperature_violation_for_trip(
    db: Session,
    trip_id: int,
    payload: TemperatureViolationCreate,
    user: User | None = None,
) -> TemperatureViolation:
    """Ghi nhận sự cố vi phạm nhiệt độ cho chuyến xe và tự động lan truyền vào chuỗi của mọi lô (S-45).

    Các bước xử lý trong một transaction duy nhất:
    1. Kiểm tra tồn tại chuyến xe và phân quyền người gọi.
    2. Xác định danh sách các lô hàng đang chở trên chuyến (các lô chưa dỡ `detached_at IS NULL`).
    3. Tạo bản ghi `TemperatureViolation` lưu trữ chi tiết sự cố (thời điểm, đỉnh, thời lượng).
    4. Duyệt qua từng lô hàng:
       - Ghi sự kiện `TEMPERATURE_VIOLATION` vào hash-chain bất biến của lô hàng (`BatchEvent`).
       - Cập nhật cờ `batch.has_temperature_violation = True` và tăng `batch.temperature_violation_count`.
       - Ghi nhật ký kiểm toán `AuditLog` cho từng lô.
    5. Ghi nhật ký kiểm toán cho chuyến xe `ColdTrip`.
    6. Commit nguyên tử (atomic commit), rollback toàn bộ nếu có bất kỳ lỗi nào.
    """
    trip = db.scalar(
        select(ColdTrip)
        .options(
            joinedload(ColdTrip.trip_batches).joinedload(ColdTripBatch.batch),
        )
        .where(ColdTrip.id == trip_id)
    )
    if trip is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy chuyến xe có id={trip_id}.",
        )

    if user is not None:
        _check_violation_recording_permission(user, trip)

    # Lấy danh sách các lô nông sản trên chuyến
    # Ưu tiên các lô đang trong hành trình (chưa dỡ). Nếu chuyến đã dỡ thì lấy toàn bộ lô trên chuyến.
    active_batches: list[Batch] = [
        tb.batch for tb in trip.trip_batches if tb.detached_at is None and tb.batch is not None
    ]
    if not active_batches:
        active_batches = [tb.batch for tb in trip.trip_batches if tb.batch is not None]

    # Xác định mức độ nghiêm trọng theo S-43 (kéo dài >= 30 phút là CRITICAL)
    severity = "CRITICAL" if payload.duration_minutes >= 30.0 else "WARNING"
    status_str = "RESOLVED" if payload.end_time else "ACTIVE"

    affected_batch_ids = [b.id for b in active_batches]

    now = _naive_utcnow()
    violation = TemperatureViolation(
        trip_id=trip.id,
        container_code=trip.container_code,
        start_time=payload.start_time,
        end_time=payload.end_time,
        duration_minutes=float(payload.duration_minutes),
        peak_temperature=float(payload.peak_temperature),
        threshold_temperature=float(payload.threshold_temperature),
        min_threshold=float(payload.min_threshold) if payload.min_threshold is not None else None,
        max_threshold=float(payload.max_threshold) if payload.max_threshold is not None else None,
        violation_type=payload.violation_type,
        severity=severity,
        status=status_str,
        affected_batch_ids=affected_batch_ids,
        notes=payload.notes,
        created_at=now,
        updated_at=now,
    )
    db.add(violation)
    db.flush()

    # Lan truyền sự kiện vi phạm vào Hash-Chain và cờ cảnh báo của TỪNG LÔ
    for batch in active_batches:
        event_payload = {
            "violation_id": violation.id,
            "trip_id": trip.id,
            "trip_code": trip.trip_code,
            "container_code": trip.container_code,
            "start_time": violation.start_time.isoformat(),
            "end_time": violation.end_time.isoformat() if violation.end_time else None,
            "duration_minutes": round(violation.duration_minutes, 2),
            "peak_temperature": round(violation.peak_temperature, 2),
            "threshold_temperature": round(violation.threshold_temperature, 2),
            "min_threshold": violation.min_threshold,
            "max_threshold": violation.max_threshold,
            "violation_type": violation.violation_type,
            "severity": violation.severity,
            "status": violation.status,
            "action": EVENT_TEMPERATURE_VIOLATION,
            "description": (
                f"Cảnh báo vi phạm nhiệt độ: Đỉnh {violation.peak_temperature}°C "
                f"(ngưỡng {violation.threshold_temperature}°C), kéo dài {round(violation.duration_minutes, 1)} phút "
                f"trên chuyến {trip.trip_code} (thùng: {trip.container_code})"
            ),
        }

        # 1. Ghi vào Cryptographic Hash-Chain bất biến
        record_event(
            db=db,
            batch_id=batch.id,
            event_type=EVENT_TEMPERATURE_VIOLATION,
            payload=event_payload,
            org_id=batch.current_org_id,
            user_id=user.id if user else (trip.created_by_user_id or 1),
            event_data=event_payload["description"],
        )

        # 2. Cập nhật cờ cảnh báo và bộ đếm trên model Batch
        batch.has_temperature_violation = True
        batch.temperature_violation_count = (batch.temperature_violation_count or 0) + 1

        # 3. Ghi AuditLog lịch sử thao tác cho lô
        if user is not None:
            record_action(
                db,
                user,
                ACTION_UPDATE,
                "batch",
                batch.id,
                operation="TEMPERATURE_VIOLATION",
                batch_ids=[batch.id],
            )

    # 4. Ghi AuditLog lịch sử thao tác cho chuyến xe
    if user is not None:
        record_action(
            db,
            user,
            ACTION_UPDATE,
            "cold_trip",
            trip.id,
            operation="TEMPERATURE_VIOLATION",
            batch_ids=affected_batch_ids,
        )

    db.commit()
    db.refresh(violation)
    return violation


def record_temperature_violation_for_batch(
    db: Session,
    batch_id: int,
    payload: TemperatureViolationCreate,
    user: User | None = None,
) -> TemperatureViolation:
    """Ghi nhận sự cố vi phạm nhiệt độ trực tiếp cho một lô hàng cụ thể (S-45).

    Sử dụng khi phát hiện vi phạm tại kho bảo quản hoặc đợt kiểm tra chất lượng riêng lẻ của lô.
    """
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy lô nông sản có id={batch_id}.",
        )

    if user is not None:
        role = get_effective_role(user)
        if role not in (ROLE_INSPECTOR, ROLE_SYSTEM_ADMIN, ROLE_ADMIN):
            if user.organization_id is None or user.organization_id != batch.current_org_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Bạn không có quyền ghi nhận vi phạm cho lô nông sản thuộc tổ chức khác.",
                )

    severity = "CRITICAL" if payload.duration_minutes >= 30.0 else "WARNING"
    status_str = "RESOLVED" if payload.end_time else "ACTIVE"
    now = _naive_utcnow()

    violation = TemperatureViolation(
        trip_id=None,
        batch_id=batch.id,
        container_code=None,
        start_time=payload.start_time,
        end_time=payload.end_time,
        duration_minutes=float(payload.duration_minutes),
        peak_temperature=float(payload.peak_temperature),
        threshold_temperature=float(payload.threshold_temperature),
        min_threshold=float(payload.min_threshold) if payload.min_threshold is not None else None,
        max_threshold=float(payload.max_threshold) if payload.max_threshold is not None else None,
        violation_type=payload.violation_type,
        severity=severity,
        status=status_str,
        affected_batch_ids=[batch.id],
        notes=payload.notes,
        created_at=now,
        updated_at=now,
    )
    db.add(violation)
    db.flush()

    # Ghi nhận vào hash chain của lô
    event_payload = {
        "violation_id": violation.id,
        "batch_id": batch.id,
        "batch_code": batch.code,
        "start_time": violation.start_time.isoformat(),
        "end_time": violation.end_time.isoformat() if violation.end_time else None,
        "duration_minutes": round(violation.duration_minutes, 2),
        "peak_temperature": round(violation.peak_temperature, 2),
        "threshold_temperature": round(violation.threshold_temperature, 2),
        "min_threshold": violation.min_threshold,
        "max_threshold": violation.max_threshold,
        "violation_type": violation.violation_type,
        "severity": violation.severity,
        "status": violation.status,
        "action": EVENT_TEMPERATURE_VIOLATION,
        "description": (
            f"Cảnh báo vi phạm nhiệt độ bảo quản lô #{batch.code}: Đỉnh {violation.peak_temperature}°C "
            f"(ngưỡng {violation.threshold_temperature}°C), kéo dài {round(violation.duration_minutes, 1)} phút."
        ),
    }

    record_event(
        db=db,
        batch_id=batch.id,
        event_type=EVENT_TEMPERATURE_VIOLATION,
        payload=event_payload,
        org_id=batch.current_org_id,
        user_id=user.id if user else 1,
        event_data=event_payload["description"],
    )

    batch.has_temperature_violation = True
    batch.temperature_violation_count = (batch.temperature_violation_count or 0) + 1

    if user is not None:
        record_action(
            db,
            user,
            ACTION_UPDATE,
            "batch",
            batch.id,
            operation="TEMPERATURE_VIOLATION",
            batch_ids=[batch.id],
        )

    db.commit()
    db.refresh(violation)
    return violation


def record_temperature_reading(
    db: Session,
    container_code: str,
    payload: TemperatureLogCreate,
    user: User | None = None,
) -> TemperatureLog:
    """Ghi nhận số đo nhiệt độ cảm biến theo thời gian cho chuyến xe (S-41).

    Quy tắc S-41:
    - Lưu theo chuyến đang chạy (IN_TRANSIT) của container_code.
    - Số đo có mốc thời gian cũ hơn số đã lưu hoặc trùng thì bỏ qua và trả về đã nhận.
    """
    clean_code = container_code.strip().upper()
    trip = db.scalar(
        select(ColdTrip).where(
            ColdTrip.container_code == clean_code,
            ColdTrip.status == TRIP_STATUS_IN_TRANSIT,
        ).limit(1)
    )
    if trip is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy chuyến xe nào đang chạy (IN_TRANSIT) với thùng lạnh '{clean_code}'.",
        )

    if user is not None:
        _check_violation_recording_permission(user, trip)

    rec_time = payload.recorded_at or _naive_utcnow()

    # Kiểm tra số đo cũ hơn hoặc trùng thời gian (S-41)
    latest_reading = db.scalar(
        select(TemperatureLog)
        .where(
            TemperatureLog.trip_id == trip.id,
            TemperatureLog.recorded_at >= rec_time,
        )
        .order_by(TemperatureLog.recorded_at.desc())
        .limit(1)
    )
    if latest_reading is not None and rec_time <= latest_reading.recorded_at:
        # Bỏ qua không lưu trùng và trả về số đo hợp lệ đã nhận
        return latest_reading

    log = TemperatureLog(
        trip_id=trip.id,
        container_code=trip.container_code,
        temperature=float(payload.temperature),
        recorded_at=rec_time,
        created_at=_naive_utcnow(),
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def detect_violations_from_readings(
    readings: list[tuple[datetime, float]],
    threshold_max: float = 8.0,
    threshold_min: float | None = 2.0,
    min_duration_minutes: float = 30.0,
    gap_merge_minutes: float = 5.0,
) -> list[dict[str, Any]]:
    """Thuật toán phát hiện sự cố vi phạm nhiệt độ theo tiêu chuẩn S-43:

    Quy tắc nghiệp vụ S-43:
    1. Nhiệt độ vượt ngưỡng liên tục quá 30 phút thì sinh một vi phạm ghi rõ bắt đầu, kết thúc, đỉnh.
    2. Vượt ngắn rồi trở lại (dưới 30 phút) thì không tính là vi phạm.
    3. Hai lần vượt cách nhau dưới 5 phút tính là một vi phạm liên tục (gộp).
    4. Hai lần vượt cách xa nhau (>= 5 phút) tính là hai vi phạm độc lập.
    """
    if not readings or len(readings) < 2:
        return []

    # Sắp xếp chuỗi thời gian tăng dần
    sorted_readings = sorted(readings, key=lambda x: x[0])

    # Bước 1: Tìm các điểm vượt ngưỡng
    raw_breaches: list[list[tuple[datetime, float]]] = []
    current_burst: list[tuple[datetime, float]] = []

    for t_time, temp in sorted_readings:
        is_breach = temp > threshold_max or (threshold_min is not None and temp < threshold_min)
        if is_breach:
            current_burst.append((t_time, temp))
        else:
            if current_burst:
                raw_breaches.append(current_burst)
                current_burst = []
    if current_burst:
        raw_breaches.append(current_burst)

    if not raw_breaches:
        return []

    # Bước 2: Gộp các đợt vượt ngưỡng có khoảng cách nghỉ < 5 phút (gap_merge_minutes)
    merged_breaches: list[list[tuple[datetime, float]]] = [raw_breaches[0]]
    for next_burst in raw_breaches[1:]:
        prev_burst = merged_breaches[-1]
        prev_end = prev_burst[-1][0]
        next_start = next_burst[0][0]
        gap_mins = (next_start - prev_end).total_seconds() / 60.0

        if gap_mins < gap_merge_minutes:
            # Gộp hai lần vượt cách nhau dưới 5 phút làm một
            merged_breaches[-1] = prev_burst + next_burst
        else:
            # Cách xa hơn tính là hai đợt riêng biệt
            merged_breaches.append(next_burst)

    # Bước 3: Lọc các đợt vi phạm kéo dài >= 30 phút (min_duration_minutes)
    detected_violations: list[dict[str, Any]] = []
    for burst in merged_breaches:
        start_time = burst[0][0]
        end_time = burst[-1][0]
        duration_minutes = (end_time - start_time).total_seconds() / 60.0

        if duration_minutes >= min_duration_minutes:
            # Tính nhiệt độ đỉnh (peak)
            peak_temp = max(temp for _, temp in burst)
            detected_violations.append({
                "start_time": start_time,
                "end_time": end_time,
                "duration_minutes": duration_minutes,
                "peak_temperature": peak_temp,
                "threshold_temperature": threshold_max,
                "min_threshold": threshold_min,
                "max_threshold": threshold_max,
                "violation_type": "PROLONGED_HEAT" if peak_temp > threshold_max else "FREEZING_RISK",
            })

    return detected_violations


def list_trip_violations(
    db: Session,
    trip_id: int,
    user: User | None = None,
) -> list[TemperatureViolation]:
    """Lấy danh sách các sự cố vi phạm nhiệt độ của một chuyến xe."""
    trip = db.get(ColdTrip, trip_id)
    if trip is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy chuyến xe có id={trip_id}.",
        )

    if user is not None:
        role = get_effective_role(user)
        if role not in (ROLE_INSPECTOR, ROLE_SYSTEM_ADMIN, ROLE_ADMIN):
            if user.organization_id is None or user.organization_id != trip.transporter_org_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Bạn không có quyền xem vi phạm của chuyến xe thuộc tổ chức khác.",
                )

    return list(
        db.scalars(
            select(TemperatureViolation)
            .where(TemperatureViolation.trip_id == trip_id)
            .order_by(TemperatureViolation.start_time.asc())
        ).all()
    )


def list_batch_violations(
    db: Session,
    batch_id: int,
    user: User | None = None,
) -> list[TemperatureViolation]:
    """Lấy danh sách các sự cố vi phạm nhiệt độ từng xảy ra trên lô hàng (S-45)."""
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy lô nông sản có id={batch_id}.",
        )

    if user is not None:
        if not can_view_batch(db, user.organization_id, batch_id, user_role=user.role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Bạn không có quyền xem thông tin lô nông sản này.",
            )

    # Tìm các vi phạm gắn trực tiếp với batch_id hoặc qua chuyến xe chứa lô
    # Đồng thời quét các chuyến xe mà lô từng tham gia
    trip_ids = list(
        db.scalars(
            select(ColdTripBatch.trip_id).where(ColdTripBatch.batch_id == batch_id)
        ).all()
    )

    query = select(TemperatureViolation).where(
        (TemperatureViolation.batch_id == batch_id) |
        (TemperatureViolation.trip_id.in_(trip_ids) if trip_ids else False)
    ).order_by(TemperatureViolation.start_time.asc())

    return list(db.scalars(query).all())


def get_batch_violation_summary(
    db: Session,
    batch_id: int,
    user: User | None = None,
) -> BatchViolationSummary:
    """Trả về tóm tắt thông tin vi phạm nhiệt độ phục vụ kiểm tra trước khi bàn giao (S-45)."""
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy lô nông sản có id={batch_id}.",
        )

    violations = list_batch_violations(db, batch_id, user=user)
    has_violation = bool(batch.has_temperature_violation or len(violations) > 0)
    count = max(batch.temperature_violation_count or 0, len(violations))

    return BatchViolationSummary(
        batch_id=batch.id,
        batch_code=batch.code,
        has_violation=has_violation,
        violation_count=count,
        violations=[
            TemperatureViolationResponse(
                id=v.id,
                trip_id=v.trip_id,
                batch_id=v.batch_id,
                container_code=v.container_code,
                start_time=v.start_time,
                end_time=v.end_time,
                duration_minutes=v.duration_minutes,
                peak_temperature=v.peak_temperature,
                threshold_temperature=v.threshold_temperature,
                min_threshold=v.min_threshold,
                max_threshold=v.max_threshold,
                violation_type=v.violation_type,
                severity=v.severity,
                status=v.status,
                affected_batch_ids=v.affected_batch_ids or [],
                notes=v.notes,
                created_at=v.created_at,
                updated_at=v.updated_at,
            )
            for v in violations
        ],
    )


def list_trip_readings(
    db: Session,
    trip_id: int,
    limit: int = 200,
    user: User | None = None,
) -> list[TemperatureLog]:
    """Lấy danh sách số đo nhiệt độ đã lưu của chuyến xe (S-41)."""
    trip = db.get(ColdTrip, trip_id)
    if trip is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy chuyến xe có id={trip_id}.",
        )

    if user is not None:
        role = get_effective_role(user)
        if role not in (ROLE_INSPECTOR, ROLE_SYSTEM_ADMIN, ROLE_ADMIN):
            if user.organization_id is None or user.organization_id != trip.transporter_org_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Bạn không có quyền xem dữ liệu cảm biến của tổ chức khác.",
                )

    return list(
        db.scalars(
            select(TemperatureLog)
            .where(TemperatureLog.trip_id == trip_id)
            .order_by(TemperatureLog.recorded_at.asc())
            .limit(limit)
        ).all()
    )
