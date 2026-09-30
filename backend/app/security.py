"""Xác thực (authentication) và phân quyền (authorization) cơ bản - Sprint 4.

Nguyên tắc của sprint này: **đơn giản, chạy được demo, không JWT**.
- Không sinh token, không lưu session ở server, không refresh token.
- Client gửi kèm thông tin đăng nhập ở mỗi request theo chuẩn **HTTP Basic**:
  ``Authorization: Basic base64(username:password)``.
- ``POST /auth/login`` (xem ``app/routers/auth.py``) dùng cùng hàm kiểm tra
  bên dưới, chỉ để frontend biết ``username`` + ``role`` ngay sau khi đăng nhập.

Hai dependency phân quyền dùng cho các router::

    from app.security import require_farmer

    @router.post("/farms")
    def create_farm(user: User = Depends(require_farmer), ...):
        ...

Vì dùng ``HTTPBasic`` của FastAPI nên Swagger UI tự hiện nút **Authorize** và
có thể test quyền ngay trên ``/docs``.

Lưu ý bảo mật: chọn HTTP Basic + SHA-256 là để demo nhanh, **không dùng cho
production** (Basic gửi mật khẩu ở mọi request nên bắt buộc phải có HTTPS;
SHA-256 không salt nên không chống được brute-force - production nên dùng
``bcrypt``/``argon2`` qua ``passlib`` và chuyển sang JWT/OAuth2).

Sprint 6: thêm lớp chống dò mật khẩu dựa trên database: sai
``MAX_FAILED_LOGIN_ATTEMPTS`` (5) lần liên tiếp -> tài khoản bị tạm khoá
``LOCKOUT_DURATION`` (5 phút) bằng 2 cột ``users.failed_login_attempts`` và
``users.locked_until``.
"""

import hashlib
import math
from datetime import datetime, timedelta, timezone
from hmac import compare_digest

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ROLE_ADMIN, ROLE_FARMER, User

# ``auto_error=False`` để mình tự trả lỗi 401 với thông điệp tiếng Việt,
# thay vì để FastAPI trả "Not authenticated" (mặc định của HTTPBasic).
basic_scheme = HTTPBasic(auto_error=False)

# ------------------------------------------- Chống dò mật khẩu (Sprint 6) ---
# Chính sách: nhập sai mật khẩu liên tiếp quá `MAX_FAILED_LOGIN_ATTEMPTS` lần thì
# tài khoản bị **tạm khoá** `LOCKOUT_DURATION`. Chính sách được áp ở
# ``POST /auth/login`` (xem ``authenticate_user_with_lockout`` bên dưới) và khi
# tài khoản đang bị khoá thì mọi request cần quyền đều nhận **403**
# (xem ``get_current_user``).
MAX_FAILED_LOGIN_ATTEMPTS: int = 5
LOCKOUT_DURATION: timedelta = timedelta(minutes=5)


