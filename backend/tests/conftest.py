"""Fixture dùng chung cho bộ test backend (pytest).

Mỗi test chạy trên một database SQLite **in-memory** riêng và được cô lập với
file thật ``backend/ttcs.db``: dependency ``get_db`` được override nên request
trong test không đọc/ghi dữ liệu demo.

Chạy test từ thư mục ``backend``::

    python -m pytest
"""

import os
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base, get_db
from app.main import app
from app.models import ROLE_ADMIN, ROLE_FARMER, User
from app.security import hash_password

# Mật khẩu của tài khoản test (giống tài khoản demo của dự án).
TEST_PASSWORD = "123456"

# Tên 2 tài khoản test - trùng với tài khoản demo do `seed_default_users()` tạo.
TEST_USERNAME_ADMIN = "admin"
TEST_USERNAME_FARMER = "farmer"

# Email của 2 tài khoản test (S-04: dùng để kiểm thử đăng nhập bằng email).
TEST_EMAIL_ADMIN = "admin@gmail.com"
TEST_EMAIL_FARMER = "farmer@gmail.com"


@pytest.fixture(autouse=True)
def local_seed_environment(monkeypatch):
    monkeypatch.setenv("TTCS_ENV", "test")
    monkeypatch.setenv("DEMO_PASSWORD", TEST_PASSWORD)


@pytest.fixture()
def engine() -> Generator[Engine, None, None]:
    """Engine SQLite trên **file tạm** (nhiều kết nối) cho mỗi test.

    Dùng file tạm thay vì in-memory ``StaticPool`` (chỉ 1 kết nối dùng chung) để
    các bài kiểm thử đồng thời (tách lô race condition) thực sự chạy trên nhiều
    kết nối - phản ánh đúng môi trường production và tránh làm hỏng transaction
    của nhau. File được tạo/xoá riêng cho từng test, hoàn toàn không đụng tới
    ``backend/ttcs.db``.
    """
    fd, db_path = tempfile.mkstemp(prefix="ttcs_test_", suffix=".db")
    os.close(fd)
    test_engine = create_engine(
        f"sqlite:///{Path(db_path).as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=test_engine)
    from app.database import create_event_immutability_triggers
    create_event_immutability_triggers(test_engine)
    try:
        yield test_engine
    finally:
        test_engine.dispose()
        try:
            os.remove(db_path)
        except OSError:
            pass


@pytest.fixture()
def session_factory(engine: Engine) -> sessionmaker[Session]:
    """Factory tạo Session mới cho mỗi request (giống ``SessionLocal`` thật)."""
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


@pytest.fixture()
def users(session_factory: sessionmaker[Session], monkeypatch) -> list[str]:
    """Tạo sẵn tổ chức mặc định và 2 tài khoản test (``admin`` + ``farmer``, mật khẩu ``123456``)."""
    monkeypatch.setenv("DEMO_PASSWORD", TEST_PASSWORD)
    monkeypatch.setenv("TTCS_ENV", "test")
    from app.models import Organization
    with session_factory() as session:
        org = Organization(
            id=1,
            name="Hợp tác xã Nông sản An Toàn Đồng Tháp",
            code="HTX-DT",
            description="Tổ chức mặc định cho kiểm thử",
        )
        session.add(org)
        session.flush()

        session.add_all(
            [
                User(
                    username=TEST_USERNAME_ADMIN,
                    email=TEST_EMAIL_ADMIN,
                    password=hash_password(TEST_PASSWORD),
                    role=ROLE_ADMIN,
                    organization_id=org.id,
                ),
                User(
                    username=TEST_USERNAME_FARMER,
                    email=TEST_EMAIL_FARMER,
                    password=hash_password(TEST_PASSWORD),
                    role=ROLE_FARMER,
                    organization_id=org.id,
                ),
            ]
        )
        session.commit()

    return [TEST_USERNAME_ADMIN, TEST_USERNAME_FARMER]


@pytest.fixture()
def client(
    session_factory: sessionmaker[Session],
    users: list[str],
) -> Generator[TestClient, None, None]:
    """``TestClient`` của FastAPI dùng database in-memory thay cho database thật.

    Cố tình **không** dùng ``with TestClient(app)`` để bỏ qua ``lifespan`` ->
    ``init_db()`` không chạy, nhờ đó file ``backend/ttcs.db`` không bị đụng tới.
    """

    def override_get_db() -> Generator[Session, None, None]:
        session: Session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
