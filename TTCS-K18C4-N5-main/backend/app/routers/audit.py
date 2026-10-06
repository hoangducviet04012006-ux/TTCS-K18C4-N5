"""Router lịch sử thao tác (``GET /audit-logs``) - Sprint 7, **chỉ admin**.

Mục đích: trả lời câu hỏi "ai đã làm gì trong hệ thống". Dữ liệu được ghi tự
động bởi các endpoint tạo/sửa/xoá vùng trồng & lô nông sản (xem ``app/audit.py``).

- Gọi bằng tài khoản ``admin``  → ``200 OK`` + danh sách log (mới nhất trước).
- Gọi bằng tài khoản ``farmer`` → ``403 Forbidden``.
- Không gửi header ``Authorization`` → ``401 Unauthorized``.

Hỗ trợ lọc để tra cứu nhanh: ``?entity=farm|batch``, ``?user_id=<id>``,
``?limit=<1..500>``.
"""

from typing import Literal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.audit import (
    DEFAULT_AUDIT_LOG_LIMIT,
    MAX_AUDIT_LOG_LIMIT,
    fetch_audit_logs,
)
from app.database import get_db
from app.models import User
from app.schemas import AuditLogResponse
from app.security import require_admin

router = APIRouter(
    prefix="/audit-logs",
    tags=["Audit logs"],
)


@router.get(
    "",
    response_model=list[AuditLogResponse],
    status_code=status.HTTP_200_OK,
    summary="Xem lịch sử thao tác (chỉ admin)",
    description=(
        "Trả về danh sách thao tác đã được ghi nhận, **mới nhất trước**: ai "
        "(`user_id`/`username`) làm gì (`action`) trên bản ghi nào "
        "(`entity`/`entity_id`) vào lúc nào (`created_at`, UTC).\n\n"
        "Log được sinh tự động khi tạo/sửa/xoá vùng trồng hoặc lô nông sản - "
        "không có endpoint nào cho phép client tự thêm/sửa/xoá log.\n\n"
        "**Bộ lọc (tuỳ chọn):** `entity` (`farm`/`batch`), `user_id`, `limit` "
        f"(mặc định {DEFAULT_AUDIT_LOG_LIMIT}, tối đa {MAX_AUDIT_LOG_LIMIT}). "
        "Giá trị `entity` không hợp lệ → `422 Unprocessable Entity`.\n\n"
        "**Phân quyền:** chỉ `role = admin` được gọi (dùng `require_admin`). "
        "Farmer gọi sẽ nhận `403 Forbidden`."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Chưa đăng nhập (thiếu header `Authorization`).",
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "Đã đăng nhập nhưng không phải admin.",
        },
    },
)
def list_audit_logs(
    # `Literal` (chuỗi cụ thể) để FastAPI validate: giá trị lạ -> 422.
    # Hai giá trị hợp lệ trùng với ENTITY_FARM / ENTITY_BATCH ở `app/models.py`.
    entity: Literal["farm", "batch"] | None = Query(
        default=None,
        description="Lọc theo loại dữ liệu bị tác động: `farm` hoặc `batch`.",
        examples=["farm"],
    ),
    user_id: int | None = Query(
        default=None,
        ge=1,
        description="Lọc theo ID người thực hiện (bảng `users`).",
        examples=[1],
    ),
    limit: int = Query(
        default=DEFAULT_AUDIT_LOG_LIMIT,
        ge=1,
        le=MAX_AUDIT_LOG_LIMIT,
        description=(
            "Số dòng log tối đa trả về (mới nhất trước). "
            f"Mặc định {DEFAULT_AUDIT_LOG_LIMIT}, tối đa {MAX_AUDIT_LOG_LIMIT}."
        ),
        examples=[100],
    ),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[AuditLogResponse]:
    """Lấy lịch sử thao tác (chỉ admin).

    Args:
        entity: Lọc theo ``"farm"`` / ``"batch"``; ``None`` = tất cả.
        user_id: Lọc theo người thực hiện; ``None`` = tất cả.
        limit: Số dòng tối đa (đã được FastAPI validate trong khoảng 1..500).
        current_user: Tài khoản admin đã được ``require_admin`` kiểm tra quyền.
        db: Session SQLAlchemy từ dependency ``get_db``.

    Returns:
        list[AuditLogResponse]: Log mới nhất trước (HTTP 200); mảng rỗng nếu
        chưa có thao tác nào (hoặc bộ lọc không khớp).

    Raises:
        HTTPException: 401 nếu chưa đăng nhập; 403 nếu không phải admin
            (được raise tự động bên trong dependency ``require_admin``).
    """
    # `current_user` không dùng trong thân hàm nhưng bắt buộc phải khai báo để
    # FastAPI chạy dependency kiểm tra quyền trước khi vào endpoint.
    _ = current_user
    return fetch_audit_logs(db, entity=entity, user_id=user_id, limit=limit)