"""Router kiểm tra trạng thái hệ thống và kết nối cơ sở dữ liệu."""

from fastapi import APIRouter, Depends, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import HealthResponse

router = APIRouter(
    tags=["System"],
)


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Kiểm tra hệ thống (Health Check)",
    description="Trả về trạng thái hoạt động của backend và kết nối DB. Dùng cho health check CI/CD.",
)
def health_check(db: Session = Depends(get_db)) -> HealthResponse:
    """Endpoint health check kiểm tra máy chủ và kết nối database.

    Returns:
        HealthResponse: {"status": "ok", "database": "connected"} nếu mọi thứ bình thường.
    """
    try:
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:
        db_status = "disconnected"
    return HealthResponse(status="ok", database=db_status)
