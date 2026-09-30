"""Fixture dùng chung cho bộ test backend (pytest).

Mỗi test chạy trên một database SQLite **in-memory** riêng và được cô lập với
file thật ``backend/ttcs.db``: dependency ``get_db`` được override nên request
trong test không đọc/ghi dữ liệu demo.

Chạy test từ thư mục ``backend``::

    python -m pytest
"""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import ROLE_ADMIN, ROLE_FARMER, User
from app.security import hash_password

# Mật khẩu của tài khoản test (giống tài khoản demo của dự án).
TEST_PASSWORD = "123456"

# Tên 2 tài khoản test - trùng với tài khoản demo do `seed_default_users()` tạo.
TEST_USERNAME_ADMIN = "admin"
TEST_USERNAME_FARMER = "farmer"


@pytest.fixture()
def engine() -> Generator[Engine, None, None]:
    """Engine SQLite in-memory (``StaticPool`` để mọi session dùng chung 1 kết nối)."""
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=test_engine)
    try:
        yield test_engine
    finally:
        Base.metadata.drop_all(bind=test_engine)
        test_engine.dispose()


@pytest.fixture()
def session_factory(engine: Engine) -> sessionmaker[Session]:
    """Factory tạo Session mới cho mỗi request (giống ``SessionLocal`` thật)."""
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


@pytest.fixture()
def users(session_factory: sessionmaker[Session]) -> list[str]:
    """Tạo sẵn 2 tài khoản test (``admin`` + ``farmer``, mật khẩu ``123456``)."""
    with session_factory() as session:
        session.add_all(
            [
                User(
                    username=TEST_USERNAME_ADMIN,
                    password=hash_password(TEST_PASSWORD),
                    role=ROLE_ADMIN,
                ),
                User(
                    username=TEST_USERNAME_FARMER,
                    password=hash_password(TEST_PASSWORD),
                    role=ROLE_FARMER,
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
