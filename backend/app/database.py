"""Cấu hình kết nối cơ sở dữ liệu SQLite bằng SQLAlchemy.

File này chịu trách nhiệm: tạo engine, SessionLocal, Base và các hàm tiện ích
khởi tạo database, seed dữ liệu mẫu và migration cho Sprint 1 & Sprint 2.
"""

import os
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, select, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# ---------------------------------------------------------------- Cấu hình ---
BASE_DIR: Path = Path(__file__).resolve().parent.parent
DATA_DIR: Path = BASE_DIR.parent / "data"
AGRITRACE_DB: Path = DATA_DIR / "agritrace.db"
# DATABASE_FILE biểu thị file ttcs.db gốc để phục vụ cơ chế bảo vệ chống ghi đè/demo-login
DATABASE_FILE: Path = BASE_DIR / "ttcs.db"
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{AGRITRACE_DB.as_posix()}" if AGRITRACE_DB.exists() else f"sqlite:///{DATABASE_FILE.as_posix()}"
)

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


@event.listens_for(engine, "connect")
def enable_foreign_keys(connection, _record):
    cursor = connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    """Base class cho toàn bộ ORM models."""


def get_db() -> Generator[Session, None, None]:
    """Dependency cung cấp Session cho mỗi request và tự đóng khi xong."""
    db: Session = SessionLocal()
    try:
        if not hasattr(db.get_bind(), "_phase_c_ready"):
            from app.services.locations import probe_schema
            probe_schema(db)
        yield db
    finally:
        db.close()


def seed_default_users() -> None:
    """Legacy local bootstrap is explicitly opt-in; never seed default secrets in production."""
    if os.getenv("TTCS_SEED_DEFAULTS") != "1":
        return
    if os.getenv("TTCS_ENV", "local").lower() not in ("local", "development", "test"):
        raise RuntimeError("Demo seed is disabled outside local/development/test.")
    password = os.environ.get("DEMO_PASSWORD", "")
    if len(password) < 12:
        raise RuntimeError("Set DEMO_PASSWORD (at least 12 characters).")
    from app.models import Organization, User
    from app.security import hash_password
    with SessionLocal() as db:
        org = db.scalar(select(Organization).where(Organization.code == "HTX-DT"))
        if org is None:
            org = Organization(code="HTX-DT", name="Hợp tác xã Đồng Tháp")
            db.add(org)
            db.flush()
        for username, role in (("admin", "admin"), ("farmer", "farmer")):
            if db.scalar(select(User.id).where(User.username == username)) is None:
                db.add(User(username=username, email=f"{username}@demo.local", role=role,
                            organization_id=org.id, password=hash_password(password)))
        db.commit()


def seed_default_products() -> None:
    """Tạo các sản phẩm mẫu cho hệ thống (T-16)."""
    from app.models import Product, ProductUnit

    sample_products = [
        ("Xoài cát Chu", ProductUnit.KG.value),
        ("Sầu riêng Ri6", ProductUnit.KG.value),
        ("Thanh long ruột đỏ", ProductUnit.THUNG.value),
        ("Gạo ST25", ProductUnit.TAN.value),
    ]

    db: Session = SessionLocal()
    try:
        for name, unit in sample_products:
            prod = db.scalar(select(Product).where(Product.name == name))
            if prod is None:
                db.add(Product(name=name, unit=unit))
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def migrate_user_security_columns() -> None:
    """Thêm cột bảo mật đăng nhập cho users và cột organization_id, coordinates nếu thiếu."""
    user_columns: dict[str, str] = {
        "is_active": "BOOLEAN NOT NULL DEFAULT 1",
        "is_locked": "BOOLEAN NOT NULL DEFAULT 0",
        "failed_login_attempts": "INTEGER NOT NULL DEFAULT 0",
        "locked_until": "DATETIME",
        "organization_id": "INTEGER",
        # S-04: cột email phục vụ đăng nhập bằng email (database cũ chưa có).
        "email": "VARCHAR(255)",
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


def _migrate_temperature_violation_indexes(connection) -> None:
    """T?o Partial Unique Index cho temperature_violations n?u kh?ng c? d? li?u tr?ng (S-45).

    Tuy?t ??i kh?ng x?a d? li?u ?? ?p migration th?nh c?ng.
    """
    existing_violations = {
        row[1] for row in connection.exec_driver_sql("PRAGMA table_info(temperature_violations)")
    }
    if not existing_violations:
        return

    try:
        trip_dups = connection.exec_driver_sql(
            "SELECT trip_id, start_time, COUNT(*) as cnt FROM temperature_violations "
            "WHERE trip_id IS NOT NULL "
            "GROUP BY trip_id, start_time HAVING cnt > 1"
        ).fetchall()
        if not trip_dups:
            connection.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_temp_violations_trip_start "
                "ON temperature_violations (trip_id, start_time) WHERE trip_id IS NOT NULL"
            )
    except Exception:
        pass

    try:
        batch_dups = connection.exec_driver_sql(
            "SELECT batch_id, start_time, COUNT(*) as cnt FROM temperature_violations "
            "WHERE batch_id IS NOT NULL "
            "GROUP BY batch_id, start_time HAVING cnt > 1"
        ).fetchall()
        if not batch_dups:
            connection.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_temp_violations_batch_start "
                "ON temperature_violations (batch_id, start_time) WHERE batch_id IS NOT NULL"
            )
    except Exception:
        pass


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
            if "has_temperature_violation" not in existing_batches:
                try:
                    connection.exec_driver_sql(
                        "ALTER TABLE batches ADD COLUMN has_temperature_violation BOOLEAN NOT NULL DEFAULT 0"
                    )
                except Exception:
                    pass
            if "temperature_violation_count" not in existing_batches:
                try:
                    connection.exec_driver_sql(
                        "ALTER TABLE batches ADD COLUMN temperature_violation_count INTEGER NOT NULL DEFAULT 0"
                    )
                except Exception:
                    pass
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

        _migrate_temperature_violation_indexes(connection)


