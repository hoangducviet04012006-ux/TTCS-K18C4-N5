"""Router quản lý Chuyến vận chuyển chuỗi lạnh (Cold Trips - S-40).

Endpoints:
- POST /trips: Mở chuyến vận chuyển, gắn nhiều lô và một thùng lạnh.
- GET  /trips: Lấy danh sách các chuyến vận chuyển (có phân quyền).
- GET  /trips/{trip_id}: Xem chi tiết một chuyến xe kèm danh sách các lô.
- POST /trips/{trip_id}/complete: Hoàn thành chuyến xe, dỡ hàng xuống xe.
- GET  /trips/active-container/{container_code}: Tra cứu chuyến đang chạy theo mã thùng lạnh (hỗ trợ S-41).
"""

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.schemas_trips import (
    BatchViolationSummary,
    TemperatureLogCreate,
    TemperatureLogResponse,
    TemperatureViolationCreate,
    TemperatureViolationResponse,
    TripCompleteRequest,
    TripCreate,
    TripDetailResponse,
    TripResponse,
)
from app.security import get_current_user
from app.services.cold_chain import (
    get_batch_violation_summary,
    list_trip_readings,
    list_trip_violations,
    record_temperature_reading,
    record_temperature_violation_for_batch,
    record_temperature_violation_for_trip,
)
from app.services.trips import (
    build_trip_detail_response,
    build_trip_response,
    cancel_cold_trip,
    complete_cold_trip,
    create_cold_trip,
    find_active_trip_by_container,
    get_cold_trip_detail,
    list_cold_trips,
)

router = APIRouter(
    prefix="/trips",
    tags=["Cold Trips & Cold Chain (S-40, S-41, S-45)"],
)


