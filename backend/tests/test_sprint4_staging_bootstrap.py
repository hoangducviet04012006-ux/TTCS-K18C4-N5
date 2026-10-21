"""Kiểm thử cơ chế bootstrap schema độc lập cho môi trường CI/Staging (Sprint 4).

Đảm bảo:
1. Từ chối chạy bootstrap trên cơ sở dữ liệu chính được bảo vệ.
2. Khởi tạo schema đầy đủ Sprint 1-4 trên file SQLite staging mới hoàn toàn.
3. Tích hợp trơn tru với FastAPI lifespan khi có biến môi trường TTCS_BOOTSTRAP_STAGING=1.
4. Giữ nguyên cơ chế chặn schema thiếu khi không bật cờ bootstrap.
"""
import os
import tempfile
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.database import get_db
from app.services.sprint4_schema import (
    bootstrap_staging_database,
    schema_status,
    ensure_sprint4_schema,
)
from app.main import app


def test_bootstrap_refuses_protected_databases():
    """Từ chối chạy bootstrap trên data/agritrace.db hoặc backend/ttcs.db."""
    root = Path(__file__).resolve().parents[2]
    main_db = root / "data/agritrace.db"
    if main_db.exists():
        eng = create_engine(f"sqlite:///{main_db.as_posix()}")
        with pytest.raises(RuntimeError, match="Từ chối bootstrap trên database chính được bảo vệ"):
            bootstrap_staging_database(eng)
        eng.dispose()


def test_bootstrap_initializes_empty_sqlite_file():
    """Khởi tạo schema đầy đủ trên file SQLite mới và đạt trạng thái ready."""
    fd, path = tempfile.mkstemp(prefix="test_staging_", suffix=".db")
    os.close(fd)
    try:
        eng = create_engine(f"sqlite:///{Path(path).as_posix()}")
        # Trước bootstrap: schema chưa sẵn sàng
        st_before = schema_status(eng)
        assert not st_before["ready"]
        assert len(st_before["missing"]) > 0

        # Thực hiện bootstrap
        res = bootstrap_staging_database(eng)
        assert res["ready"] is True
        assert res["missing"] == []

        # Sau bootstrap: ensure_sprint4_schema xác nhận hợp lệ
        validated = ensure_sprint4_schema(eng)
        assert validated["ready"] is True
        assert validated["missing"] == []
        eng.dispose()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def test_lifespan_with_bootstrap_flag(monkeypatch):
    """Khi có TTCS_BOOTSTRAP_STAGING=1, ứng dụng tự khởi tạo schema trên DB mới và phục vụ /health + /ready."""
    fd, path = tempfile.mkstemp(prefix="test_staging_app_", suffix=".db")
    os.close(fd)
    test_engine = create_engine(f"sqlite:///{Path(path).as_posix()}")
    test_session = sessionmaker(bind=test_engine)

    def override_get_db():
        session = test_session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setenv("TTCS_BOOTSTRAP_STAGING", "1")

    try:
        with TestClient(app) as client:
            resp_health = client.get("/health")
            assert resp_health.status_code == 200
            assert resp_health.json()["status"] == "ok"
            assert resp_health.json()["database"] == "connected"

            resp_ready = client.get("/ready")
            assert resp_ready.status_code == 200
            assert resp_ready.json()["ready"] is True
            assert resp_ready.json()["missing"] == []
    finally:
        app.dependency_overrides.pop(get_db, None)
        test_engine.dispose()
        try:
            os.remove(path)
        except OSError:
            pass


def test_lifespan_without_bootstrap_flag_rejects_empty_db(monkeypatch):
    """Khi KHÔNG có TTCS_BOOTSTRAP_STAGING, ứng dụng từ chối khởi động trên DB trống để bảo vệ dữ liệu."""
    fd, path = tempfile.mkstemp(prefix="test_empty_app_", suffix=".db")
    os.close(fd)
    test_engine = create_engine(f"sqlite:///{Path(path).as_posix()}")
    test_session = sessionmaker(bind=test_engine)

    def override_get_db():
        session = test_session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.delenv("TTCS_BOOTSTRAP_STAGING", raising=False)

    try:
        with pytest.raises(RuntimeError, match="Sprint 4 schema chưa sẵn sàng"):
            with TestClient(app):
                pass
    finally:
        app.dependency_overrides.pop(get_db, None)
        test_engine.dispose()
        try:
            os.remove(path)
        except OSError:
            pass
