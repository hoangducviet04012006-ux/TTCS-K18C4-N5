"""Dịch vụ giám sát chuỗi lạnh và xử lý vi phạm nhiệt độ (Sprint Epic E-07 / User Story S-45).

Nhiệm vụ chính:
1. Phát hiện sự cố vi phạm nhiệt độ theo tiêu chuẩn S-43 (vượt ngưỡng liên tục > 30 phút,
   gộp 2 lần vượt cách nhau < 5 phút).
2. Tự động ghi nhận sự kiện vi phạm vào Hash-Chain bất biến của từng lô hàng tương ứng (S-45).
3. Gắn cờ cảnh báo (warning flag / has_temperature_violation) vào lô nông sản và chuỗi khối.
4. Ghi nhận dấu vết kiểm toán vào AuditLog của hệ thống (S-07 / T-14).
5. Quản lý chuyến vận chuyển lạnh (Shipment - S-40) và ghi nhận vi phạm cho mọi lô trên chuyến.
"""

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record_action
from app.hash_chain import record_event
from app.models import (
    ACTION_UPDATE,
    COLD_CHAIN_NORMAL,
    COLD_CHAIN_VIOLATED,
    COLD_CHAIN_WARNING,
    ENTITY_BATCH,
    EVENT_TEMPERATURE_VIOLATION,
    SHIPMENT_STATUS_IN_TRANSIT,
    Batch,
    Organization,
    Shipment,
    ShipmentBatch,
    TemperatureViolation,
    User,
    _naive_utcnow,
)
from app.schemas import (
    BatchColdChainStatusResponse,
    ShipmentCreate,
    ShipmentOut,
    TemperatureReadingItem,
    TemperatureStreamProcessRequest,
    TemperatureStreamProcessResponse,
    TemperatureViolationCreate,
    TemperatureViolationOut,
)


def _get_system_or_actor_user(db: Session, current_user: User | None = None) -> User:
    """Lấy tài khoản người thực hiện hoặc tài khoản quản trị hệ thống mặc định."""
    if current_user is not None:
        return current_user
    # Lấy tài khoản admin hoặc user đầu tiên nếu là tiến trình nền/IoT tự động
    user = db.scalar(select(User).order_by(User.id.asc()).limit(1))
    if user is None:
        # Tạo tạm user ảo nếu db test hoàn toàn trống
        user = User(
            id=1,
            username="system_coldchain",
            role="system_admin",
            password="",
            organization_id=1,
        )
    return user


