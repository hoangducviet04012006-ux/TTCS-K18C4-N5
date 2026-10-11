"""Test S-04 - Đăng nhập bằng **email** và khoá tạm sau **5 lần sai**.

Bao phủ User Story S-04:

1. Đăng nhập thành công bằng **email** (kể cả khác hoa/thường) -> 200 + trả ``email``.
2. Đăng nhập bằng **tên đăng nhập** vẫn hoạt động (tương thích ngược).
3. Nhập sai mật khẩu **5 lần liên tiếp** (bằng email) -> tài khoản bị **tạm khoá**;
   lần thứ 6 (kể cả đúng mật khẩu, đăng nhập bằng email) nhận `403 Forbidden` kèm
   message rõ ràng -> đúng yêu cầu "khoá tạm tài khoản sau 5 lần nhập sai".
4. Đăng nhập thành công -> xoá bộ đếm sai.

Chạy: ``python -m pytest`` (từ thư mục ``backend``).
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import User
from app.security import MAX_FAILED_LOGIN_ATTEMPTS
from tests.conftest import (
    TEST_EMAIL_ADMIN,
    TEST_EMAIL_FARMER,
    TEST_PASSWORD,
    TEST_USERNAME_ADMIN,
    TEST_USERNAME_FARMER,
)

LOGIN_URL = "/auth/login"
WRONG_PASSWORD = "mat-khau-sai"


def login(client: TestClient, identifier: str, password: str):
    """Gọi ``POST /auth/login`` (``identifier`` = email hoặc username)."""
    return client.post(LOGIN_URL, json={"username": identifier, "password": password})


def lock_state(session_factory: sessionmaker[Session], username: str) -> tuple[int, object]:
    """Đọc trực tiếp ``(failed_login_attempts, locked_until)`` từ database."""
    with session_factory() as session:
        user = session.scalar(select(User).where(User.username == username))
        assert user is not None, f"Không tìm thấy tài khoản {username!r}"
        return user.failed_login_attempts, user.locked_until


# ------------------------------------------- 1. Đăng nhập bằng email thành công ---
def test_dang_nhap_bang_email_thanh_cong(client: TestClient) -> None:
    """Email hợp lệ + mật khẩu đúng -> 200 và trả kèm thông tin tài khoản."""
    response = login(client, TEST_EMAIL_ADMIN, TEST_PASSWORD)

    assert response.status_code == 200
    data = response.json()
    assert data["username"] == TEST_USERNAME_ADMIN
    assert data["email"] == TEST_EMAIL_ADMIN
    assert data["role"] == "admin"
    assert "organization_id" in data


def test_dang_nhap_bang_email_khong_phan_biet_hoa_thuong(client: TestClient) -> None:
    """Email so khớp không phân biệt hoa/thường (``ADMIN@GMAIL.COM``)."""
    response = login(client, TEST_EMAIL_ADMIN.upper(), TEST_PASSWORD)

    assert response.status_code == 200
    assert response.json()["username"] == TEST_USERNAME_ADMIN


def test_dang_nhap_bang_ten_dang_nhap_van_hoat_dong(client: TestClient) -> None:
    """Tương thích ngược: vẫn đăng nhập được bằng tên đăng nhập (không phải email)."""
    response = login(client, TEST_USERNAME_FARMER, TEST_PASSWORD)

    assert response.status_code == 200
    assert response.json()["username"] == TEST_USERNAME_FARMER


def test_email_khong_dung_mat_khau_tra_401(client: TestClient) -> None:
    """Email tồn tại nhưng sai mật khẩu -> 401 (chưa đủ ngưỡng khoá)."""
    response = login(client, TEST_EMAIL_ADMIN, WRONG_PASSWORD)

    assert response.status_code == 401


def test_email_khong_ton_tai_tra_401(client: TestClient) -> None:
    """Email không tồn tại -> 401, không lộ thông tin tài khoản tồn tại hay không."""
    response = login(client, "khong-ton-tai@gmail.com", WRONG_PASSWORD)

    assert response.status_code == 401


# ------------------------- 3. Sai 5 lần bằng email -> khoá tạm, lần 6 bị chặn ---
def test_sai_mat_khau_5_lan_bang_email_thi_bi_khoa(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """Sai 5 lần liên tiếp (bằng email) -> khoá tạm; lần thứ 6 (đúng mật khẩu) bị chặn."""
    # 4 lần đầu: chỉ 401 (chưa đủ ngưỡng khoá).
    for _ in range(MAX_FAILED_LOGIN_ATTEMPTS - 1):
        assert login(client, TEST_EMAIL_ADMIN, WRONG_PASSWORD).status_code == 401

    # Lần thứ 5: đạt ngưỡng -> 403 (vừa sai vừa bị khoá).
    lan_thu_5 = login(client, TEST_EMAIL_ADMIN, WRONG_PASSWORD)
    assert lan_thu_5.status_code == 403
    assert "tạm khoá" in lan_thu_5.json()["detail"]

    # Lần thứ 6: dù mật khẩu ĐÚNG và đăng nhập bằng email -> vẫn bị khoá (403).
    lan_thu_6 = login(client, TEST_EMAIL_ADMIN, TEST_PASSWORD)
    assert lan_thu_6.status_code == 403
    assert "tạm khoá" in lan_thu_6.json()["detail"]

    # Bộ đếm sai lưu theo tài khoản (mặc dù thao tác qua email).
    attempts, locked_until = lock_state(session_factory, TEST_USERNAME_ADMIN)
    assert attempts == MAX_FAILED_LOGIN_ATTEMPTS == 5
    assert locked_until is not None


def test_dang_nhap_thanh_cong_bang_email_xoa_bo_dem_sai(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """Sai vài lần rồi đăng nhập đúng bằng email -> bộ đếm sai được xoá về 0."""
    for _ in range(3):
        assert login(client, TEST_EMAIL_ADMIN, WRONG_PASSWORD).status_code == 401
    assert lock_state(session_factory, TEST_USERNAME_ADMIN)[0] == 3

    response = login(client, TEST_EMAIL_ADMIN, TEST_PASSWORD)

    assert response.status_code == 200
    assert lock_state(session_factory, TEST_USERNAME_ADMIN) == (0, None)


# ------------------------------------------------ 4. API trả về email tài khoản ---
def test_api_users_tra_ve_email(client: TestClient) -> None:
    """``GET /users`` (admin) trả kèm ``email`` của từng tài khoản."""
    response = client.get("/users", auth=(TEST_USERNAME_ADMIN, TEST_PASSWORD))

    assert response.status_code == 200
    by_username = {item["username"]: item for item in response.json()}
    assert by_username[TEST_USERNAME_ADMIN]["email"] == TEST_EMAIL_ADMIN
    assert by_username[TEST_USERNAME_FARMER]["email"] == TEST_EMAIL_FARMER


if __name__ == "__main__":  # pragma: no cover - cho phép chạy trực tiếp file test
    raise SystemExit(pytest.main([__file__, "-v"]))
