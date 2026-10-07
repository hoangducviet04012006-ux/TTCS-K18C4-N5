"""Cáº¥u hÃ¬nh káº¿t ná»‘i cÆ¡ sá»Ÿ dá»¯ liá»‡u SQLite báº±ng SQLAlchemy.

File nÃ y chá»‹u trÃ¡ch nhiá»‡m: táº¡o engine, SessionLocal, Base vÃ  cÃ¡c hÃ m tiá»‡n Ã­ch
khá»Ÿi táº¡o database, seed dá»¯ liá»‡u máº«u vÃ  migration.
"""

import os
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# ---------------------------------------------------------------- Cáº¥u hÃ¬nh ---
BASE_DIR: Path = Path(__file__).resolve().parent.parent
DATABASE_FILE: Path = BASE_DIR / "ttcs.db"
DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{DATABASE_FILE.as_posix()}")

# Äáº£m báº£o thÆ° má»¥c chá»©a file SQLite tá»“n táº¡i (há»— trá»£ mount volume Docker)
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
    """Base class cho toÃ n bá»™ ORM models."""


def get_db() -> Generator[Session, None, None]:
    """Dependency cung cáº¥p Session cho má»—i request vÃ  tá»± Ä‘Ã³ng khi xong."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def seed_default_users() -> None:
    """Táº¡o tá»• chá»©c máº·c Ä‘á»‹nh vÃ  cÃ¡c tÃ i khoáº£n demo máº«u (Argon2id).

    Táº¡o:
    - Tá»• chá»©c 1: Há»£p tÃ¡c xÃ£ NÃ´ng sáº£n An ToÃ n Äá»“ng ThÃ¡p (HTX-DT)
    - Tá»• chá»©c 2: Há»£p tÃ¡c xÃ£ NÃ´ng nghiá»‡p Sáº¡ch Tiá»n Giang (HTX-TG) - phá»¥c vá»¥ test cÃ¡ch ly dá»¯ liá»‡u
    - TÃ i khoáº£n: admin (HTX-DT), farmer (HTX-DT), farmer_tg (HTX-TG), máº­t kháº©u demo: 123456
    """
    from app.models import ROLE_ADMIN, ROLE_FARMER, Organization, User
    from app.security import hash_password

    db: Session = SessionLocal()
    try:
        # 1. Táº¡o tá»• chá»©c máº·c Ä‘á»‹nh náº¿u chÆ°a cÃ³
        org_dt = db.scalar(select(Organization).where(Organization.code == "HTX-DT"))
        if org_dt is None:
            org_dt = Organization(
                name="Há»£p tÃ¡c xÃ£ NÃ´ng sáº£n An ToÃ n Äá»“ng ThÃ¡p",
                code="HTX-DT",
                description="Há»£p tÃ¡c xÃ£ chuyÃªn canh tÃ¡c xoÃ i vÃ  cÃ¢y Äƒn trÃ¡i xuáº¥t kháº©u tá»‰nh Äá»“ng ThÃ¡p",
            )
            db.add(org_dt)
            db.flush()

        org_tg = db.scalar(select(Organization).where(Organization.code == "HTX-TG"))
        if org_tg is None:
            org_tg = Organization(
                name="Há»£p tÃ¡c xÃ£ NÃ´ng nghiá»‡p Sáº¡ch Tiá»n Giang",
                code="HTX-TG",
                description="Há»£p tÃ¡c xÃ£ sáº§u riÃªng & nÃ´ng sáº£n sáº¡ch tá»‰nh Tiá»n Giang",
            )
            db.add(org_tg)
            db.flush()

        # 2. Táº¡o tÃ i khoáº£n demo
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

        # Cáº­p nháº­t cÃ¡c thá»­a Ä‘áº¥t cÅ© chÆ°a cÃ³ organization_id vá» org_dt.id
        try:
            from sqlalchemy import text
            db.execute(
                text("UPDATE farms SET organization_id = :org_id WHERE organization_id IS NULL"),
                {"org_id": org_dt.id},
            )
        except Exception:
            pass

        # Táº¡o máº«u 1 thá»­a Ä‘áº¥t cho HTX Tiá»n Giang náº¿u chÆ°a cÃ³ Ä‘á»ƒ demo cÃ¡ch ly dá»¯ liá»‡u
        try:
            from app.models import Farm
            farm_tg = db.scalar(select(Farm).where(Farm.organization_id == org_tg.id))
            if farm_tg is None:
                db.add(
                    Farm(
                        name="VÆ°á»n sáº§u riÃªng Ri6 Cai Láº­y",
                        location="XÃ£ Tam BÃ¬nh, huyá»‡n Cai Láº­y, Tiá»n Giang",
                        area=2.8,
                        owner="HTX NÃ´ng nghiá»‡p Sáº¡ch Tiá»n Giang",
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
    """ThÃªm cá»™t báº£o máº­t Ä‘Äƒng nháº­p cho users vÃ  cá»™t organization_id, coordinates náº¿u thiáº¿u."""
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
    """ThÃªm cá»™t current_org_id cho báº£ng batches vÃ  táº¡o index unique cho handovers náº¿u thiáº¿u."""
    with engine.begin() as connection:
        existing_batches = {
            row[1] for row in connection.exec_driver_sql("PRAGMA table_info(batches)")
        }
        if existing_batches:
            if "current_org_id" not in existing_batches:
                connection.exec_driver_sql(
                    "ALTER TABLE batches ADD COLUMN current_org_id INTEGER REFERENCES organizations(id)"
                )
            if "parent_id" not in existing_batches:
                connection.exec_driver_sql(
                    "ALTER TABLE batches ADD COLUMN parent_id INTEGER REFERENCES batches(id)"
                )
            if "remaining_quantity" not in existing_batches:
                connection.exec_driver_sql(
                    "ALTER TABLE batches ADD COLUMN remaining_quantity REAL"
                )
            if "status" not in existing_batches:
                connection.exec_driver_sql(
                    "ALTER TABLE batches ADD COLUMN status TEXT"
                )
            if "unit" not in existing_batches:
                connection.exec_driver_sql(
                    "ALTER TABLE batches ADD COLUMN unit TEXT"
                )
            try:
                connection.exec_driver_sql(
                    "UPDATE batches SET current_org_id = ("
                    "    SELECT farms.organization_id FROM farms WHERE farms.id = batches.farm_id"
                    ") WHERE current_org_id IS NULL"
                )
                connection.exec_driver_sql(
                    "UPDATE batches SET remaining_quantity = quantity WHERE remaining_quantity IS NULL"
                )
                connection.exec_driver_sql(
                    "UPDATE batches SET status = 'Äang lÆ°u kho' WHERE status IS NULL OR status = ''"
                )
                connection.exec_driver_sql(
                    "UPDATE batches SET unit = 'kg' WHERE unit IS NULL OR unit = ''"
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


def create_event_immutability_triggers(target_engine=None) -> None:
    """Táº¡o DB Triggers Ä‘á»ƒ ngÄƒn UPDATE vÃ  DELETE trÃªn báº£ng batch_events (S-11) á»Ÿ táº§ng database."""
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



def migrate_s09_idempotency_column() -> None:
    """Migration S-09: l?u Idempotency-Key ?? ch?ng t?o l? thu ho?ch tr?ng."""
    with engine.begin() as conn:
        columns = {
            row[1]
            for row in conn.exec_driver_sql("PRAGMA table_info(batches)").fetchall()
        }

        if "idempotency_key" not in columns:
            conn.exec_driver_sql(
                "ALTER TABLE batches ADD COLUMN idempotency_key VARCHAR(255)"
            )

        conn.exec_driver_sql(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
            uq_batches_current_org_idempotency_key
            ON batches(current_org_id, idempotency_key)
            WHERE idempotency_key IS NOT NULL
            """
        )


