"""Router phục vụ Cổng Truy xuất Nguồn gốc Công khai (Story S-48).

Tuân thủ nghiêm ngặt quy định bảo vệ dữ liệu công khai S-48:
- Chỉ trả về các trường được đánh dấu trong danh mục công khai (whitelist tập trung).
- Mọi trường nội bộ bị chặn mặc định và loại bỏ triệt để.
- Khối lượng, giá cả và tên đối tác kinh doanh trung gian được bảo mật tuyệt đối.
"""

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas_public import PublicBatchTraceResponse
from app.services.public_trace import get_public_batch_trace

router = APIRouter(tags=["Public Traceability"])


@router.get(
    "/public/trace/{batch_code}",
    response_model=PublicBatchTraceResponse,
    status_code=status.HTTP_200_OK,
    summary="Thông tin truy xuất nguồn gốc công khai theo mã lô (Story S-48)",
    description=(
        "Endpoint công khai dành cho người tiêu dùng và khách quét mã QR xem thông tin "
        "truy xuất nguồn gốc nông sản. Không yêu cầu đăng nhập.\n\n"
        "**Tuân thủ tiêu chuẩn bảo vệ dữ liệu S-48:**\n"
        "- Chỉ trả về các trường thuộc danh mục cho phép (mã lô, nông sản, ngày thu hoạch, "
        "xuất xứ vùng trồng, danh sách lô gốc, hành trình các khâu).\n"
        "- Tuyệt đối không để lộ khối lượng, giá cả hay cấu trúc kinh doanh.\n"
        "- Tên đối tác thương mại trung gian được ẩn danh theo loại đơn vị (Hợp tác xã, "
        "Đơn vị vận chuyển, Nhà phân phối...). Vùng trồng gốc vẫn hiển thị minh bạch."
    ),
    responses={
        status.HTTP_200_OK: {
            "description": "Dữ liệu truy xuất nguồn gốc công khai hợp lệ.",
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "Không tìm thấy lô nông sản với mã cung cấp.",
        },
    },
)
def public_trace_by_code(
    batch_code: str = Path(..., min_length=1, max_length=100, description="Mã công khai của lô nông sản."),
    db: Session = Depends(get_db),
) -> PublicBatchTraceResponse:
    """Truy vấn thông tin truy xuất nguồn gốc công khai cho người tiêu dùng."""
    data = get_public_batch_trace(batch_code=batch_code, db=db)
    return PublicBatchTraceResponse(**data)