@router.post(
    "",
    response_model=TripDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Mở chuyến vận chuyển gắn nhiều lô và một thùng lạnh (S-40)",
    description=(
        "Khởi tạo chuyến vận chuyển chuỗi lạnh mới ở trạng thái `IN_TRANSIT`.\n\n"
        "Kiểm tra nghiệp vụ (Server-side validation):\n"
        "- Chỉ vai trò `transporter` (hoặc `org_admin` của tổ chức vận chuyển) được phép mở chuyến (403).\n"
        "- Thùng lạnh `container_code` không được thuộc chuyến khác đang chạy (400).\n"
        "- Mỗi lô phải do tổ chức của Transporter đang trực tiếp nắm giữ (403).\n"
        "- Mỗi lô phải hợp lệ, không bị thu hồi/cách ly, không có bàn giao PENDING (400/409).\n"
        "- Ràng buộc S-16: Mỗi lô không được nằm trong hai chuyến IN_TRANSIT đồng thời (400).\n"
        "- Ghi nhận sự kiện `TRIP_DISPATCH` vào hash-chain của từng lô trong cùng transaction."
    ),
)
def create_trip(
    payload: TripCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TripDetailResponse:
    """Tạo mới chuyến vận chuyển lạnh."""
    trip = create_cold_trip(db, current_user, payload)
    return build_trip_detail_response(trip, user=current_user, db=db)


@router.get(
    "",
    response_model=list[TripResponse],
    status_code=status.HTTP_200_OK,
    summary="Danh sách chuyến vận chuyển (S-40)",
    description=(
        "Lấy danh sách các chuyến vận chuyển có phân quyền:\n"
        "- Transporter / Org Admin: chỉ xem chuyến của tổ chức mình.\n"
        "- Inspector / System Admin: xem toàn bộ chuyến liên tổ chức để giám sát chuỗi lạnh."
    ),
)
def get_trips(
    status: str | None = Query(default=None, description="Lọc theo trạng thái (IN_TRANSIT, COMPLETED, CANCELLED)."),
    container_code: str | None = Query(default=None, description="Lọc theo mã thùng lạnh."),
    limit: int = Query(default=50, ge=1, le=100, description="Số lượng bản ghi tối đa."),
    skip: int = Query(default=0, ge=0, description="Vị trí bắt đầu phân trang."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TripResponse]:
    """Lấy danh sách chuyến vận chuyển chuỗi lạnh."""
    trips = list_cold_trips(
        db,
        current_user,
        status_filter=status,
        container_code=container_code,
        limit=limit,
        skip=skip,
    )
    return [build_trip_response(t) for t in trips]


@router.get(
    "/active-container/{container_code}",
    response_model=TripResponse,
    status_code=status.HTTP_200_OK,
    summary="Tra cứu chuyến đang chạy theo mã thùng lạnh (Hỗ trợ S-41)",
    description=(
        "Tra cứu chuyến xe đang ở trạng thái IN_TRANSIT gắn với mã thùng lạnh để cảm biến nhiệt độ ghi nhận số đo.\n\n"
        "Kiểm tra phân quyền (RBAC & Organization Scope):\n"
        "- Đơn vị vận chuyển chỉ tra cứu được chuyến của tổ chức mình (403 nếu khác tổ chức).\n"
        "- Inspector và System Admin được tra cứu liên tổ chức để giám sát chuỗi lạnh.\n"
        "- Trả về 404 nếu thùng lạnh không gắn với chuyến nào đang chạy."
    ),
)
def get_active_trip_for_container(
    container_code: str = Path(..., description="Mã thùng lạnh cần tra cứu."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TripResponse:
    """Tra cứu chuyến xe đang chạy theo mã thùng lạnh."""
    trip = find_active_trip_by_container(db, container_code, user=current_user)
    if trip is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy chuyến xe nào đang chạy (IN_TRANSIT) với thùng lạnh '{container_code}'.",
        )
    return build_trip_response(trip)


@router.get(
    "/{trip_id}",
    response_model=TripDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Xem chi tiết chuyến vận chuyển (S-40)",
    description="Lấy thông tin chi tiết một chuyến xe và danh sách các lô nông sản chở trên chuyến theo phân quyền.",
)
def get_trip(
    trip_id: int = Path(..., ge=1, description="ID của chuyến xe cần xem."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TripDetailResponse:
    """Lấy chi tiết một chuyến xe lạnh."""
    trip = get_cold_trip_detail(db, current_user, trip_id)
    return build_trip_detail_response(trip, user=current_user, db=db)


@router.post(
    "/{trip_id}/complete",
    response_model=TripDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Hoàn thành chuyến vận chuyển / Hạ hàng xuống xe (S-40)",
    description=(
        "Chuyển trạng thái chuyến từ `IN_TRANSIT` sang `COMPLETED`.\n\n"
        "- Cập nhật thời điểm kết thúc (`end_time`).\n"
        "- Tự động ghi sự kiện `TRIP_DELIVER` vào hash-chain của toàn bộ các lô trên chuyến.\n"
        "- Giải phóng thùng lạnh và các lô để sẵn sàng cho các hành trình hoặc bàn giao tiếp theo."
    ),
)
def complete_trip(
    payload: TripCompleteRequest | None = None,
    trip_id: int = Path(..., ge=1, description="ID của chuyến xe cần hoàn thành."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TripDetailResponse:
    """Kết thúc chuyến vận chuyển chuỗi lạnh."""
    trip = complete_cold_trip(db, current_user, trip_id, payload)
    return build_trip_detail_response(trip, user=current_user, db=db)


@router.post(
    "/{trip_id}/cancel",
    response_model=TripDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Hủy chuyến vận chuyển chuỗi lạnh (S-40)",
    description=(
        "Chuyển trạng thái chuyến từ `IN_TRANSIT` sang `CANCELLED`.\n\n"
        "- Đặt thời điểm kết thúc (`end_time`).\n"
        "- Giải phóng thùng lạnh và các lô nông sản để có thể sử dụng lại cho chuyến khác."
    ),
)
def cancel_trip(
    payload: TripCompleteRequest | None = None,
    trip_id: int = Path(..., ge=1, description="ID của chuyến xe cần hủy."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TripDetailResponse:
    """Hủy chuyến vận chuyển chuỗi lạnh."""
    reason = payload.notes if payload else None
    trip = cancel_cold_trip(db, current_user, trip_id, reason)
    return build_trip_detail_response(trip, user=current_user, db=db)


# ==============================================================================
# QUẢN LÝ VI PHẠM NHIỆT ĐỘ & SỐ ĐO CẢM BIẾN (S-41, S-43, S-45)
# ==============================================================================
@router.post(
    "/{trip_id}/violations",
    response_model=TemperatureViolationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ghi nhận sự cố vi phạm nhiệt độ cho chuyến xe và các lô (S-45)",
    description=(
        "Khi hệ thống phát hiện cảm biến nhiệt độ ghi nhận giá trị vi phạm "
        "(vượt ngưỡng hoặc kéo dài trên 30 phút theo S-43):\n\n"
        "- Tự động ghi nhận sự kiện `TEMPERATURE_VIOLATION` vào hash-chain bất biến của mọi lô đang chở trên chuyến.\n"
        "- Cập nhật trạng thái và gắn cờ cảnh báo `has_temperature_violation = True` cho từng lô.\n"
        "- Ghi nhật ký kiểm toán `AuditLog` cho chuyến xe và các lô liên quan.\n"
        "- Đảm bảo tính nhất quán dữ liệu qua giao dịch nguyên tử (atomic transaction)."
    ),
)
def create_trip_violation(
    payload: TemperatureViolationCreate,
    trip_id: int = Path(..., ge=1, description="ID của chuyến xe xảy ra vi phạm."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TemperatureViolationResponse:
    """Ghi nhận sự cố vi phạm nhiệt độ chuỗi lạnh cho chuyến xe và toàn bộ các lô (S-45)."""
    violation = record_temperature_violation_for_trip(db, trip_id, payload, user=current_user)
    return TemperatureViolationResponse.model_validate(violation)


@router.get(
    "/{trip_id}/violations",
    response_model=list[TemperatureViolationResponse],
    status_code=status.HTTP_200_OK,
    summary="Danh sách sự cố vi phạm nhiệt độ của chuyến xe (S-45)",
    description="Lấy danh sách toàn bộ các đợt vi phạm nhiệt độ từng được ghi nhận trên chuyến xe này.",
)
def get_trip_violations(
    trip_id: int = Path(..., ge=1, description="ID của chuyến xe."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TemperatureViolationResponse]:
    """Danh sách vi phạm nhiệt độ của chuyến xe."""
    violations = list_trip_violations(db, trip_id, user=current_user)
    return [TemperatureViolationResponse.model_validate(v) for v in violations]


@router.post(
    "/{trip_id}/readings",
    response_model=TemperatureLogResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ghi nhận số đo cảm biến nhiệt độ theo thời gian (S-41)",
    description="Endpoint nhận số đo kèm mốc thời gian, tự động bỏ qua số đo cũ hơn hoặc trùng thời gian theo S-41.",
)
def add_trip_reading(
    payload: TemperatureLogCreate,
    trip_id: int = Path(..., ge=1, description="ID của chuyến xe đang chạy."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TemperatureLogResponse:
    """Ghi nhận số đo nhiệt độ cho chuyến xe."""
    trip = get_cold_trip_detail(db, current_user, trip_id)
    log = record_temperature_reading(db, trip.container_code, payload, user=current_user)
    return TemperatureLogResponse.model_validate(log)


@router.get(
    "/{trip_id}/readings",
    response_model=list[TemperatureLogResponse],
    status_code=status.HTTP_200_OK,
    summary="Lịch sử số đo cảm biến nhiệt độ của chuyến xe (S-41)",
    description="Lấy chuỗi thời gian số đo nhiệt độ thùng lạnh trong suốt hành trình.",
)
def get_trip_readings(
    trip_id: int = Path(..., ge=1, description="ID của chuyến xe."),
    limit: int = Query(default=200, ge=1, le=1000, description="Số lượng bản ghi tối đa."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TemperatureLogResponse]:
    """Lấy danh sách số đo nhiệt độ của chuyến xe."""
    readings = list_trip_readings(db, trip_id, limit=limit, user=current_user)
    return [TemperatureLogResponse.model_validate(r) for r in readings]


@router.post(
    "/active-container/{container_code}/readings",
    response_model=TemperatureLogResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Cảm biến IoT gửi số đo nhiệt độ theo mã thùng lạnh (S-41)",
    description="Cảm biến gắn trên thùng lạnh gửi dữ liệu nhiệt độ về theo mã thùng đang chạy hành trình.",
)
def add_container_reading(
    payload: TemperatureLogCreate,
    container_code: str = Path(..., description="Mã thùng lạnh."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TemperatureLogResponse:
    """Ghi nhận số đo cảm biến nhiệt độ theo mã thùng lạnh."""
    log = record_temperature_reading(db, container_code, payload, user=current_user)
    return TemperatureLogResponse.model_validate(log)


@router.get(
    "/batches/{batch_id}/violations",
    response_model=BatchViolationSummary,
    status_code=status.HTTP_200_OK,
    summary="Kiểm tra sự cố vi phạm nhiệt độ của lô nông sản (S-45)",
    description=(
        "Tra cứu tổng hợp tình trạng vi phạm chuỗi lạnh của lô nông sản:\n\n"
        "- Trả về cờ cảnh báo `has_violation` và tổng số lần vi phạm `violation_count`.\n"
        "- Trả về danh sách chi tiết các đợt vi phạm kèm thời lượng và nhiệt độ đỉnh (S-45).\n"
        "- Phục vụ nhà phân phối / bên nhận kiểm tra trước khi xác nhận bàn giao."
    ),
)
def get_batch_violations(
    batch_id: int = Path(..., ge=1, description="ID lô nông sản cần tra cứu."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BatchViolationSummary:
    """Tra cứu tình trạng vi phạm nhiệt độ của lô hàng (S-45)."""
    return get_batch_violation_summary(db, batch_id, user=current_user)


@router.post(
    "/batches/{batch_id}/violations",
    response_model=TemperatureViolationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ghi nhận sự cố vi phạm nhiệt độ trực tiếp cho lô nông sản (S-45)",
    description="Ghi nhận sự cố vi phạm nhiệt độ kho bãi hoặc kiểm tra chất lượng trực tiếp cho một lô hàng.",
)
def create_batch_violation(
    payload: TemperatureViolationCreate,
    batch_id: int = Path(..., ge=1, description="ID lô nông sản."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TemperatureViolationResponse:
    """Ghi nhận vi phạm nhiệt độ trực tiếp cho một lô nông sản."""
    violation = record_temperature_violation_for_batch(db, batch_id, payload, user=current_user)
    return TemperatureViolationResponse.model_validate(violation)
