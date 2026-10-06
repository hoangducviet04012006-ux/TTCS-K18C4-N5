"""Test bảo mật đăng nhập: Đăng nhập bằng Email, khoá tài khoản 15 phút sau 5 lần sai.

Bao phủ các yêu cầu:
1. Đăng nhập bằng Email + Password đúng -> thành công (HTTP 200).
2. Sai mật khẩu:
   - Lần 1 -> failed_login_attempts = 1
   - Lần 2 -> failed_login_attempts = 2
   - Lần 3 -> failed_login_attempts = 3
   - Lần 4 -> failed_login_attempts = 4 (HTTP 401, chưa khoá)
   - Lần 5 -> tài khoản bị tạm khoá 15 phút (HTTP 403).
3. Đang bị khoá: nhập đúng mật khẩu vẫn bị từ chối (HTTP 403).
4. Sau khi hết 15 phút -> đăng nhập lại được và reset failed_login_attempts về 0.
5. Email không tồn tại -> HTTP 401.

Chạy: ``python -m pytest`` (từ thư mục ``backend``).
"""

from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import User
from app.security import LOCKOUT_DURATION, MAX_FAILED_LOGIN_ATTEMPTS, utcnow
from tests.conftest import (
    TEST_EMAIL_ADMIN,
    TEST_EMAIL_FARMER,
    TEST_PASSWORD,
    TEST_USERNAME_ADMIN,
    TEST_USERNAME_FARMER,
)

LOGIN_URL = "/auth/login"
WRONG_PASSWORD = "mat-khau-sai"
INVALID_CREDENTIALS_MESSAGE = "Sai email hoặc mật khẩu."


# ------------------------------------------------------------------- Helper ---
def login(client: TestClient, email: str, password: str):
    """Gọi ``POST /auth/login`` với body JSON."""
    return client.post(LOGIN_URL, json={"email": email, "password": password})


def lock_state(
    session_factory: sessionmaker[Session], email_or_username: str
) -> tuple[int, datetime | None]:
    """Đọc trực tiếp ``(failed_login_attempts, locked_until)`` từ database."""
    with session_factory() as session:
        user = session.scalar(
            select(User).where(
                (User.email == email_or_username) | (User.username == email_or_username)
            )
        )
        assert user is not None, f"Không tìm thấy tài khoản {email_or_username!r} trong database test"
        return user.failed_login_attempts, user.locked_until


def set_locked_until(
    session_factory: sessionmaker[Session],
    email_or_username: str,
    moment: datetime,
) -> None:
    """Giả lập thời gian trôi qua: đặt ``locked_until`` về một mốc cụ thể."""
    with session_factory() as session:
        user = session.scalar(
            select(User).where(
                (User.email == email_or_username) | (User.username == email_or_username)
            )
        )
        assert user is not None
        user.locked_until = moment
        session.commit()