def detect_s43_violations(
    readings: list[TemperatureReadingItem],
    min_threshold: float = 2.0,
    max_threshold: float = 8.0,
    latency_minutes: int = 30,
    gap_tolerance_minutes: int = 5,
) -> list[dict[str, Any]]:
    """Thuật toán phát hiện vi phạm nhiệt độ theo tiêu chuẩn User Story S-43.

    Quy tắc nghiệp vụ:
    - Nhiệt độ vượt ngưỡng cho phép (< min_threshold hoặc > max_threshold) liên tục quá 30 phút
      mới sinh một vi phạm (tránh báo động giả khi chỉ mở cửa xe vài phút).
    - Vượt ngắn rồi trở lại trong ngưỡng thì không tính là vi phạm.
    - Hai lần vượt cách nhau dưới 5 phút (<= 5 phút) tính là một lần vi phạm liên tục kéo dài.
    - Hai lần vượt cách xa hơn 5 phút (> 5 phút) tính là hai vi phạm riêng biệt.
    - Ghi nhận đầy đủ: bắt đầu (start_time), kết thúc (end_time), đỉnh vi phạm (peak_temperature),
      thời lượng (duration_minutes).
    """
    if not readings:
        return []

    # 1. Sắp xếp theo mốc thời gian tăng dần và loại bỏ trùng lặp / mốc cũ (S-41)
    sorted_readings: list[TemperatureReadingItem] = []
    seen_timestamps: set[datetime] = set()

    for item in sorted(readings, key=lambda r: r.timestamp):
        # Chuẩn hóa về datetime naive UTC để tính toán đồng nhất
        ts = item.timestamp.replace(tzinfo=None) if item.timestamp.tzinfo else item.timestamp
        if ts not in seen_timestamps:
            seen_timestamps.add(ts)
            sorted_readings.append(
                TemperatureReadingItem(
                    temperature=item.temperature,
                    timestamp=ts,
                    sensor_id=item.sensor_id,
                )
            )

    if not sorted_readings:
        return []

    violations: list[dict[str, Any]] = []

    # Cấu trúc một đợt vượt ngưỡng đang theo dõi
    current_episode: dict[str, Any] | None = None

    def is_exceeded(temp: float) -> bool:
        return temp < min_threshold or temp > max_threshold

    def calculate_peak(current_peak: float, new_temp: float) -> float:
        if new_temp > max_threshold:
            return max(current_peak, new_temp)
        elif new_temp < min_threshold:
            return min(current_peak, new_temp)
        return current_peak

    for reading in sorted_readings:
        temp = reading.temperature
        ts = reading.timestamp

        if is_exceeded(temp):
            if current_episode is None:
                # Bắt đầu đợt vượt ngưỡng mới
                current_episode = {
                    "start_time": ts,
                    "end_time": ts,
                    "last_exceeded_time": ts,
                    "peak_temperature": temp,
                    "is_in_normal_gap": False,
                }
            else:
                if current_episode["is_in_normal_gap"]:
                    # Đang trong khoảng nghỉ tạm thời: kiểm tra độ dài khoảng bình thường
                    gap_mins = (ts - current_episode["last_exceeded_time"]).total_seconds() / 60.0
                    if gap_mins <= gap_tolerance_minutes:
                        # Khoảng cách <= 5 phút -> Gộp làm một đợt kéo dài liên tục
                        current_episode["end_time"] = ts
                        current_episode["last_exceeded_time"] = ts
                        current_episode["is_in_normal_gap"] = False
                        current_episode["peak_temperature"] = calculate_peak(
                            current_episode["peak_temperature"], temp
                        )
                    else:
                        # Khoảng cách > 5 phút -> Chốt đợt cũ, mở đợt mới (tính làm hai vi phạm riêng)
                        dur_mins = (
                            current_episode["end_time"] - current_episode["start_time"]
                        ).total_seconds() / 60.0
                        if dur_mins >= latency_minutes:
                            violations.append({
                                "start_time": current_episode["start_time"],
                                "end_time": current_episode["end_time"],
                                "duration_minutes": int(round(dur_mins)),
                                "peak_temperature": current_episode["peak_temperature"],
                                "recorded_temperature": current_episode["peak_temperature"],
                                "min_threshold": min_threshold,
                                "max_threshold": max_threshold,
                            })
                        # Khởi tạo đợt mới
                        current_episode = {
                            "start_time": ts,
                            "end_time": ts,
                            "last_exceeded_time": ts,
                            "peak_temperature": temp,
                            "is_in_normal_gap": False,
                        }
                else:
                    # Cả 2 số đo liên tiếp đều vượt ngưỡng -> Chuỗi vượt ngưỡng liên tục
                    current_episode["end_time"] = ts
                    current_episode["last_exceeded_time"] = ts
                    current_episode["peak_temperature"] = calculate_peak(
                        current_episode["peak_temperature"], temp
                    )
        else:
            # Số đo trong ngưỡng bình thường
            if current_episode is not None:
                if not current_episode["is_in_normal_gap"]:
                    current_episode["is_in_normal_gap"] = True

                gap_mins = (ts - current_episode["last_exceeded_time"]).total_seconds() / 60.0
                if gap_mins > gap_tolerance_minutes:
                    # Khoảng cách bình thường đã vượt quá 5 phút -> Chốt đóng đợt cũ
                    dur_mins = (
                        current_episode["end_time"] - current_episode["start_time"]
                    ).total_seconds() / 60.0
                    if dur_mins >= latency_minutes:
                        violations.append({
                            "start_time": current_episode["start_time"],
                            "end_time": current_episode["end_time"],
                            "duration_minutes": int(round(dur_mins)),
                            "peak_temperature": current_episode["peak_temperature"],
                            "recorded_temperature": current_episode["peak_temperature"],
                            "min_threshold": min_threshold,
                            "max_threshold": max_threshold,
                        })
                    current_episode = None

    # Kiểm tra đợt cuối cùng khi duyệt xong toàn bộ số đo
    if current_episode is not None:
        dur_mins = (
            current_episode["end_time"] - current_episode["start_time"]
        ).total_seconds() / 60.0
        if dur_mins >= latency_minutes:
            violations.append({
                "start_time": current_episode["start_time"],
                "end_time": current_episode["end_time"],
                "duration_minutes": int(round(dur_mins)),
                "peak_temperature": current_episode["peak_temperature"],
                "recorded_temperature": current_episode["peak_temperature"],
                "min_threshold": min_threshold,
                "max_threshold": max_threshold,
            })

    return violations


