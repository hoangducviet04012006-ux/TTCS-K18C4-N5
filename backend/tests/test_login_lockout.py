"""Test Sprint 6 - bảo mật đăng nhập: khoá tài khoản khi nhập sai quá nhiều lần.

Bao phủ 3 yêu cầu:

1. Đăng nhập đúng vẫn hoạt động bình thường (không phá vỡ chức năng cũ).
2. Nhập sai mật khẩu 5 lần liên tiếp -> khoá tài khoản 5 phút + HTTP **403** kèm
   message rõ ràng, số lần sai được lưu trong database.
3. Hết thời gian khoá -> đăng nhập lại được (bộ đếm cũng được xoá).

Chạy: ``python -m pytest`` (từ thư mục ``backend``).
"""

from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import User
from app.security import LOCKOUT_DURATION, MAX_FAILED_LOGIN_ATTEMPTS, utcnow
from tests.conftest import TEST_PASSWORD, TEST_EMAIL_ADMIN, TEST_EMAIL_FARMER

LOGIN_URL = "/auth/login"
WRONG_PASSWORD = "mat-khau-sai"
INVALID_CREDENTIALS_MESSAGE = "Sai tên đăng nhập hoặc mật khẩu."


# ------------------------------------------------------------------- Helper ---
def login(client: TestClient, email: str, password: str):
    """Gọi ``POST /auth/login`` với body JSON cho gọn."""
    return client.post(LOGIN_URL, json={"email": email, "password": password})


def lock_state(
    session_factory: sessionmaker[Session], email: str
) -> tuple[int, datetime | None]:
    """Đọc trực tiếp ``(failed_login_attempts, locked_until)`` từ database.

    Dùng một session mới để chắc chắn đọc được giá trị mà request vừa ghi.
    """
    with session_factory() as session:
        user = session.scalar(select(User).where(User.email == email))
        assert user is not None, f"Không tìm thấy tài khoản {email!r} trong database test"
        return user.failed_login_attempts, user.locked_until


def set_locked_until(
    session_factory: sessionmaker[Session],
    email: str,
    moment: datetime,
) -> None:
    """Giả lập thời gian trôi qua: đặt ``locked_until`` về một mốc cụ thể."""
    with session_factory() as session:
        user = session.scalar(select(User).where(User.email == email))
        assert user is not None
        user.locked_until = moment
        session.commit()


