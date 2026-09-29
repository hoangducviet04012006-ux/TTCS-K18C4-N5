"""Điểm khởi tạo (entrypoint) của ứng dụng FastAPI.

Chạy local:
    uvicorn app.main:app --reload

Tài liệu API (Swagger UI):
    http://127.0.0.1:8000/docs

Sprint 1 - Phạm vi nền tảng:
- Cấu hình FastAPI (metadata, CORS, tài liệu tự động).
- Kết nối SQLite qua SQLAlchemy (khởi tạo bảng khi app start).
- Endpoint kiểm tra hệ thống: GET /health
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.database import init_db
from app.routers import batches, farms, health

# ------------------------------------------------------------------ Lifespan ---
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Vòng đời ứng dụng: chạy khi server khởi động và khi server tắt.

    Hiện tại chỉ cần tạo bảng trong SQLite (nếu chưa có) trước khi nhận request.
    """
    init_db()
    yield


# ----------------------------------------------------------- Khởi tạo FastAPI ---
app = FastAPI(
    title="TTCS K18C4 - Truy xuất nguồn gốc và giám sát chuỗi lạnh nông sản",
    description=(
        "Backend API cho hệ thống truy xuất nguồn gốc và giám sát chuỗi lạnh "
        "nông sản. **Sprint 1**: khung dự án + `GET /health`. "
        "**Sprint 2**: module Farm (`POST /farms`, `GET /farms`) và "
        "module Batch - lô nông sản (`POST /batches`, `GET /batches`, "
        "`GET /batches/{batch_id}`)."
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

# --------------------------------------------------------- Đăng ký các router ---
# Mỗi module nghiệp vụ là 1 router; thêm module mới = thêm 1 dòng ở đây.
app.include_router(health.router)
app.include_router(farms.router)
app.include_router(batches.router)