def record_temperature_violation(
    db: Session,
    payload: TemperatureViolationCreate,
    current_user: User | None = None,
) -> list[TemperatureViolationOut]:
    """Tiến trình cốt lõi ghi nhận sự kiện vi phạm nhiệt độ vào nhật ký và Hash-Chain (S-45).

    Chức năng:
    1. Xác thực lô hàng (batch_id) hoặc chuyến vận chuyển (shipment_id).
    2. Nếu có shipment_id: tự động áp dụng và ghi nhận sự kiện vào chuỗi của TẤT CẢ các lô
       đang chở trên chuyến đó ("sự kiện vi phạm được ghi vào chuỗi của mọi lô đang trên chuyến").
    3. Ghi sự kiện append-only vào Hash-Chain (BatchEvent) với mã băm SHA-256 bảo đảm tính toàn vẹn.
    4. Cập nhật trạng thái lô hàng (cold_chain_status = 'VIOLATED') và gắn cờ has_temperature_violation = True.
    5. Lưu bản ghi sự cố TemperatureViolation liên kết với BatchEvent.
    6. Tự động ghi nhật ký kiểm toán hệ thống (AuditLog) qua record_action.
    7. Cam kết dữ liệu atomic, an toàn giao dịch và nhất quán.
    """
    if not payload.batch_id and not payload.shipment_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bắt buộc phải cung cấp ít nhất batch_id (lô hàng) hoặc shipment_id (chuyến vận chuyển).",
        )

    actor = _get_system_or_actor_user(db, current_user)
    batches_to_process: list[Batch] = []
    shipment: Shipment | None = None

    # Trường hợp 1: Có shipment_id -> Lấy toàn bộ các lô trên chuyến
    if payload.shipment_id:
        shipment = db.get(Shipment, payload.shipment_id)
        if shipment is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Không tìm thấy chuyến vận chuyển lạnh có id={payload.shipment_id}.",
            )
        batches_to_process = list(shipment.batches)
        if not batches_to_process:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Chuyến vận chuyển mã '{shipment.code}' hiện không có lô hàng nào.",
            )

    # Trường hợp 2: Có batch_id đơn lẻ
    if payload.batch_id:
        batch = db.get(Batch, payload.batch_id)
        if batch is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Không tìm thấy lô nông sản có id={payload.batch_id}.",
            )
        if batch not in batches_to_process:
            batches_to_process.append(batch)

    now = _naive_utcnow()
    start_dt = payload.start_time or now
    if start_dt.tzinfo:
        start_dt = start_dt.replace(tzinfo=None)
    end_dt = payload.end_time
    if end_dt and end_dt.tzinfo:
        end_dt = end_dt.replace(tzinfo=None)

    peak_temp = payload.peak_temperature if payload.peak_temperature is not None else payload.recorded_temperature
    duration = payload.duration_minutes
    if duration is None and end_dt:
        duration = max(0, int((end_dt - start_dt).total_seconds() / 60.0))

    violation_outputs: list[TemperatureViolationOut] = []

    # Xử lý ghi nhận cho từng lô hàng trong cùng một giao dịch (Transaction)
    for batch in batches_to_process:
        # 1. Cập nhật trạng thái lô hàng & gắn cờ cảnh báo sự cố vi phạm
        batch.has_temperature_violation = True
        batch.cold_chain_status = (
            COLD_CHAIN_VIOLATED if payload.severity.upper() == "CRITICAL" else COLD_CHAIN_WARNING
        )

        # 2. Xây dựng payload sự kiện vi phạm nhiệt độ chi tiết
        threshold_info = ""
        if payload.min_threshold is not None and payload.max_threshold is not None:
            threshold_info = f" ({payload.min_threshold}°C - {payload.max_threshold}°C)"

        description = (
            payload.notes
            or f"Cảnh báo vi phạm nhiệt độ chuỗi lạnh: ghi nhận {payload.recorded_temperature}°C"
            f"{threshold_info}, đỉnh {peak_temp}°C, thời lượng {duration or 0} phút."
        )

        event_payload: dict[str, Any] = {
            "batch_id": batch.id,
            "batch_code": batch.code,
            "event_type": EVENT_TEMPERATURE_VIOLATION,
            "recorded_temperature": payload.recorded_temperature,
            "min_threshold": payload.min_threshold,
            "max_threshold": payload.max_threshold,
            "threshold_min": payload.min_threshold,
            "threshold_max": payload.max_threshold,
            "peak_temperature": peak_temp,
            "duration_minutes": duration,
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat() if end_dt else None,
            "severity": payload.severity.upper(),
            "warning_flag": payload.warning_flag,
            "has_temperature_violation": True,
            "cold_chain_status": batch.cold_chain_status,
            "sensor_id": payload.sensor_id,
            "container_code": payload.container_code or (shipment.container_code if shipment else None),
            "shipment_id": shipment.id if shipment else None,
            "shipment_code": shipment.code if shipment else None,
            "description": description,
        }

        # 3. Ghi vào Hash-Chain bất biến của lô hàng (append-only)
        effective_org_id = batch.current_org_id or actor.organization_id or 1
        event = record_event(
            db=db,
            batch_id=batch.id,
            event_type=EVENT_TEMPERATURE_VIOLATION,
            payload=event_payload,
            org_id=effective_org_id,
            user_id=actor.id,
            event_data=description,
            from_org_id=effective_org_id,
            notes=description,
        )

        # 4. Tạo bản ghi TemperatureViolation chi tiết liên kết với sự kiện
        violation_rec = TemperatureViolation(
            batch_id=batch.id,
            shipment_id=shipment.id if shipment else None,
            recorded_temperature=payload.recorded_temperature,
            min_threshold=payload.min_threshold,
            max_threshold=payload.max_threshold,
            peak_temperature=peak_temp,
            duration_minutes=duration,
            start_time=start_dt,
            end_time=end_dt,
            severity=payload.severity.upper(),
            warning_flag=payload.warning_flag,
            event_id=event.id,
            resolved=False,
            notes=payload.notes,
            created_at=now,
        )
        db.add(violation_rec)
        db.flush()

        # 5. Ghi vào nhật ký kiểm toán hệ thống (AuditLog)
        record_action(
            db=db,
            user=actor,
            action=ACTION_UPDATE,
            entity=ENTITY_BATCH,
            entity_id=batch.id,
            operation="temperature_violation",
            batch_ids=[batch.id],
        )

        violation_outputs.append(
            TemperatureViolationOut(
                id=violation_rec.id,
                batch_id=batch.id,
                batch_code=batch.code,
                shipment_id=violation_rec.shipment_id,
                recorded_temperature=violation_rec.recorded_temperature,
                min_threshold=violation_rec.min_threshold,
                max_threshold=violation_rec.max_threshold,
                peak_temperature=violation_rec.peak_temperature,
                duration_minutes=violation_rec.duration_minutes,
                start_time=violation_rec.start_time,
                end_time=violation_rec.end_time,
                severity=violation_rec.severity,
                warning_flag=violation_rec.warning_flag,
                event_id=event.id,
                event_hash=event.current_hash,
                resolved=violation_rec.resolved,
                notes=violation_rec.notes,
                created_at=violation_rec.created_at,
            )
        )

    db.commit()
    return violation_outputs


