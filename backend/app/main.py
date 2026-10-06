"""Điểm khởi tạo (entrypoint) của ứng dụng FastAPI.

Chạy local:
    uvicorn app.main:app --reload

Tài liệu API (Swagger UI):
    http://127.0.0.1:8000/docs

Các sprint:
- Sprint 1: cấu hình FastAPI (metadata, CORS, tài liệu tự động), kết nối SQLite
  qua SQLAlchemy (khởi tạo bảng khi app start), endpoint ``GET /health``.
- Sprint 2/3: module Farm (``/farms``) và Batch (``/batches``).
- Sprint 4: đăng nhập + phân quyền cơ bản (``/auth/login``, ``/users``,
  dependency ``require_admin``/``require_farmer``) - **không dùng JWT**.
- Sprint 5: hoàn thiện CRUD - thêm ``PUT``/``DELETE`` cho ``/farms`` và
  ``/batches`` (xoá chỉ dành cho ``admin``).
- Sprint 6: bảo mật đăng nhập - sai mật khẩu 5 lần liên tiếp thì khoá tài khoản
  5 phút (``POST /auth/login`` trả ``403`` kèm header ``Retry-After``, mọi API
  cần quyền cũng bị chặn khi tài khoản đang bị khoá) - xem ``app/security.py``.
- Sprint 7: lịch sử thao tác (audit log) - tự ghi log mỗi lần tạo/sửa/xoá vùng
  trồng hoặc lô nông sản, xem lại bằng ``GET /audit-logs`` (chỉ ``admin``) -
  xem ``app/audit.py``.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import __version__
from app.database import get_db, init_db
from app.routers import audit, auth, batches, farms, handovers, health, users
from app.schemas import HealthResponse


# ------------------------------------------------------------------ Lifespan ---
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Vòng đời ứng dụng: chạy khi server khởi động và khi server tắt.

    Khi khởi động: tạo bảng còn thiếu trong SQLite và tạo 2 tài khoản mặc định
    (``admin``/``farmer``) nếu chưa có - xem ``app/database.py``.
    """
    init_db()
    yield


# ----------------------------------------------------------- Khởi tạo FastAPI ---
app = FastAPI(
    title="TTCS K18C4 - Truy xuất nguồn gốc và giám sát chuỗi lạnh nông sản",
    description=(
        "Backend API cho hệ thống truy xuất nguồn gốc và giám sát chuỗi lạnh "
        "nông sản.\n\n"
        "- **Sprint 1**: khung dự án + `GET /health`.\n"
        "- **Sprint 2**: module Farm (`POST /farms`, `GET /farms`, "
        "`PUT /farms/{farm_id}`, `DELETE /farms/{farm_id}`).\n"
        "- **Sprint 3**: module Batch - lô nông sản (`POST /batches`, "
        "`GET /batches`, `GET /batches/{batch_id}`, `PUT /batches/{batch_id}`, "
        "`DELETE /batches/{batch_id}`).\n"
        "- **Sprint 4**: đăng nhập + phân quyền cơ bản (`POST /auth/login`, "
        "`GET /users`). **Không dùng JWT**: các API cần quyền dùng HTTP Basic - "
        "bấm nút **Authorize** ở trên rồi nhập `admin` / `123456` (hoặc "
        "`farmer` / `123456`) để test.\n"
        "- **Sprint 5**: hoàn thiện CRUD (`PUT`/`DELETE` cho `/farms` và "
        "`/batches`) + dashboard thống kê trên giao diện. Nhóm `DELETE` yêu cầu "
        "role `admin` (farmer nhận `403`), các API còn lại cho cả `farmer`.\n"
        "- **Sprint 6**: bảo mật đăng nhập - nhập sai mật khẩu **5 lần liên tiếp** "
        "thì tài khoản bị **tạm khoá 5 phút**: `/auth/login` và mọi API cần quyền "
        "trả `403` (kèm header `Retry-After`), kể cả khi gõ đúng mật khẩu. "
        "Đăng nhập thành công hoặc hết thời gian khoá thì bộ đếm tự đặt lại về 0.\n"
        "- **Sprint 7**: lịch sử thao tác (audit log) - mỗi lần tạo/sửa/xoá vùng "
        "trồng hoặc lô nông sản, backend tự ghi 1 dòng vào bảng `audit_logs`; "
        "xem lại toàn bộ bằng `GET /audit-logs` (**chỉ `admin`**, farmer nhận "
        "`403`) kèm bộ lọc `entity` / `user_id` / `limit`. Log **không** sửa/xoá "
        "được qua API và ghi sai thao tác (404/403/500) thì không phát sinh log."
    ),
    version=__version__,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# CORS: cho phép frontend (chạy ở cổng khác) gọi API khi phát triển.
# Sprint sau cần thay "*" bằng danh sách domain cụ thể trước khi deploy production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------- Health Check ---
@app.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    tags=["System"],
    summary="Kiểm tra hệ thống (Health Check)",
    description="Kiểm tra trạng thái máy chủ và kết nối cơ sở dữ liệu (SCRUM-17 / S-03).",
)
def health_check(db: Session = Depends(get_db)) -> HealthResponse:
    """Endpoint kiểm tra sức khỏe hệ thống phục vụ CI/CD và deployment."""
    try:
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:
        db_status = "disconnected"
    return HealthResponse(status="ok", database=db_status)


from app.routers import (
    audit,
    auth,
    batches,
    events,
    farms,
    handovers,
    health,
    users,
)

# --------------------------------------------------------- Đăng ký các router ---
# Mỗi module nghiệp vụ là 1 router; thêm module mới = thêm 1 dòng ở đây.
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(farms.router)
app.include_router(batches.router)
app.include_router(events.router)
app.include_router(users.router)
app.include_router(audit.router)
app.include_router(handovers.router)