# ------------------------------------------- 1. Đăng nhập đúng vẫn hoạt động ---
def test_login_dung_van_hoat_dong(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """Đăng nhập đúng -> 200 + ``{email, role}``, không dính bộ đếm sai."""
    response = login(client, TEST_EMAIL_ADMIN, TEST_PASSWORD)

    assert response.status_code == 200
    data = response.json()
    assert data["email"] == TEST_EMAIL_ADMIN
    assert data["role"] == "admin"
    assert "organization_id" in data
    assert lock_state(session_factory, TEST_EMAIL_ADMIN) == (0, None)


def test_login_farmer_van_hoat_dong(client: TestClient) -> None:
    """Tài khoản farmer đăng nhập vẫn trả đúng role (không bị ảnh hưởng)."""
    response = login(client, TEST_EMAIL_FARMER, TEST_PASSWORD)

    assert response.status_code == 200
    data = response.json()
    assert data["email"] == TEST_EMAIL_FARMER
    assert data["role"] == "farmer"


def test_sai_bon_lan_chua_khoa_va_dem_dung_so_lan(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """Sai 4 lần liên tiếp: vẫn là 401 (chưa khoá) nhưng đã lưu số lần sai."""
    for lan_thu in range(1, MAX_FAILED_LOGIN_ATTEMPTS):
        response = login(client, TEST_EMAIL_ADMIN, WRONG_PASSWORD)
        assert response.status_code == 401, f"lần sai thứ {lan_thu} phải trả 401"
        assert response.json()["detail"] == INVALID_CREDENTIALS_MESSAGE

    attempts, locked_until = lock_state(session_factory, TEST_EMAIL_ADMIN)
    assert attempts == MAX_FAILED_LOGIN_ATTEMPTS - 1 == 4
    assert locked_until is None

    # Đăng nhập đúng -> 200 và bộ đếm được xoá về 0.
    assert login(client, TEST_EMAIL_ADMIN, TEST_PASSWORD).status_code == 200
    assert lock_state(session_factory, TEST_EMAIL_ADMIN) == (0, None)


# --------------------------------- 2. Sai 5 lần liên tiếp -> khoá 5 phút (403) ---
def test_sai_nam_lan_lien_tiep_bi_khoa_va_tra_403(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """Lần sai thứ 5: khoá tài khoản + trả 403 kèm message rõ ràng."""
    for _ in range(MAX_FAILED_LOGIN_ATTEMPTS - 1):
        assert login(client, TEST_EMAIL_ADMIN, WRONG_PASSWORD).status_code == 401

    response = login(client, TEST_EMAIL_ADMIN, WRONG_PASSWORD)

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert TEST_EMAIL_ADMIN in detail
    assert "tạm khoá" in detail
    assert f"{MAX_FAILED_LOGIN_ATTEMPTS} lần liên tiếp" in detail
    assert "Vui lòng thử lại sau" in detail
    # Header Retry-After (giây) cho client biết cần chờ bao lâu.
    assert int(response.headers["Retry-After"]) > 0

    # Database lưu số lần sai và thời điểm mở khoá (≈ 5 phút kể từ lúc khoá).
    attempts, locked_until = lock_state(session_factory, TEST_EMAIL_ADMIN)
    assert attempts == MAX_FAILED_LOGIN_ATTEMPTS == 5
    assert locked_until is not None
    thoi_gian_con_lai = locked_until - utcnow()
    assert timedelta(seconds=0) < thoi_gian_con_lai <= LOCKOUT_DURATION


def test_trong_thoi_gian_khoa_dung_mat_khau_cung_bi_chan(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """Đang bị khoá: kể cả mật khẩu đúng cũng nhận 403, tài khoản khác vẫn vào được."""
    for _ in range(MAX_FAILED_LOGIN_ATTEMPTS):
        login(client, TEST_EMAIL_ADMIN, WRONG_PASSWORD)

    response = login(client, TEST_EMAIL_ADMIN, TEST_PASSWORD)
    assert response.status_code == 403
    assert "tạm khoá" in response.json()["detail"]

    # Bị chặn trong lúc khoá thì không được xoá bộ đếm.
    attempts, locked_until = lock_state(session_factory, TEST_EMAIL_ADMIN)
    assert attempts == MAX_FAILED_LOGIN_ATTEMPTS
    assert locked_until is not None

    # Khoá theo từng tài khoản -> tài khoản khác không bị ảnh hưởng.
    assert login(client, TEST_EMAIL_FARMER, TEST_PASSWORD).status_code == 200


def test_tai_khoan_bi_khoa_khong_goi_duoc_api_can_quyen(client: TestClient) -> None:
    """Khoá không chỉ áp ở /auth/login: API cần quyền (HTTP Basic) cũng trả 403."""
    for _ in range(MAX_FAILED_LOGIN_ATTEMPTS):
        login(client, TEST_EMAIL_ADMIN, WRONG_PASSWORD)

    response = client.get("/farms", auth=(TEST_EMAIL_ADMIN, TEST_PASSWORD))

    assert response.status_code == 403
    assert "tạm khoá" in response.json()["detail"]


# -------------------------------------- 3. Hết thời gian khoá -> đăng nhập lại ---
def test_het_thoi_gian_khoa_dang_nhap_lai_duoc(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """Giả lập đã qua 5 phút -> tài khoản được mở khoá và đăng nhập lại được."""
    for _ in range(MAX_FAILED_LOGIN_ATTEMPTS):
        login(client, TEST_EMAIL_ADMIN, WRONG_PASSWORD)
    assert login(client, TEST_EMAIL_ADMIN, TEST_PASSWORD).status_code == 403  # đang khoá

    # Thời điểm mở khoá đã ở quá khứ = đã hết 5 phút.
    set_locked_until(session_factory, TEST_EMAIL_ADMIN, utcnow() - timedelta(seconds=1))

    response = login(client, TEST_EMAIL_ADMIN, TEST_PASSWORD)

    assert response.status_code == 200
    data = response.json()
    assert data["email"] == TEST_EMAIL_ADMIN
    assert data["role"] == "admin"
    # Hết khoá thì bộ đếm sai cũng được xoá.
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
    """Tài khoản không tồn tại: giữ nguyên hành vi cũ (401), không lộ thông tin."""
    response = login(client, "khong-ton-tai", WRONG_PASSWORD)

    assert response.status_code == 401
    assert response.json()["detail"] == INVALID_CREDENTIALS_MESSAGE