def process_reading_stream_and_record(
    db: Session,
    request: TemperatureStreamProcessRequest,
    current_user: User | None = None,
) -> TemperatureStreamProcessResponse:
    """Xử lý luồng số đo cảm biến (S-41, S-42), phát hiện vi phạm theo S-43 và tự động ghi sự kiện S-45."""
    if not request.readings:
        return TemperatureStreamProcessResponse(
            total_readings=0,
            violations_detected=0,
            violations=[],
            message="Không có dữ liệu số đo nào để phân tích.",
        )

    # 1. Phát hiện vi phạm theo thuật toán S-43
    detected_violations = detect_s43_violations(
        readings=request.readings,
        min_threshold=request.min_threshold,
        max_threshold=request.max_threshold,
        latency_minutes=request.latency_minutes,
        gap_tolerance_minutes=request.gap_tolerance_minutes,
    )

    recorded_outputs: list[TemperatureViolationOut] = []

    # 2. Tự động ghi nhận từng sự cố vi phạm vào nhật ký và Hash-Chain (S-45)
    for v_info in detected_violations:
        create_payload = TemperatureViolationCreate(
            batch_id=request.batch_id,
            shipment_id=request.shipment_id,
            recorded_temperature=v_info["recorded_temperature"],
            min_threshold=v_info["min_threshold"],
            max_threshold=v_info["max_threshold"],
            peak_temperature=v_info["peak_temperature"],
            duration_minutes=v_info["duration_minutes"],
            start_time=v_info["start_time"],
            end_time=v_info["end_time"],
            severity="CRITICAL",
            warning_flag=True,
            sensor_id=request.sensor_id,
            container_code=request.container_code,
            notes=f"Tự động phát hiện vi phạm S-43: kéo dài {v_info['duration_minutes']} phút (ngưỡng 30 phút), đỉnh {v_info['peak_temperature']}°C.",
        )
        saved_list = record_temperature_violation(db, create_payload, current_user)
        recorded_outputs.extend(saved_list)

    msg = (
        f"Đã phân tích {len(request.readings)} số đo. Phát hiện và ghi nhận "
        f"{len(recorded_outputs)} sự kiện vi phạm nhiệt độ chuỗi lạnh vào nhật ký sự kiện và Hash-Chain."
        if recorded_outputs
        else f"Đã phân tích {len(request.readings)} số đo. Toàn bộ nhiệt độ đều duy trì ổn định trong ngưỡng cho phép."
    )

    return TemperatureStreamProcessResponse(
        total_readings=len(request.readings),
        violations_detected=len(detected_violations),
        violations=recorded_outputs,
        message=msg,
    )


