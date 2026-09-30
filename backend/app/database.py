"""Cấu hình kết nối cơ sở dữ liệu SQLite bằng SQLAlchemy.

File này chịu trách nhiệm duy nhất một việc: tạo `engine`, `SessionLocal`,
`Base` và các hàm tiện ích dùng chung cho tầng truy cập dữ liệu.

Sprint 1: SQLite (file local, không cần cài server) để chạy demo nhanh.
Sprint sau: muốn đổi sang PostgreSQL/MySQL thì sửa `DATABASE_URL`, cài driver
tương ứng (`psycopg`, `pymysql`...), bỏ `connect_args` chỉ dành riêng cho
SQLite ở dưới - phần ORM (models/schemas/routers) không phải sửa.

Sprint 4: thêm `seed_default_users()` - tạo sẵn 2 tài khoản demo
(`admin`/`farmer`, mật khẩu `123456`) mỗi khi khởi động nếu chưa có.

Sprint 6: thêm `migrate_user_security_columns()` - bổ sung 2 cột chống dò mật
khẩu (`failed_login_attempts`, `locked_until`) cho database tạo từ Sprint 4.
"""

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError
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


def seed_default_users() -> None:
    """Tạo 2 tài khoản mặc định (``admin`` / ``farmer``) nếu chưa tồn tại.

    Tài khoản mặc định (mật khẩu giống nhau để dễ demo):

    ==========  ==========  =====================
    username    password    role
    ==========  ==========  =====================
    ``admin``   ``123456``  ``admin`` (toàn quyền)
    ``farmer``  ``123456``  ``farmer`` (nông dân)
    ==========  ==========  =====================

    Hàm **idempotent** - gọi lại nhiều lần (mỗi lần server khởi động) cũng
    không tạo trùng, và **không ghi đè** tài khoản đã có (kể cả khi người dùng
    đã đổi mật khẩu), nhờ kiểm tra ``username`` trước khi insert.

    Mật khẩu được băm bằng ``hash_password`` (SHA-256) trước khi lưu - database
    không bao giờ chứa mật khẩu dạng thô.
    """
    # Import trong hàm để tránh import vòng: models cần `Base` ở module này,
    # còn security cần `get_db` ở module này.
    from app.models import ROLE_ADMIN, ROLE_FARMER, User
    from app.security import hash_password

    default_users: tuple[dict[str, str], ...] = (
        {"username": "admin", "password": "123456", "role": ROLE_ADMIN},
        {"username": "farmer", "password": "123456", "role": ROLE_FARMER},
    )

    db: Session = SessionLocal()
    try:
        for item in default_users:
            exists = db.scalar(select(User).where(User.username == item["username"]))
            if exists is not None:
                continue  # tài khoản đã có -> giữ nguyên, không ghi đè

            db.add(
                User(
                    username=item["username"],
                    password=hash_password(item["password"]),
                    role=item["role"],
                )
            )
        db.commit()
    except SQLAlchemyError:
        # Không để server chết vì lỗi seed dữ liệu mẫu.
        db.rollback()
    finally:
        db.close()


def migrate_user_security_columns() -> None:
    """Thêm 2 cột bảo mật đăng nhập vào bảng ``users`` **nếu còn thiếu**.

    ``Base.metadata.create_all()`` chỉ tạo bảng *mới*, không thêm cột vào bảng đã
    tồn tại, nên database tạo từ Sprint 4 (``backend/ttcs.db``) vẫn thiếu
    ``failed_login_attempts`` và ``locked_until``. Hàm này chạy ``ALTER TABLE``
    để nâng cấp tại chỗ - **không** xoá bảng, **không** mất dữ liệu tài khoản.

    An toàn khi gọi lặp lại (idempotent): chỉ thêm những cột chưa tồn tại.

    Ghi chú: khi dự án chuyển sang PostgreSQL/MySQL, đây là điểm nên thay bằng
    công cụ migration thật (Alembic) thay vì ``ALTER TABLE`` thủ công.
    """
    required_columns: dict[str, str] = {
        "failed_login_attempts": "INTEGER NOT NULL DEFAULT 0",
        "locked_until": "DATETIME",
    }

    with engine.begin() as connection:
        existing_columns = {
            row[1] for row in connection.exec_driver_sql("PRAGMA table_info(users)")
        }
        if not existing_columns:
            return  # bảng chưa tồn tại -> create_all() đã tạo đủ cột

        for column_name, column_type in required_columns.items():
            if column_name not in existing_columns:
                connection.exec_driver_sql(
                    f"ALTER TABLE users ADD COLUMN {column_name} {column_type}"
                )


def init_db() -> None:
    """Tạo toàn bộ bảng trong database dựa trên metadata của các models.

    Được gọi một lần khi ứng dụng khởi động (xem ``app/main.py``):

    - ``Base.metadata.create_all()``: bảng chưa có thì tạo, bảng đã có thì
      giữ nguyên (không làm mất dữ liệu đang lưu).
    - ``migrate_user_security_columns()``: bổ sung 2 cột chống dò mật khẩu cho
      bảng ``users`` của database cũ (Sprint 6).
    - ``seed_default_users()``: tạo 2 tài khoản mặc định cho chức năng đăng nhập
      + phân quyền (Sprint 4).
    """
    # Import models ngay trong hàm để tránh import vòng (circular import):
    # models.py cần `Base` từ module này, còn module này cần models đã được
    # đăng ký vào metadata trước khi gọi create_all().
    from app import models  # noqa: F401  (import để đăng ký metadata)

    Base.metadata.create_all(bind=engine)
    migrate_user_security_columns()
    seed_default_users()
