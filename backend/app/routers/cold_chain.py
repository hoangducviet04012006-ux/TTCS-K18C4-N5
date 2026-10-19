"""Router quản lý giám sát chuỗi lạnh và xử lý vi phạm nhiệt độ (Sprint Epic E-07 / User Story S-45).

Các endpoint chính:
- POST /cold-chain/violations: Ghi nhận sự kiện vi phạm nhiệt độ vào nhật ký và Hash-Chain của lô hàng (S-45).
- POST /cold-chain/readings/stream: Bơm chuỗi số đo cảm biến, phát hiện vi phạm trễ 30 phút theo S-43 và tự động kích hoạt S-45.
- GET /cold-chain/batches/{batch_id}/violations: Xem danh sách các vi phạm nhiệt độ của một lô hàng.
- GET /cold-chain/batches/{batch_id}/status: Kiểm tra trạng thái chuỗi lạnh và cờ cảnh báo vi phạm của lô hàng.
- POST /cold-chain/shipments: Khai báo chuyến vận chuyển lạnh mới (S-40).
- GET /cold-chain/shipments/{shipment_id}: Lấy thông tin chuyến vận chuyển lạnh và các lô trên chuyến.
"""

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.schemas import (
    BatchColdChainStatusResponse,
    ShipmentCreate,
    ShipmentOut,
    TemperatureStreamProcessRequest,
    TemperatureStreamProcessResponse,
    TemperatureViolationCreate,
    TemperatureViolationOut,
)
from app.security import get_current_user
from app.services import cold_chain_service

router = APIRouter(
    prefix="/cold-chain",
    tags=["Cold Chain Monitoring"],
)


@router.post(
    "/violations",
    response_model=list[TemperatureViolationOut],
    status_code=status.HTTP_201_CREATED,
    summary="Ghi nhận sự cố vi phạm nhiệt độ vào nhật ký và chuỗi sự kiện của lô (User Story S-45)",
    description=(
        "Khi hệ thống phát hiện cảm biến nhiệt độ ghi nhận giá trị vi phạm (vượt ngưỡng hoặc kéo dài theo S-43):\n"
        "- Tự động ghi sự kiện vi phạm (TEMPERATURE_VIOLATION) vào Hash-Chain bất biến của từng lô tương ứng.\n"
        "- Cập nhật trạng thái lô hàng và gắn cờ cảnh báo (has_temperature_violation=True).\n"
        "- Ghi nhận dấu vết kiểm toán vào AuditLog của hệ thống.\n"
        "- Nếu cung cấp shipment_id: tự động áp dụng và ghi sự kiện vào chuỗi của TẤT CẢ các lô trên chuyến."
    ),
)
def record_violation(
    payload: TemperatureViolationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TemperatureViolationOut]:
    """Ghi nhận sự kiện vi phạm nhiệt độ chuỗi lạnh cho một lô hàng hoặc toàn bộ lô trên chuyến (S-45)."""
    return cold_chain_service.record_temperature_violation(
        db=db,
        payload=payload,
        current_user=current_user,
    )


@router.post(
    "/readings/stream",
    response_model=TemperatureStreamProcessResponse,
    status_code=status.HTTP_200_OK,
    summary="Tiếp nhận luồng số đo cảm biến, phân tích vi phạm S-43 và tự động kích hoạt S-45",
    description=(
        "Tiếp nhận chuỗi số đo cảm biến (S-41, S-42), áp dụng thuật toán cửa sổ trượt S-43:\n"
        "- Nhiệt độ vượt ngưỡng liên tục quá 30 phút mới tính là vi phạm.\n"
        "- Hai lần vượt cách nhau dưới 5 phút tính là một đợt vi phạm liên tục kéo dài.\n"
        "- Tự động kích hoạt quy trình S-45 ghi sự kiện vào Hash-Chain và AuditLog cho các vi phạm thỏa mãn."
    ),
)
def process_temperature_stream(
    payload: TemperatureStreamProcessRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TemperatureStreamProcessResponse:
    """Xử lý luồng số đo cảm biến nhiệt độ theo S-43 và tự động ghi sự kiện S-45."""
    return cold_chain_service.process_reading_stream_and_record(
        db=db,
        request=payload,
        current_user=current_user,
    )


@router.get(
    "/batches/{batch_id}/violations",
    response_model=list[TemperatureViolationOut],
    status_code=status.HTTP_200_OK,
    summary="Danh sách các sự cố vi phạm nhiệt độ của lô nông sản (S-45)",
    description="Truy vấn toàn bộ lịch sử vi phạm nhiệt độ đã ghi nhận của lô nông sản cụ thể.",
)
def get_batch_violations(
    batch_id: int = Path(..., ge=1, description="Mã ID của lô nông sản."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TemperatureViolationOut]:
    """Lấy danh sách các sự cố vi phạm nhiệt độ của một lô nông sản."""
    return cold_chain_service.get_batch_violations(db=db, batch_id=batch_id)


@router.get(
    "/batches/{batch_id}/status",
    response_model=BatchColdChainStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Kiểm tra trạng thái chuỗi lạnh và cờ cảnh báo vi phạm của lô hàng (S-45)",
    description=(
        "Truy vấn tình trạng chuỗi lạnh và cờ cảnh báo (has_temperature_violation).\n"
        "Được sử dụng cho bên nhận trước khi xác nhận bàn giao để quyết định nhận hay từ chối lô hàng."
    ),
)
def get_batch_cold_chain_status(
    batch_id: int = Path(..., ge=1, description="Mã ID của lô nông sản."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BatchColdChainStatusResponse:
    """Kiểm tra tình trạng chuỗi lạnh và cờ cảnh báo của lô hàng trước khi nhận bàn giao (S-45)."""
    return cold_chain_service.get_batch_cold_chain_status(db=db, batch_id=batch_id)


@router.post(
    "/shipments",
    response_model=ShipmentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Khai báo chuyến vận chuyển lạnh mới gồm các lô và thùng lạnh (S-40)",
    description="Khai báo chuyến xe chở các lô hàng và gán thùng lạnh để dữ liệu nhiệt độ gắn vào đúng các lô.",
)
def create_shipment(
    payload: ShipmentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ShipmentOut:
    """Tạo mới một chuyến vận chuyển lạnh (S-40)."""
    return cold_chain_service.create_shipment(
        db=db,
        payload=payload,
        current_user=current_user,
    )


@router.get(
    "/shipments/{shipment_id}",
    response_model=ShipmentOut,
    status_code=status.HTTP_200_OK,
    summary="Xem thông tin chuyến vận chuyển lạnh và các lô hàng trên chuyến (S-40)",
    description="Lấy chi tiết hành trình chuyến vận chuyển, thùng lạnh và danh sách các lô hàng đang chở.",
)
def get_shipment(
    shipment_id: int = Path(..., ge=1, description="Mã ID của chuyến vận chuyển."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ShipmentOut:
    """Lấy thông tin chi tiết một chuyến vận chuyển lạnh (S-40)."""
    return cold_chain_service.get_shipment(db=db, shipment_id=shipment_id)