def get_batch_cold_chain_status(db: Session, batch_id: int) -> BatchColdChainStatusResponse:
    """Truy vấn tình trạng chuỗi lạnh và cảnh báo sự cố vi phạm của một lô hàng (S-45)."""
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy lô nông sản có id={batch_id}.",
        )

    violations = list(
        db.scalars(
            select(TemperatureViolation)
            .where(TemperatureViolation.batch_id == batch_id)
            .order_by(TemperatureViolation.created_at.desc())
        ).all()
    )

    out_list = [
        TemperatureViolationOut(
            id=v.id,
            batch_id=v.batch_id,
            batch_code=batch.code,
            shipment_id=v.shipment_id,
            recorded_temperature=v.recorded_temperature,
            min_threshold=v.min_threshold,
            max_threshold=v.max_threshold,
            peak_temperature=v.peak_temperature,
            duration_minutes=v.duration_minutes,
            start_time=v.start_time,
            end_time=v.end_time,
            severity=v.severity,
            warning_flag=v.warning_flag,
            event_id=v.event_id,
            event_hash=v.event.current_hash if v.event else None,
            resolved=v.resolved,
            notes=v.notes,
            created_at=v.created_at,
        )
        for v in violations
    ]

    warning_msg = None
    if batch.has_temperature_violation or out_list:
        warning_msg = (
            f"CẢNH BÁO: Lô nông sản '{batch.code}' từng ghi nhận {len(out_list)} sự cố "
            f"vi phạm nhiệt độ bảo quản lạnh. Bên tiếp nhận cần kiểm tra chất lượng kỹ trước khi xác nhận bàn giao!"
        )

    return BatchColdChainStatusResponse(
        batch_id=batch.id,
        batch_code=batch.code,
        cold_chain_status=batch.cold_chain_status or COLD_CHAIN_NORMAL,
        has_temperature_violation=batch.has_temperature_violation,
        total_violations=len(out_list),
        violations=out_list,
        warning_message=warning_msg,
    )