def migrate_sprint2_schema(target_engine=None) -> None:  # noqa: C901
    """Migration nâng cấp schema cho Sprint 2:

    - Bảng products (T-16)
    - Bảng plots (T-18) đồng bộ với farms
    - Các cột bổ sung của batches (code, plot_id, product_id, initial_quantity, remaining_quantity, status)
    - Các cột bổ sung của batch_events (payload, organization_id, created_by_user_id, timestamp, current_hash)
    """
    eng = target_engine if target_engine is not None else engine
    with eng.begin() as connection:
        # 1. Đảm bảo bảng plots có dữ liệu tương ứng từ farms
        tables = {
            row[0]
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if "plots" in tables and "farms" in tables:
            try:
                connection.exec_driver_sql(
                    "INSERT OR IGNORE INTO plots (id, organization_id, name, location, area, coordinates, owner) "
                    "SELECT id, organization_id, name, location, area, coordinates, owner FROM farms"
                )
            except Exception:
                pass

        # 2. Cột bảng batches
        if "batches" in tables:
            batch_cols = {
                row[1] for row in connection.exec_driver_sql("PRAGMA table_info(batches)")
            }
            needed_batch_cols = {
                "code": "VARCHAR(20)",
                "plot_id": "INTEGER",
                "product_id": "INTEGER",
                "initial_quantity": "NUMERIC(10, 2)",
                "remaining_quantity": "NUMERIC(10, 2)",
                "status": "VARCHAR(30) DEFAULT 'ACTIVE'",
            }
            for col, c_type in needed_batch_cols.items():
                if col not in batch_cols:
                    try:
                        connection.exec_driver_sql(f"ALTER TABLE batches ADD COLUMN {col} {c_type}")
                    except Exception:
                        pass

            # Cập nhật dữ liệu mặc định cho các lô cũ
            try:
                connection.exec_driver_sql(
                    "UPDATE batches SET plot_id = farm_id WHERE plot_id IS NULL AND farm_id IS NOT NULL"
                )
                connection.exec_driver_sql(
                    "UPDATE batches SET farm_id = plot_id WHERE farm_id IS NULL AND plot_id IS NOT NULL"
                )
                connection.exec_driver_sql(
                    "UPDATE batches SET product_id = (SELECT products.id FROM products "
                    "WHERE products.name = batches.product_name) WHERE product_id IS NULL"
                )
                connection.exec_driver_sql(
                    "UPDATE batches SET initial_quantity = quantity WHERE initial_quantity IS NULL AND quantity IS NOT NULL"
                )
                connection.exec_driver_sql(
                    "UPDATE batches SET remaining_quantity = quantity "
                    "WHERE remaining_quantity IS NULL AND quantity IS NOT NULL"
                )
                connection.exec_driver_sql(
                    "UPDATE batches SET status = 'ACTIVE' WHERE status IS NULL"
                )
                connection.exec_driver_sql(
                    "UPDATE batches SET current_org_id = (SELECT farms.organization_id FROM farms "
                    "WHERE farms.id = batches.farm_id) WHERE current_org_id IS NULL"
                )
                # Tự động gán mã lô hợp lệ cho các bản ghi cũ thiếu code
                rows = connection.exec_driver_sql(
                    "SELECT id FROM batches WHERE code IS NULL OR code = ''"
                ).fetchall()
                for (b_id,) in rows:
                    from app.utils.batch_code import generate_batch_code
                    code_val = generate_batch_code()
                    connection.exec_driver_sql(
                        "UPDATE batches SET code = :code WHERE id = :id",
                        {"code": code_val, "id": b_id},
                    )
            except Exception:
                pass

        # 3. Cột bảng batch_events
        if "batch_events" in tables:
            event_cols = {
                row[1] for row in connection.exec_driver_sql("PRAGMA table_info(batch_events)")
            }
            needed_event_cols = {
                "payload": "JSON",
                "organization_id": "INTEGER",
                "created_by_user_id": "INTEGER",
                "timestamp": "DATETIME",
                "current_hash": "VARCHAR(64)",
            }
            for col, c_type in needed_event_cols.items():
                if col not in event_cols:
                    try:
                        connection.exec_driver_sql(f"ALTER TABLE batch_events ADD COLUMN {col} {c_type}")
                    except Exception:
                        pass

            try:
                connection.exec_driver_sql(
                    "UPDATE batch_events SET current_hash = record_hash "
                    "WHERE (current_hash IS NULL OR current_hash = '') AND record_hash IS NOT NULL"
                )
                connection.exec_driver_sql(
                    "UPDATE batch_events SET timestamp = created_at WHERE timestamp IS NULL"
                )
                connection.exec_driver_sql(
                    "UPDATE batch_events SET created_by_user_id = user_id "
                    "WHERE created_by_user_id IS NULL AND user_id IS NOT NULL"
                )
            except Exception:
                pass


def create_event_immutability_triggers(target_engine=None) -> None:
    """Tạo DB Triggers để ngăn UPDATE và DELETE trên bảng batch_events (S-11) ở tầng database."""
    eng = target_engine if target_engine is not None else engine
    triggers_sql = [
        """
        CREATE TRIGGER IF NOT EXISTS prevent_batch_events_update
        BEFORE UPDATE ON batch_events
        BEGIN
            SELECT RAISE(ABORT, 'S-11: Updates to batch_events table are strictly prohibited (append-only log).');
        END;
        """,
        """
        CREATE TRIGGER IF NOT EXISTS prevent_batch_events_delete
        BEFORE DELETE ON batch_events
        BEGIN
            SELECT RAISE(ABORT, 'S-11: Deletions from batch_events table are strictly prohibited (append-only log).');
        END;
        """,
    ]
    with eng.begin() as connection:
        for sql in triggers_sql:
            connection.exec_driver_sql(sql)


def migrate_sprint3_schema(target_engine=None) -> None:
    """Migration nâng cấp schema cho Sprint 3 (T-39, T-56):

    - Bảng batch_relations (T-39: quan hệ phả hệ tách/gộp).
    - Cột is_overdue cho bảng handovers (T-56: cảnh báo quá hạn 48h).
    """
    eng = target_engine if target_engine is not None else engine
    with eng.begin() as connection:
        tables = {
            row[0]
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if "batch_relations" not in tables:
            connection.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS batch_relations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    parent_batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
                    child_batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
                    transferred_quantity NUMERIC(10, 2) NOT NULL,
                    relation_type VARCHAR(20) NOT NULL,
                    created_at DATETIME NOT NULL,
                    CONSTRAINT uq_parent_child_batch UNIQUE (parent_batch_id, child_batch_id)
                )
                """
            )
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS idx_batch_relations_parent ON batch_relations (parent_batch_id)"
            )
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS idx_batch_relations_child ON batch_relations (child_batch_id)"
            )

        if "handovers" in tables:
            handover_cols = {
                row[1] for row in connection.exec_driver_sql("PRAGMA table_info(handovers)")
            }
            if "is_overdue" not in handover_cols:
                try:
                    connection.exec_driver_sql(
                        "ALTER TABLE handovers ADD COLUMN is_overdue BOOLEAN NOT NULL DEFAULT 0"
                    )
                except Exception:
                    pass


def init_db() -> None:
    """Tạo bảng và chạy migration khi ứng dụng khởi động."""
    from app import models  # noqa: F401

    from app.services.recall_database import is_protected_engine
    # Stage 3B.2A: original database must never be bootstrapped/migrated/seeded.
    if is_protected_engine(engine):
        return

    # Bảo vệ cơ sở dữ liệu đã hợp nhất/hoàn thiện (tránh tự động seed, reset hoặc migration khi khởi động)
    try:
        with engine.connect() as conn:
            marker = conn.exec_driver_sql(
                "SELECT value FROM sprint_demo_marker WHERE name='scope'"
            ).scalar()
            if marker == "sprint123":
                return
    except Exception:
        pass
    Base.metadata.create_all(
        bind=engine,
        tables=[t for t in Base.metadata.sorted_tables if not t.info.get("recall_trial") and not t.info.get("phase_c")],
    )
    migrate_user_security_columns()
    migrate_handover_and_batch_columns()
    migrate_sprint2_schema()
    migrate_sprint3_schema()
    create_event_immutability_triggers()
    seed_default_users()
    if os.getenv("TTCS_SEED_DEFAULTS") == "1":
        seed_default_products()
