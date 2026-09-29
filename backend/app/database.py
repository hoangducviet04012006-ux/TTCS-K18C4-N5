"""Cấu hình kết nối cơ sở dữ liệu SQLite bằng SQLAlchemy.

File này chịu trách nhiệm duy nhất một việc: tạo `engine`, `SessionLocal`,
`Base` và các hàm tiện ích dùng chung cho tầng truy cập dữ liệu.

Sprint 1: SQLite (file local, không cần cài server) để chạy demo nhanh.
Sprint sau: muốn đổi sang PostgreSQL/MySQL thì sửa `DATABASE_URL`, cài driver
tương ứng (`psycopg`, `pymysql`...), bỏ `connect_args` chỉ dành riêng cho
SQLite ở dưới - phần ORM (models/schemas/routers) không phải sửa.
"""

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# ---------------------------------------------------------------- Cấu hình ---
# Thư mục `backend/` (cha của thư mục `app/`) - nơi đặt file database .db
BASE_DIR: Path = Path(__file__).resolve().parent.parent

# Đường dẫn file SQLite: backend/ttcs.db
DATABASE_FILE: Path = BASE_DIR / "ttcs.db"
DATABASE_URL: str = f"sqlite:///{DATABASE_FILE.as_posix()}"

# -------------------------------------------------------------- SQLAlchemy ---
# `check_same_thread=False` là bắt buộc với SQLite khi dùng cùng FastAPI,
# vì mỗi request có thể được xử lý trên một thread khác nhau.
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,  # đổi thành True nếu muốn xem câu SQL sinh ra khi debug
)

# Mỗi request sẽ mở một Session riêng, không tự commit/autoflush (an toàn hơn).
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    """Base class cho toàn bộ ORM models.

    Mọi model trong ``app/models.py`` đều kế thừa class này để SQLAlchemy
    biết cách ánh xạ (map) class Python -> bảng trong database.
    """


# ------------------------------------------------------------------- Helper ---
def get_db() -> Generator[Session, None, None]:
    """Dependency cung cấp Session cho mỗi request và tự đóng khi xong.

    Cách dùng trong router::

        from fastapi import Depends
        from sqlalchemy.orm import Session
        from app.database import get_db

        @router.get("/items")
        def list_items(db: Session = Depends(get_db)):
            ...
    """
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Tạo toàn bộ bảng trong database dựa trên metadata của các models.

    Được gọi một lần khi ứng dụng khởi động (xem ``app/main.py``).
    Sprint 1 chưa có model nào nên database chỉ được tạo file rỗng - đây là
    bước chuẩn bị hạ tầng cho Sprint 2.
    """
    # Import models ngay trong hàm để tránh import vòng (circular import):
    # models.py cần `Base` từ module này, còn module này cần models đã được
    # đăng ký vào metadata trước khi gọi create_all().
    from app import models  # noqa: F401  (import để đăng ký metadata)

    Base.metadata.create_all(bind=engine)