def get_batch_violations(db: Session, batch_id: int) -> list[TemperatureViolationOut]:
    """Lấy danh sách tất cả các sự cố vi phạm nhiệt độ của một lô hàng."""
    status_resp = get_batch_cold_chain_status(db, batch_id)
    return status_resp.violations


def create_shipment(
    db: Session,
    payload: ShipmentCreate,
    current_user: User,
) -> ShipmentOut:
    """Tạo mới một chuyến vận chuyển lạnh gồm các lô hàng và thùng lạnh (S-40)."""
    # Kiểm tra mã chuyến trùng lặp
    existing = db.scalar(select(Shipment).where(Shipment.code == payload.code))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Mã chuyến vận chuyển '{payload.code}' đã tồn tại trong hệ thống.",
        )

    # Kiểm tra các lô hàng
    batches = list(db.scalars(select(Batch).where(Batch.id.in_(payload.batch_ids))).all())
    found_ids = {b.id for b in batches}
    missing_ids = set(payload.batch_ids) - found_ids
    if missing_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy các lô hàng có id={sorted(list(missing_ids))}.",
        )

    transporter_org_id = current_user.organization_id or 1
    now = _naive_utcnow()

    shipment = Shipment(
        code=payload.code,
        container_code=payload.container_code,
        transporter_org_id=transporter_org_id,
        status=SHIPMENT_STATUS_IN_TRANSIT,
        started_at=now,
        notes=payload.notes,
        created_at=now,
    )
    db.add(shipment)
    db.flush()

    for batch in batches:
        link = ShipmentBatch(shipment_id=shipment.id, batch_id=batch.id, created_at=now)
        db.add(link)

    db.commit()
    db.refresh(shipment)

    return ShipmentOut(
        id=shipment.id,
        code=shipment.code,
        container_code=shipment.container_code,
        transporter_org_id=shipment.transporter_org_id,
        status=shipment.status,
        batch_ids=[b.id for b in batches],
        started_at=shipment.started_at,
        completed_at=shipment.completed_at,
        notes=shipment.notes,
        created_at=shipment.created_at,
    )


def get_shipment(db: Session, shipment_id: int) -> ShipmentOut:
    """Lấy thông tin chi tiết một chuyến vận chuyển lạnh (S-40)."""
    shipment = db.get(Shipment, shipment_id)
    if shipment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy chuyến vận chuyển có id={shipment_id}.",
        )

    return ShipmentOut(
        id=shipment.id,
        code=shipment.code,
        container_code=shipment.container_code,
        transporter_org_id=shipment.transporter_org_id,
        status=shipment.status,
        batch_ids=[b.id for b in shipment.batches],
        started_at=shipment.started_at,
        completed_at=shipment.completed_at,
        notes=shipment.notes,
        created_at=shipment.created_at,
    )