def init_db() -> None:
    """Táº¡o báº£ng vÃ  cháº¡y migration khi á»©ng dá»¥ng khá»Ÿi Ä‘á»™ng."""
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    migrate_user_security_columns()
    migrate_handover_and_batch_columns()
    migrate_s07_s08_s09_columns()
    migrate_s09_idempotency_column()
    create_event_immutability_triggers()
    seed_default_users()

def migrate_s07_s08_s09_columns() -> None:
    """Bá»• sung báº£ng danh má»¥c vÃ  cÃ¡c cá»™t phá»¥c vá»¥ S-07, S-08, S-09."""
    with engine.begin() as connection:
        # --------------------------------------------------------
        # Báº£ng products
        # --------------------------------------------------------
        connection.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id INTEGER NOT NULL,
                name VARCHAR(255) NOT NULL,
                code VARCHAR(50) NOT NULL,
                active BOOLEAN NOT NULL DEFAULT 1,
                FOREIGN KEY (organization_id) REFERENCES organizations(id)
            )
            """
        )

        connection.exec_driver_sql(
            """
            CREATE INDEX IF NOT EXISTS ix_products_organization_id
            ON products (organization_id)
            """
        )

        connection.exec_driver_sql(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_products_org_code
            ON products (organization_id, code)
            """
        )

        # --------------------------------------------------------
        # Báº£ng units
        # --------------------------------------------------------
        connection.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS units (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id INTEGER NOT NULL,
                name VARCHAR(50) NOT NULL,
                symbol VARCHAR(20) NOT NULL,
                active BOOLEAN NOT NULL DEFAULT 1,
                FOREIGN KEY (organization_id) REFERENCES organizations(id)
            )
            """
        )

        connection.exec_driver_sql(
            """
            CREATE INDEX IF NOT EXISTS ix_units_organization_id
            ON units (organization_id)
            """
        )

        connection.exec_driver_sql(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_units_org_symbol
            ON units (organization_id, symbol)
            """
        )

        # --------------------------------------------------------
        # CÃ¡c cá»™t má»›i cá»§a batches
        # --------------------------------------------------------
        existing_batches = {
            row[1]
            for row in connection.exec_driver_sql(
                "PRAGMA table_info(batches)"
            )
        }

        if existing_batches:
            if "batch_code" not in existing_batches:
                connection.exec_driver_sql(
                    "ALTER TABLE batches ADD COLUMN batch_code VARCHAR(8)"
                )

            if "product_id" not in existing_batches:
                connection.exec_driver_sql(
                    "ALTER TABLE batches ADD COLUMN product_id INTEGER "
                    "REFERENCES products(id)"
                )

            if "unit_id" not in existing_batches:
                connection.exec_driver_sql(
                    "ALTER TABLE batches ADD COLUMN unit_id INTEGER "
                    "REFERENCES units(id)"
                )

            connection.exec_driver_sql(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS ix_batches_batch_code
                ON batches (batch_code)
                WHERE batch_code IS NOT NULL
                """
            )

            connection.exec_driver_sql(
                """
                CREATE INDEX IF NOT EXISTS ix_batches_product_id
                ON batches (product_id)
                """
            )

            connection.exec_driver_sql(
                """
                CREATE INDEX IF NOT EXISTS ix_batches_unit_id
                ON batches (unit_id)
                """
            )
