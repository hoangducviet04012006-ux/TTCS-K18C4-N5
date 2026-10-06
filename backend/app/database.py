"""Cấu hình kết nối cơ sở dữ liệu SQLite bằng SQLAlchemy.

File này chịu trách nhiệm: tạo engine, SessionLocal, Base và các hàm tiện ích
khởi tạo database, seed dữ liệu mẫu và migration.
"""

import os
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# ---------------------------------------------------------------- Cấu hình ---
BASE_DIR: Path = Path(__file__).resolve().parent.parent
DATABASE_FILE: Path = BASE_DIR / "ttcs.db"
DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{DATABASE_FILE.as_posix()}")

# Đảm bảo thư mục chứa file SQLite tồn tại (hỗ trợ mount volume Docker)
if DATABASE_URL.startswith("sqlite:///"):
    _db_path_str = DATABASE_URL.replace("sqlite:///", "")
    if _db_path_str and not _db_path_str.startswith(":memory:"):
        _db_path = Path(_db_path_str)
        _db_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    """Base class cho toàn bộ ORM models."""


def get_db() -> Generator[Session, None, None]:
    """Dependency cung cấp Session cho mỗi request và tự đóng khi xong."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def seed_default_users() -> None:
    """Tạo tổ chức mặc định và các tài khoản demo mẫu (Argon2id).

    Tạo:
    - Tổ chức 1: Hợp tác xã Nông sản An Toàn Đồng Tháp (HTX-DT)
    - Tổ chức 2: Hợp tác xã Nông nghiệp Sạch Tiền Giang (HTX-TG) - phục vụ test cách ly dữ liệu
    - Tài khoản: admin (HTX-DT), farmer (HTX-DT), farmer_tg (HTX-TG), mật khẩu demo: 123456
    """
    from app.models import ROLE_ADMIN, ROLE_FARMER, Organization, User
    from app.security import hash_password

    db: Session = SessionLocal()
    try:
        # 1. Tạo tổ chức mặc định nếu chưa có
        org_dt = db.scalar(select(Organization).where(Organization.code == "HTX-DT"))
        if org_dt is None:
            org_dt = Organization(
                name="Hợp tác xã Nông sản An Toàn Đồng Tháp",
                code="HTX-DT",
                description="Hợp tác xã chuyên canh tác xoài và cây ăn trái xuất khẩu tỉnh Đồng Tháp",
            )
            db.add(org_dt)
            db.flush()

        org_tg = db.scalar(select(Organization).where(Organization.code == "HTX-TG"))
        if org_tg is None:
            org_tg = Organization(
                name="Hợp tác xã Nông nghiệp Sạch Tiền Giang",
                code="HTX-TG",
                description="Hợp tác xã sầu riêng & nông sản sạch tỉnh Tiền Giang",
            )
            db.add(org_tg)
            db.flush()

        # 2. Tạo tài khoản demo
        default_users: tuple[dict, ...] = (
            {"username": "admin", "password": "123456", "role": ROLE_ADMIN, "organization_id": org_dt.id},
            {"username": "farmer", "password": "123456", "role": ROLE_FARMER, "organization_id": org_dt.id},
            {"username": "farmer_tg", "password": "123456", "role": ROLE_FARMER, "organization_id": org_tg.id},
        )

        for item in default_users:
            user = db.scalar(select(User).where(User.username == item["username"]))
            if user is None:
                db.add(
                    User(
                        username=item["username"],
                        password=hash_password(item["password"]),
                        role=item["role"],
                        organization_id=item["organization_id"],
                    )
                )
            else:
                if user.organization_id is None:
                    user.organization_id = item["organization_id"]

        # Cập nhật các thửa đất cũ chưa có organization_id về org_dt.id
        try:
            from sqlalchemy import text
            db.execute(
                text("UPDATE farms SET organization_id = :org_id WHERE organization_id IS NULL"),
                {"org_id": org_dt.id},
            )
        except Exception:
            pass

        # Tạo mẫu 1 thửa đất cho HTX Tiền Giang nếu chưa có để demo cách ly dữ liệu
        try:
            from app.models import Farm
            farm_tg = db.scalar(select(Farm).where(Farm.organization_id == org_tg.id))
            if farm_tg is None:
                db.add(
                    Farm(
                        name="Vườn sầu riêng Ri6 Cai Lậy",
                        location="Xã Tam Bình, huyện Cai Lậy, Tiền Giang",
                        area=2.8,
                        owner="HTX Nông nghiệp Sạch Tiền Giang",
                        coordinates="10.4123, 106.0123",
                        organization_id=org_tg.id,
                    )
                )
        except Exception:
            pass
        db.commit()
    except SQLAlchemyError:
        db.rollback()
    finally:
        db.close()


def migrate_user_security_columns() -> None:
    """Thêm cột bảo mật đăng nhập cho users và cột organization_id, coordinates nếu thiếu."""
    user_columns: dict[str, str] = {
        "failed_login_attempts": "INTEGER NOT NULL DEFAULT 0",
        "locked_until": "DATETIME",
        "organization_id": "INTEGER",
    }
    farm_columns: dict[str, str] = {
        "organization_id": "INTEGER",
        "coordinates": "VARCHAR(255)",
    }

    with engine.begin() as connection:
        existing_users = {
            row[1] for row in connection.exec_driver_sql("PRAGMA table_info(users)")
        }
        if existing_users:
            for col_name, col_type in user_columns.items():
                if col_name not in existing_users:
                    connection.exec_driver_sql(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}")

        existing_farms = {
            row[1] for row in connection.exec_driver_sql("PRAGMA table_info(farms)")
        }
        if existing_farms:
            for col_name, col_type in farm_columns.items():
                if col_name not in existing_farms:
                    connection.exec_driver_sql(f"ALTER TABLE farms ADD COLUMN {col_name} {col_type}")


def migrate_handover_and_batch_columns() -> None:
    """Thêm cột current_org_id cho bảng batches và tạo index unique cho handovers nếu thiếu."""
    with engine.begin() as connection:
        existing_batches = {
            row[1] for row in connection.exec_driver_sql("PRAGMA table_info(batches)")
        }
        if existing_batches:
            if "current_org_id" not in existing_batches:
                connection.exec_driver_sql(
                    "ALTER TABLE batches ADD COLUMN current_org_id INTEGER REFERENCES organizations(id)"
                )
            try:
                connection.exec_driver_sql(
                    "UPDATE batches SET current_org_id = ("
                    "    SELECT farms.organization_id FROM farms WHERE farms.id = batches.farm_id"
                    ") WHERE current_org_id IS NULL"
                )
            except Exception:
                pass

        existing_handovers = {
            row[1] for row in connection.exec_driver_sql("PRAGMA table_info(handovers)")
        }
        if existing_handovers:
            try:
                connection.exec_driver_sql(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_batch_pending_handover "
                    "ON handovers (batch_id) WHERE status = 'PENDING'"
                )
            except Exception:
                pass


def init_db() -> None:
    """Tạo bảng và chạy migration khi ứng dụng khởi động."""
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    migrate_user_security_columns()
    migrate_handover_and_batch_columns()
    seed_default_users()