def utcnow() -> datetime:
    """Thời điểm hiện tại theo UTC nhưng **không** kèm ``tzinfo``.

    Cột ``users.locked_until`` là ``DateTime`` thường (SQLite không lưu offset),
    nên phải so sánh bằng naive datetime để tránh lỗi
    ``TypeError: can't compare offset-naive and offset-aware datetimes``.
    Dùng UTC (thay vì giờ local) để database không phụ thuộc múi giờ máy chạy.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AccountLockedError(Exception):
    """Tài khoản đang bị tạm khoá vì đăng nhập sai quá nhiều lần.

    Là lỗi nghiệp vụ (không phải ``HTTPException``) để tầng router quyết định
    mã HTTP - hiện tại ``POST /auth/login`` trả **403 Forbidden**.

    Attributes:
        username: Tên đăng nhập của tài khoản đang bị khoá.
        locked_until: Thời điểm tài khoản được mở khoá (UTC, naive).
    """

    def __init__(self, username: str, locked_until: datetime) -> None:
        self.username = username
        self.locked_until = locked_until
        super().__init__(build_lockout_message(username, locked_until))

# ------------------------------------------------------- Mật khẩu (hash) ---
def hash_password(raw_password: str) -> str:
    """Băm mật khẩu bằng SHA-256, trả về chuỗi hex 64 ký tự.

    Dùng ``hashlib`` của Python standard library nên **không cần cài thêm
    thư viện**. Database chỉ lưu giá trị đã băm, không lưu mật khẩu thô.

    Args:
        raw_password: Mật khẩu người dùng nhập (dạng thô).

    Returns:
        str: Mật khẩu đã băm, dạng hex.

    Note:
        Chỉ dùng cho demo: SHA-256 ở đây **không có salt** và tính rất nhanh
        nên không chống được brute-force/rainbow table.
    """
    return hashlib.sha256(raw_password.encode("utf-8")).hexdigest()


def verify_password(raw_password: str, hashed_password: str) -> bool:
    """So sánh mật khẩu người dùng nhập với mật khẩu đã băm trong database.

    Không so sánh bằng ``==`` mà dùng ``hmac.compare_digest`` (so sánh theo
    thời gian hằng) để tránh timing attack.
    """
    return compare_digest(hash_password(raw_password), hashed_password)


def authenticate_user(db: Session, username: str, password: str) -> User | None:
    """Tra bảng ``users`` và trả về tài khoản nếu thông tin đăng nhập đúng.

    Hàm **thuần xác thực**: không đếm số lần sai, cũng không kiểm tra khoá. Luồng
    đăng nhập có chống dò mật khẩu là ``authenticate_user_with_lockout`` bên dưới.

    Args:
        db: Session SQLAlchemy hiện tại.
        username: Tên đăng nhập.
        password: Mật khẩu dạng thô (hàm tự băm để so sánh).

    Returns:
        User | None: Tài khoản nếu hợp lệ, ``None`` nếu sai username **hoặc**
        sai mật khẩu (cố tình không phân biệt để tránh dò tài khoản).
    """
    user = db.scalar(select(User).where(User.username == username))
    if user is None or not verify_password(password, user.password):
        return None
    return user


# -------------------------- Số lần đăng nhập sai / tài khoản bị khoá (Sprint 6) ---
def get_user_by_username(db: Session, username: str) -> User | None:
    """Tra tài khoản theo ``username``; trả ``None`` nếu không tồn tại."""
    return db.scalar(select(User).where(User.username == username))


def is_account_locked(locked_until: datetime | None) -> bool:
    """Kiểm tra thời điểm mở khoá ``locked_until`` còn ở tương lai hay không.

    Args:
        locked_until: Giá trị cột ``users.locked_until`` (``None`` = không bị khoá).

    Returns:
        bool: ``True`` nếu tài khoản **đang** bị tạm khoá.
    """
    return locked_until is not None and locked_until > utcnow()


def lockout_seconds_remaining(locked_until: datetime) -> int:
    """Số giây còn lại của thời gian khoá (làm tròn lên, nhỏ nhất là ``0``).

    Dùng để đặt header ``Retry-After`` và hiển thị thời gian chờ cho người dùng.
    """
    remaining = locked_until - utcnow()
    return max(0, math.ceil(remaining.total_seconds()))


def build_lockout_message(username: str, locked_until: datetime) -> str:
    """Câu thông báo (tiếng Việt) giải thích tài khoản đang bị khoá trong bao lâu."""
    minutes, seconds = divmod(lockout_seconds_remaining(locked_until), 60)
    wait_time = " ".join(
        part
        for part in (
            f"{minutes} phút" if minutes else "",
            f"{seconds} giây" if seconds else "",
        )
        if part
    ) or "0 giây"
    return (
        f"Tài khoản '{username}' đã bị tạm khoá do nhập sai mật khẩu "
        f"{MAX_FAILED_LOGIN_ATTEMPTS} lần liên tiếp. Vui lòng thử lại sau {wait_time}."
    )


def register_failed_login(db: Session, user: User) -> None:
    """Ghi nhận **một lần** đăng nhập sai và tạm khoá nếu đã đủ số lần cho phép.

    Tăng ``failed_login_attempts`` thêm 1; khi đạt ``MAX_FAILED_LOGIN_ATTEMPTS``
    thì đặt ``locked_until = utcnow() + LOCKOUT_DURATION`` (5 phút).
    """
    user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
    if user.failed_login_attempts >= MAX_FAILED_LOGIN_ATTEMPTS:
        user.locked_until = utcnow() + LOCKOUT_DURATION
    db.commit()


def reset_login_attempts(db: Session, user: User) -> None:
    """Xoá bộ đếm sai và mở khoá tài khoản (đăng nhập thành công / hết hạn khoá).

    Chỉ ghi database khi thực sự có gì để thay đổi - tránh câu ``UPDATE`` vô ích
    ở mỗi lần đăng nhập đúng.
    """
    if user.failed_login_attempts or user.locked_until is not None:
        user.failed_login_attempts = 0
        user.locked_until = None
        db.commit()


def authenticate_user_with_lockout(db: Session, username: str, password: str) -> User | None:
    """Xác thực cho ``POST /auth/login`` - có đếm số lần sai và tạm khoá tài khoản.

    Luồng xử lý:

    1. Không tìm thấy ``username`` -> trả ``None`` (router trả **401**; không đếm
       vì không có tài khoản nào để ghi nhận).
    2. Tài khoản đã hết thời gian khoá -> mở khoá, bộ đếm về 0 (chu kỳ mới).
    3. Tài khoản đang bị khoá -> ``AccountLockedError`` (**403**).
    4. Sai mật khẩu -> ghi nhận 1 lần sai, trả ``None`` (**401**). Nếu đây là
       lần sai thứ ``MAX_FAILED_LOGIN_ATTEMPTS`` (5) thì khoá tài khoản và
       ``AccountLockedError`` được raise ngay (**403**).
    5. Đúng mật khẩu -> xoá bộ đếm và trả về ``User`` (**200**).

    Raises:
        AccountLockedError: Tài khoản đang trong thời gian bị tạm khoá.
    """
    user = get_user_by_username(db, username)
    if user is None:
        return None

    if user.locked_until is not None and not is_account_locked(user.locked_until):
        reset_login_attempts(db, user)  # hết hạn khoá -> mở khoá, đếm lại từ đầu

    if is_account_locked(user.locked_until):
        raise AccountLockedError(user.username, user.locked_until)

    if not verify_password(password, user.password):
        register_failed_login(db, user)
        if is_account_locked(user.locked_until):
            # Vừa chạm ngưỡng ở lần sai này -> báo 403 ngay cho client biết.
            raise AccountLockedError(user.username, user.locked_until)
        return None

    reset_login_attempts(db, user)
    return user


# ----------------------------------------------------------- Dependencies ---
def get_current_user(
    credentials: HTTPBasicCredentials | None = Depends(basic_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Dependency: lấy tài khoản đang gọi API từ header ``Authorization``.

    Raises:
        HTTPException: **401** nếu thiếu header ``Authorization``, hoặc
            username/mật khẩu không đúng. Header ``WWW-Authenticate: Basic``
            giúp Swagger UI/browser biết cần đăng nhập.
        HTTPException: **403** nếu tài khoản đang bị tạm khoá do nhập sai mật
            khẩu quá nhiều lần (Sprint 6).
    """
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Chưa đăng nhập hoặc thông tin đăng nhập không đúng.",
        headers={"WWW-Authenticate": "Basic"},
    )

    if credentials is None:  # client không gửi header Authorization
        raise unauthorized

    user = authenticate_user(db, credentials.username, credentials.password)
    if user is None:  # username không tồn tại hoặc sai mật khẩu
        raise unauthorized

    if is_account_locked(user.locked_until):
        # Tài khoản đang bị khoá: không cho dùng API cần quyền dù mật khẩu đúng,
        # nếu không thì việc khoá chỉ chặn được đúng endpoint /auth/login.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=build_lockout_message(user.username, user.locked_until),
        )

    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Dependency: **chỉ** tài khoản role ``admin`` được phép gọi API.

    Dùng cho các chức năng quản trị hệ thống - ví dụ ``GET /users``.

    Args:
        current_user: Tài khoản đã xác thực do ``get_current_user`` cấp.

    Returns:
        User: Tài khoản admin (router có thể dùng để log/audit).

    Raises:
        HTTPException: **401** nếu chưa đăng nhập; **403** nếu đã đăng nhập
            nhưng vai trò không phải admin.
    """
    if current_user.role != ROLE_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chỉ tài khoản admin được phép thực hiện chức năng này.",
        )
    return current_user


def require_farmer(current_user: User = Depends(get_current_user)) -> User:
    """Dependency: cho phép **farmer và admin** (nhóm chức năng nông sản).

    Quy ước phân quyền của sprint này:

    - ``farmer`` (nông dân): quản lý nông sản - vùng trồng + lô nông sản.
    - ``admin``: có toàn quyền nên cũng đi qua được dependency này.

    Args:
        current_user: Tài khoản đã xác thực do ``get_current_user`` cấp.

    Returns:
        User: Tài khoản đang gọi API.

    Raises:
        HTTPException: **401** nếu chưa đăng nhập; **403** nếu vai trò không
            nằm trong danh sách được phép.
    """
    if current_user.role not in (ROLE_FARMER, ROLE_ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Chỉ tài khoản nông dân (farmer) hoặc admin "
                "được phép thực hiện chức năng này."
            ),
        )
    return current_user


__all__ = [
    "AccountLockedError",
    "LOCKOUT_DURATION",
    "MAX_FAILED_LOGIN_ATTEMPTS",
    "authenticate_user",
    "authenticate_user_with_lockout",
    "basic_scheme",
    "build_lockout_message",
    "get_current_user",
    "get_user_by_username",
    "hash_password",
    "is_account_locked",
    "lockout_seconds_remaining",
    "register_failed_login",
    "require_admin",
    "require_farmer",
    "reset_login_attempts",
    "utcnow",
    "verify_password",
]

