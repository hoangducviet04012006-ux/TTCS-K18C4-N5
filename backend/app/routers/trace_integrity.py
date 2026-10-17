"""Router cho Story S-50: Kiểm tra tính toàn vẹn dữ liệu truy xuất nguồn gốc.

Cung cấp 2 endpoints:
1. GET /batches/{batch_id}/trace-integrity: Endpoint nội bộ (xác thực RBAC) cho thanh tra và đối tác.
2. GET /public/trace/{batch_code}/integrity: Endpoint công khai quét mã QR (không yêu cầu đăng nhập,
   bảo vệ bằng Rate Limiter 30 mã/phút/IP và Cache 60s).
"""

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Batch, User
from app.schemas_integrity import TraceabilityIntegrityResponse
from app.security import get_current_user
from app.services.permissions import can_view_batch
from app.services.rate_limiter import check_scan_rate_limit
from app.services.trace_integrity import verify_traceability_integrity

router = APIRouter(
    tags=["Traceability Integrity"],
)


@router.get(
    "/batches/{batch_id}/trace-integrity",
    response_model=TraceabilityIntegrityResponse,
    status_code=status.HTTP_200_OK,
    summary="Kiểm tra toàn diện tính toàn vẹn chuỗi truy xuất nguồn gốc (Story S-50)",
    description=(
        "Thẩm định toàn bộ chuỗi băm mật mã SHA-256 (Canonical JSON) từ lô thu hoạch gốc "
        "qua toàn bộ phả hệ tổ tiên đến lô hiện tại. Phát hiện can thiệp sửa trực tiếp SQL "
        "(HASH_MISMATCH) hoặc đứt gãy liên kết (CHAIN_BROKEN)."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Không tìm thấy lô nông sản."},
        status.HTTP_403_FORBIDDEN: {"description": "Không có quyền xem thông tin lô này."},
    },
)
def get_batch_trace_integrity(
    batch_id: int = Path(..., ge=1, description="ID của lô nông sản cần kiểm tra."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TraceabilityIntegrityResponse:
    """Kiểm tra toàn vẹn chuỗi truy xuất nguồn gốc nội bộ."""
    # Kiểm tra phân quyền truy cập lô
    if not can_view_batch(db, current_user.organization_id, batch_id, user_role=current_user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền truy xuất thông tin nguồn gốc của lô nông sản này.",
        )

    result = verify_traceability_integrity(db, batch_id=batch_id, use_cache=True)
    return TraceabilityIntegrityResponse(**result)


@router.get(
    "/public/trace/{batch_code}/integrity",
    response_model=TraceabilityIntegrityResponse,
    status_code=status.HTTP_200_OK,
    summary="Xác thực toàn vẹn dữ liệu truy xuất nguồn gốc công khai quét QR (Story S-50)",
    description=(
        "Endpoint công khai dành cho người tiêu dùng và khách quét mã QR kiểm tra "
        "tính toàn vẹn toán học của dữ liệu truy xuất nguồn gốc. Không yêu cầu đăng nhập. "
        "Được bảo vệ bằng bộ nhớ đệm Cache 60s và giới hạn tần suất Rate Limit 30 mã/phút/IP."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Không tìm thấy lô nông sản."},
        status.HTTP_429_TOO_MANY_REQUESTS: {"description": "Vượt quá giới hạn dò quét mã lô."},
    },
)
def get_public_trace_integrity(
    request: Request,
    batch_code: str = Path(..., min_length=1, max_length=100, description="Mã lô nông sản cần xác thực."),
    db: Session = Depends(get_db),
) -> TraceabilityIntegrityResponse:
    """Xác thực toàn vẹn chuỗi truy xuất công khai không cần đăng nhập."""
    # 1. Trích xuất địa chỉ IP client
    client_ip = request.headers.get("x-forwarded-for")
    if client_ip:
        client_ip = client_ip.split(",")[0].strip()
    else:
        client_ip = request.client.host if request.client else "127.0.0.1"

    # 2. Kiểm tra Rate Limiting chống dò quét mã lô (30 mã/phút)
    check_scan_rate_limit(client_ip, batch_code)

    # 3. Thẩm định tính toàn vẹn (tự động cache 60s)
    clean_code = batch_code.strip()
    target_batch = db.scalar(select(Batch.id).where(Batch.code == clean_code))
    if not target_batch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy lô nông sản có mã '{clean_code}'.",
        )

    result = verify_traceability_integrity(db, batch_code=clean_code, use_cache=True)
    return TraceabilityIntegrityResponse(**result)
