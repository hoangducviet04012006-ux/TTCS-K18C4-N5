"""Test nâng cấp database cũ (Sprint 6): thêm 2 cột bảo mật cho bảng ``users``.

Database tạo từ Sprint 4 chưa có ``failed_login_attempts`` / ``locked_until``,
mà ``create_all()`` không thêm cột vào bảng đã tồn tại -> người dùng phải xoá
file ``ttcs.db`` nếu không có migration. Test này mô phỏng đúng tình huống đó và
kiểm tra dữ liệu tài khoản cũ vẫn còn nguyên sau khi nâng cấp.
"""

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import sessionmaker

from app import database


def _create_legacy_users_table(engine: Engine) -> None:
    """Tạo bảng ``users`` đúng như schema Sprint 4 (thiếu 2 cột bảo mật)."""
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE users ("
            "id INTEGER NOT NULL PRIMARY KEY, "
            "username VARCHAR(50) NOT NULL UNIQUE, "
            "password VARCHAR(64) NOT NULL, "
            "role VARCHAR(20) NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO users (username, password, role) "
            "VALUES ('admin', 'hash-cu', 'admin')"
        )


def test_migration_them_hai_cot_va_khong_mat_du_lieu(tmp_path, monkeypatch) -> None:
    """Sau migration: đủ 2 cột, tài khoản cũ còn nguyên, giá trị mặc định hợp lý."""
    legacy_engine = create_engine(f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}")
    _create_legacy_users_table(legacy_engine)

    # Chạy migration trên database "cũ" (không đụng tới ``backend/ttcs.db``).
    monkeypatch.setattr(database, "engine", legacy_engine)
    database.migrate_user_security_columns()

    with legacy_engine.begin() as connection:
        columns = {
            row[1] for row in connection.exec_driver_sql("PRAGMA table_info(users)")
        }
        row = connection.execute(
            text("SELECT username, failed_login_attempts, locked_until FROM users")
        ).one()

    assert {"failed_login_attempts", "locked_until"} <= columns
    # Tài khoản cũ vẫn còn, mặc định "chưa từng đăng nhập sai" và "không bị khoá".
    assert row == ("admin", 0, None)

    legacy_engine.dispose()


def test_migration_an_toan_khi_chay_lai_nhieu_lan(tmp_path, monkeypatch) -> None:
    """Gọi migration lần 2 (mỗi lần server khởi động) không được lỗi duplicate column."""
    legacy_engine = create_engine(f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}")
    _create_legacy_users_table(legacy_engine)

    monkeypatch.setattr(database, "engine", legacy_engine)
    database.migrate_user_security_columns()
    database.migrate_user_security_columns()  # gọi lại vẫn phải chạy êm

    with legacy_engine.begin() as connection:
        columns = [
            row[1] for row in connection.exec_driver_sql("PRAGMA table_info(users)")
        ]

    # Mỗi cột chỉ xuất hiện đúng 1 lần.
    assert columns.count("failed_login_attempts") == 1
    assert columns.count("locked_until") == 1

    legacy_engine.dispose()


def test_migration_bo_qua_khi_chua_co_bang(tmp_path, monkeypatch) -> None:
    """Database trắng (chưa có bảng ``users``) -> bỏ qua, để ``create_all()`` lo."""
    empty_engine = create_engine(f"sqlite:///{(tmp_path / 'empty.db').as_posix()}")
    monkeypatch.setattr(database, "engine", empty_engine)

    database.migrate_user_security_columns()  # không được raise lỗi

    with empty_engine.begin() as connection:
        tables = {
            row[0]
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert "users" not in tables
    empty_engine.dispose()


def test_init_db_tao_them_bang_audit_logs_cho_database_cu(tmp_path, monkeypatch) -> None:
    """Database cũ (Sprint 6) chưa có bảng ``audit_logs`` -> ``init_db()`` tự tạo thêm.

    ``Base.metadata.create_all()`` tạo bảng *mới* kể cả khi file database đã tồn
    tại, nên người dùng chỉ cần khởi động lại server là có bảng lịch sử thao tác
    (Sprint 7) - **không** phải xoá ``ttcs.db`` và **không** mất dữ liệu cũ.
    """
    legacy_engine = create_engine(f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}")
    _create_legacy_users_table(legacy_engine)

    monkeypatch.setattr(database, "engine", legacy_engine)
    monkeypatch.setattr(
        database,
        "SessionLocal",
        sessionmaker(bind=legacy_engine, autocommit=False, autoflush=False),
    )

    database.init_db()

    with legacy_engine.begin() as connection:
        tables = {
            row[0]
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        audit_columns = [
            row[1]
            for row in connection.exec_driver_sql("PRAGMA table_info(audit_logs)")
        ]
        user_columns = {
            row[1] for row in connection.exec_driver_sql("PRAGMA table_info(users)")
        }
        usernames = {
            row[0] for row in connection.exec_driver_sql("SELECT username FROM users")
        }

    # Bảng mới của Sprint 7 được tạo thêm, đủ 6 cột theo yêu cầu.
    assert "audit_logs" in tables
    assert audit_columns == [
        "id",
        "user_id",
        "action",
        "entity",
        "entity_id",
        "created_at",
    ]
    # Database cũ vẫn được nâng cấp 2 cột bảo mật và giữ nguyên tài khoản đang có.
    assert {"failed_login_attempts", "locked_until"} <= user_columns
    assert usernames == {"admin", "farmer"}

    legacy_engine.dispose()