# ------------------------------------------- 1. Đăng nhập đúng bằng Email ---
def test_email_password_dung_dang_nhap_thanh_cong(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """1. Email + password đúng → đăng nhập thành công (HTTP 200)."""
    response = login(client, TEST_EMAIL_ADMIN, TEST_PASSWORD)

    assert response.status_code == 200
    data = response.json()
    assert data["email"] == TEST_EMAIL_ADMIN
    assert data["username"] == TEST_USERNAME_ADMIN
    assert data["role"] == "admin"
    assert "organization_id" in data
    assert lock_state(session_factory, TEST_EMAIL_ADMIN) == (0, None)


def test_login_farmer_email_thanh_cong(client: TestClient) -> None:
    """Tài khoản farmer đăng nhập bằng email thành công."""
    response = login(client, TEST_EMAIL_FARMER, TEST_PASSWORD)

    assert response.status_code == 200
    data = response.json()
    assert data["email"] == TEST_EMAIL_FARMER
    assert data["username"] == TEST_USERNAME_FARMER
    assert data["role"] == "farmer"


# ------------------------------------------- 2. Sai mật khẩu lần 1 -> 4 ---
def test_sai_mat_khau_lan_1_failed_login_attempts_bang_1(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """Sai mật khẩu lần 1 → failed_login_attempts = 1."""
    response = login(client, TEST_EMAIL_ADMIN, WRONG_PASSWORD)
    assert response.status_code == 401
    assert response.json()["detail"] == INVALID_CREDENTIALS_MESSAGE
    attempts, locked_until = lock_state(session_factory, TEST_EMAIL_ADMIN)
    assert attempts == 1
    assert locked_until is None


def test_sai_mat_khau_lan_2_failed_login_attempts_bang_2(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """Sai mật khẩu lần 2 → failed_login_attempts = 2."""
    login(client, TEST_EMAIL_ADMIN, WRONG_PASSWORD)
    response = login(client, TEST_EMAIL_ADMIN, WRONG_PASSWORD)
    assert response.status_code == 401
    attempts, locked_until = lock_state(session_factory, TEST_EMAIL_ADMIN)
    assert attempts == 2
    assert locked_until is None


def test_sai_mat_khau_lan_3_failed_login_attempts_bang_3(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """Sai mật khẩu lần 3 → failed_login_attempts = 3."""
    for _ in range(2):
        login(client, TEST_EMAIL_ADMIN, WRONG_PASSWORD)
    response = login(client, TEST_EMAIL_ADMIN, WRONG_PASSWORD)
    assert response.status_code == 401
    attempts, locked_until = lock_state(session_factory, TEST_EMAIL_ADMIN)
    assert attempts == 3
    assert locked_until is None


def test_sai_mat_khau_lan_4_failed_login_attempts_bang_4(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """Sai mật khẩu lần 4 → failed_login_attempts = 4."""
    for _ in range(3):
        login(client, TEST_EMAIL_ADMIN, WRONG_PASSWORD)
    response = login(client, TEST_EMAIL_ADMIN, WRONG_PASSWORD)
    assert response.status_code == 401
    attempts, locked_until = lock_state(session_factory, TEST_EMAIL_ADMIN)
    assert attempts == 4
    assert locked_until is None


# --------------------------------- 3. Sai 5 lần liên tiếp -> khoá tài khoản 15 phút ---
def test_sai_mat_khau_lan_5_tai_khoan_bi_khoa_15_phut_tra_403(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """Sai lần 5 → tài khoản bị khóa tạm thời 15 phút (HTTP 403)."""
    for _ in range(4):
        login(client, TEST_EMAIL_ADMIN, WRONG_PASSWORD)

    response = login(client, TEST_EMAIL_ADMIN, WRONG_PASSWORD)

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert "Tài khoản đã bị khóa tạm thời do đăng nhập sai quá 5 lần." in detail or (
        "khóa tạm thời" in detail and "5 lần" in detail
    )
    # Header Retry-After (giây) cho client biết cần chờ bao lâu.
    assert int(response.headers["Retry-After"]) > 0

    # Database lưu số lần sai = 5 và thời điểm mở khoá (15 phút).
    attempts, locked_until = lock_state(session_factory, TEST_EMAIL_ADMIN)
    assert attempts == MAX_FAILED_LOGIN_ATTEMPTS == 5
    assert locked_until is not None
    thoi_gian_con_lai = locked_until - utcnow()
    assert timedelta(seconds=0) < thoi_gian_con_lai <= LOCKOUT_DURATION


# --------------------------------- 4. Đang bị khóa nhập đúng vẫn bị từ chối ---
def test_dang_bi_khoa_nhap_dung_password_van_bi_tu_choi(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """Đang bị khóa nhưng nhập đúng password → vẫn bị từ chối (HTTP 403)."""
    for _ in range(MAX_FAILED_LOGIN_ATTEMPTS):
        login(client, TEST_EMAIL_ADMIN, WRONG_PASSWORD)

    response = login(client, TEST_EMAIL_ADMIN, TEST_PASSWORD)
    assert response.status_code == 403
    assert "khóa" in response.json()["detail"] or "khoá" in response.json()["detail"]

    # Bị chặn trong lúc khoá thì không được xoá bộ đếm.
    attempts, locked_until = lock_state(session_factory, TEST_EMAIL_ADMIN)
    assert attempts == MAX_FAILED_LOGIN_ATTEMPTS == 5
    assert locked_until is not None

    # Tài khoản khác không bị ảnh hưởng.
    assert login(client, TEST_EMAIL_FARMER, TEST_PASSWORD).status_code == 200


def test_tai_khoan_bi_khoa_khong_goi_duoc_api_can_quyen(client: TestClient) -> None:
    """Khoá không chỉ áp ở /auth/login: API cần quyền (HTTP Basic) cũng trả 403."""
    for _ in range(MAX_FAILED_LOGIN_ATTEMPTS):
        login(client, TEST_EMAIL_ADMIN, WRONG_PASSWORD)

    response = client.get("/farms", auth=(TEST_EMAIL_ADMIN, TEST_PASSWORD))

    assert response.status_code == 403
    assert "khóa" in response.json()["detail"] or "khoá" in response.json()["detail"]


# --------------------------------- 5. Sau khi hết 15 phút -> đăng nhập lại ---
def test_sau_khi_het_15_phut_co_the_dang_nhap_lai(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """Sau khi hết 15 phút → có thể đăng nhập lại."""
    for _ in range(MAX_FAILED_LOGIN_ATTEMPTS):
        login(client, TEST_EMAIL_ADMIN, WRONG_PASSWORD)
    assert login(client, TEST_EMAIL_ADMIN, TEST_PASSWORD).status_code == 403  # đang khoá

    # Thời điểm mở khoá đã ở quá khứ = đã hết 15 phút.
    set_locked_until(session_factory, TEST_EMAIL_ADMIN, utcnow() - timedelta(seconds=1))

    response = login(client, TEST_EMAIL_ADMIN, TEST_PASSWORD)

    assert response.status_code == 200
    data = response.json()
    assert data["email"] == TEST_EMAIL_ADMIN
    assert data["role"] == "admin"


# --------------------------------- 6. Đăng nhập thành công -> reset failed attempts ---
def test_dang_nhap_thanh_cong_reset_failed_login_attempts_ve_0(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """Đăng nhập thành công → failed_login_attempts được reset về 0."""
    # Thử sai 3 lần
    for _ in range(3):
        login(client, TEST_EMAIL_ADMIN, WRONG_PASSWORD)
    attempts, _ = lock_state(session_factory, TEST_EMAIL_ADMIN)
    assert attempts == 3

    # Đăng nhập thành công
    resp = login(client, TEST_EMAIL_ADMIN, TEST_PASSWORD)
    assert resp.status_code == 200
    assert lock_state(session_factory, TEST_EMAIL_ADMIN) == (0, None)


def test_sau_khi_het_khoa_bo_dem_sai_bat_dau_lai_tu_dau(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """Sau khi hết khoá, một lần sai mới chỉ tính là 1 (không bị khoá lại ngay)."""
    for _ in range(MAX_FAILED_LOGIN_ATTEMPTS):
        login(client, TEST_EMAIL_ADMIN, WRONG_PASSWORD)
    set_locked_until(session_factory, TEST_EMAIL_ADMIN, utcnow() - timedelta(seconds=1))

    response = login(client, TEST_EMAIL_ADMIN, WRONG_PASSWORD)

    assert response.status_code == 401  # đã mở khoá, chỉ là sai mật khẩu
    assert lock_state(session_factory, TEST_EMAIL_ADMIN) == (1, None)


def test_email_khong_ton_tai_van_tra_401(client: TestClient) -> None:
    """Email không tồn tại: trả 401, không lộ thông tin."""
    response = login(client, "khong-ton-tai@gmail.com", WRONG_PASSWORD)

    assert response.status_code == 401
    assert response.json()["detail"] == INVALID_CREDENTIALS_MESSAGE
