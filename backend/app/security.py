"""Xác thực (authentication), phân quyền (authorization) và cách ly tổ chức.

Sprint 1:
- Băm mật khẩu an toàn theo chuẩn Argon2id (dùng argon2-cffi).
- Cơ chế khóa tài khoản: Sai 5 lần liên tiếp -> khóa tạm 15 phút (HTTP 403 kèm Retry-After).
  Đăng nhập đúng thì reset số lần sai về 0.
- Cách ly dữ liệu theo Organization: dependency tự động lấy organization_id từ phiên đăng nhập,
  ngăn chặn truy cập chéo giữa các tổ chức (HTTP 403 Forbidden).
"""

import hashlib
import math
import os
from datetime import datetime, timedelta, timezone
from hmac import compare_digest

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import case, func, select, update
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.session_store import (
    CSRF_HEADER_NAME,
    SESSION_COOKIE_NAME,
    get_session,
)
from app.models import (
    ROLE_ADMIN,
    ROLE_DISTRIBUTOR,
    ROLE_FARMER,
    ROLE_INSPECTOR,
    ROLE_ORG_ADMIN,
    ROLE_PROCESSOR,
    ROLE_SYSTEM_ADMIN,
    ROLE_TRANSPORTER,
    User,
)

# Instance băm mật khẩu Argon2id
_hasher = PasswordHasher()

# HTTP Basic scheme (auto_error=False để tự format thông báo lỗi)
basic_scheme = HTTPBasic(auto_error=False)

# ------------------------------------------- Chống dò mật khẩu ---
# Chính sách: nhập sai mật khẩu liên tiếp quá 5 lần thì tài khoản bị tạm khóa 15 phút
MAX_FAILED_LOGIN_ATTEMPTS: int = 5
LOCKOUT_DURATION: timedelta = timedelta(minutes=15)


def utcnow() -> datetime:
    """Thời điểm hiện tại theo UTC không kèm tzinfo."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AccountLockedError(Exception):
    """Tài khoản đang bị tạm khoá vì đăng nhập sai quá nhiều lần."""

    def __init__(self, username: str, locked_until: datetime) -> None:
        self.username = username
        self.locked_until = locked_until
        super().__init__(build_lockout_message(username, locked_until))


# ------------------------------------------------------- Mật khẩu (Argon2id) ---
def hash_password(raw_password: str) -> str:
    """Băm mật khẩu bằng Argon2id."""
    return _hasher.hash(raw_password)


def verify_password(raw_password: str, hashed_password: str) -> bool:
    """So sánh mật khẩu người dùng nhập với mật khẩu đã băm.

    Hỗ trợ cả Argon2id và fallback SHA-256 (cho các bản ghi cũ).
    """
    if hashed_password.startswith("$argon2"):
        try:
            return _hasher.verify(hashed_password, raw_password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    # Fallback cho SHA-256 cũ
    legacy_hash = hashlib.sha256(raw_password.encode("utf-8")).hexdigest()
    return compare_digest(legacy_hash, hashed_password)


def authenticate_user(db: Session, username: str, password: str) -> User | None:
    """Tra bảng users và trả về tài khoản nếu thông tin đăng nhập đúng.

    S-04: ``username`` có thể là **tên đăng nhập hoặc email**.
    """
    user = get_user_by_identifier(db, username)
    if user is None or not user.is_active or user.is_locked or not verify_password(password, user.password):
        return None
    return user


def get_user_by_username(db: Session, username: str) -> User | None:
    """Tra tài khoản theo username."""
    return db.scalar(select(User).where(User.username == username))


def get_user_by_identifier(db: Session, identifier: str) -> User | None:
    """Tra tài khoản theo **username hoặc email** (S-04).

    - Khớp ``username`` chính xác (như cũ) để tương thích ngược với dữ liệu seed.
    - Khớp ``email`` **không phân biệt hoa/thường** (email của bản ghi cũ có thể
      là ``NULL`` - khi đó so sánh email không khớp và chỉ còn nhánh username).
    """
    login = (identifier or "").strip()
    if not login:
        return None
    return db.scalar(
        select(User).where(
            (User.username == login) | (func.lower(User.email) == login.lower())
        )
    )


def is_account_locked(locked_until: datetime | None) -> bool:
    """Kiểm tra thời điểm mở khoá locked_until còn ở tương lai hay không."""
    return locked_until is not None and locked_until > utcnow()


def lockout_seconds_remaining(locked_until: datetime) -> int:
    """Số giây còn lại của thời gian khoá."""
    remaining = locked_until - utcnow()
    return max(0, math.ceil(remaining.total_seconds()))


def build_lockout_message(username: str, locked_until: datetime) -> str:
    """Thông báo tài khoản đang bị khoá và thời gian chờ còn lại."""
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
    """Ghi nhận một lần đăng nhập sai và khóa 15 phút nếu đạt ngưỡng, đồng thời thu hồi mọi session."""
    next_attempt = User.failed_login_attempts + 1
    db.execute(update(User).where(User.id == user.id).values(
        failed_login_attempts=next_attempt,
        locked_until=case((next_attempt >= MAX_FAILED_LOGIN_ATTEMPTS, utcnow() + LOCKOUT_DURATION), else_=User.locked_until),
    ))
    db.commit()
    db.refresh(user)
    if is_account_locked(user.locked_until):
        from app.services.session_store import revoke_all_user_sessions
        revoke_all_user_sessions(user.id, db)


def reset_login_attempts(db: Session, user: User) -> None:
    """Xoá bộ đếm sai và mở khoá tài khoản khi đăng nhập thành công."""
    if user.failed_login_attempts or user.locked_until is not None:
        user.failed_login_attempts = 0
        user.locked_until = None
        db.commit()


def authenticate_user_with_lockout(db: Session, username: str, password: str) -> User | None:
    """Xác thực đăng nhập có kiểm tra số lần sai và tạm khoá tài khoản.

    S-04: ``username`` có thể là **tên đăng nhập hoặc email**.
    """
    user = get_user_by_identifier(db, username)
    if user is None:
        return None

    if not user.is_active or user.is_locked:
        raise HTTPException(status_code=403, detail="Tài khoản đã bị khóa hoặc vô hiệu hóa. Liên hệ quản trị viên.")

    if user.locked_until is not None and not is_account_locked(user.locked_until):
        reset_login_attempts(db, user)

    if is_account_locked(user.locked_until):
        raise AccountLockedError(user.username, user.locked_until)

    if not verify_password(password, user.password):
        register_failed_login(db, user)
        if is_account_locked(user.locked_until):
            raise AccountLockedError(user.username, user.locked_until)
        return None

    # Tự động nâng cấp hash mật khẩu legacy (SHA-256) sang Argon2id khi đăng nhập thành công
    import os
    allow_upgrade = os.getenv("ALLOW_LEGACY_PASSWORD_UPGRADE", "1") == "1"
    if allow_upgrade and not user.password.startswith("$argon2"):
        user.password = hash_password(password)
        db.commit()

    reset_login_attempts(db, user)
    return user


def is_basic_auth_allowed() -> bool:
    """Kiểm tra xem HTTP Basic Auth có được phép sử dụng hay không.

    - Mặc định trong development / test / demo: Cho phép (True) để đảm bảo tương thích ngược.
    - Trong môi trường production: Vô hiệu hóa (False), trừ khi biến ALLOW_BASIC_AUTH=true được cấu hình tường minh.
    """
    env = os.getenv("ENVIRONMENT", "").lower()
    is_prod = env in ("production", "prod") or os.getenv("AGRITRACE_ENV", "").lower() in ("production", "prod")
    explicit_allow = os.getenv("ALLOW_BASIC_AUTH", "").lower()
    if explicit_allow in ("false", "0", "no"):
        return False
    if explicit_allow in ("true", "1", "yes"):
        return True
    return not is_prod


# ----------------------------------------------------------- Dependencies ---
def get_current_user(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(basic_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Lấy tài khoản đang gọi API từ Phiên làm việc (Session Cookie) hoặc HTTP Basic.
    
    Ngăn chặn việc dùng HTTP Basic làm đường vòng vượt qua session bị thu hồi/hết hạn.
    """
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Chưa đăng nhập hoặc thông tin đăng nhập không đúng.",
        # Browser fetch must receive 401 instead of opening a native Basic
        # challenge; CLI/Swagger Basic clients retain the standard header.
        headers={} if request.headers.get("x-requested-with") == "XMLHttpRequest"
        else {"WWW-Authenticate": "Basic"},
    )

    # 1. Ưu tiên kiểm tra Session Cookie (phiên đăng nhập phía server - Giai đoạn 2)
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id:
        sess = get_session(session_id, db)
        if not sess or not sess.is_valid:
            # Cookie session được gửi nhưng không còn hợp lệ / bị thu hồi:
            # Yêu cầu đăng nhập lại ngay lập tức, tuyệt đối KHÔNG fallback sang Basic Auth
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Phiên làm việc đã hết hạn hoặc không hợp lệ. Vui lòng đăng nhập lại.",
            )

        # Kiểm tra CSRF cho các thao tác thay đổi dữ liệu khi dùng Cookie
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            path = request.url.path
            if not (path.endswith("/auth/login") or path.endswith("/auth/logout")):
                csrf_header = request.headers.get(CSRF_HEADER_NAME)
                if not csrf_header or not compare_digest(csrf_header, sess.csrf_token):
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="CSRF token không hợp lệ hoặc bị thiếu.",
                    )

        user = db.get(User, sess.user_id)
        if user is None or not user.is_active or user.is_locked:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tài khoản đã bị khóa hoặc vô hiệu hóa. Liên hệ quản trị viên.",
            )
        if is_account_locked(user.locked_until):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=build_lockout_message(user.username, user.locked_until),
            )

        return user

    # 2. Fallback sang HTTP Basic Auth để tương thích ngược với API clients / test suite
    if not is_basic_auth_allowed():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Hệ thống đã vô hiệu hóa HTTP Basic Auth trong môi trường sản xuất. Vui lòng đăng nhập qua /auth/login để nhận phiên làm việc.",
        )

    if credentials is None:
        raise unauthorized

    try:
        user = authenticate_user_with_lockout(db, credentials.username, credentials.password)
    except AccountLockedError as exc:
        raise HTTPException(
            status_code=403, detail=str(exc),
            headers={"Retry-After": str(lockout_seconds_remaining(exc.locked_until))},
        ) from exc
    if user is None:
        raise unauthorized

    if not user.is_active or user.is_locked:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tài khoản đã bị khóa hoặc vô hiệu hóa. Liên hệ quản trị viên.",
        )

    if is_account_locked(user.locked_until):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=build_lockout_message(user.username, user.locked_until),
        )

    return user


ADMIN_ROLES: tuple[str, ...] = (ROLE_SYSTEM_ADMIN, ROLE_ORG_ADMIN, ROLE_ADMIN)
OPERATIONAL_ROLES: tuple[str, ...] = (
    ROLE_FARMER,
    ROLE_PROCESSOR,
    ROLE_TRANSPORTER,
    ROLE_DISTRIBUTOR,
    ROLE_ORG_ADMIN,
    ROLE_SYSTEM_ADMIN,
    ROLE_ADMIN,
)


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Dependency: chỉ tài khoản role admin (system_admin, org_admin, admin) được phép gọi API."""
    from app.services.rbac import get_effective_role
    if get_effective_role(current_user) not in ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chỉ tài khoản admin được phép thực hiện chức năng này.",
        )
    return current_user


def require_farmer(current_user: User = Depends(get_current_user)) -> User:
    """Dependency: cho phép các vai trò nghiệp vụ chuỗi cung ứng thực hiện thao tác."""
    from app.services.rbac import get_effective_role
    if get_effective_role(current_user) not in OPERATIONAL_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vai trò của bạn không có quyền thực hiện chức năng nghiệp vụ này.",
        )
    if current_user.organization_id is None:
        raise HTTPException(status_code=403, detail="Tài khoản chưa được liên kết với tổ chức nào.")
    return current_user


def require_audit_reader(current_user: User = Depends(get_current_user)) -> User:
    """Dependency: cho phép admin và inspector đọc audit log."""
    from app.services.rbac import get_effective_role
    if get_effective_role(current_user) not in (ROLE_SYSTEM_ADMIN, ROLE_INSPECTOR, ROLE_ORG_ADMIN, ROLE_ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chỉ tài khoản quản trị hoặc thanh tra (inspector) được phép xem nhật ký kiểm toán.",
        )
    return current_user


FARM_READER_ROLES: tuple[str, ...] = OPERATIONAL_ROLES + (ROLE_INSPECTOR,)


def require_farm_reader(current_user: User = Depends(get_current_user)) -> User:
    """Dependency: cho phép các vai trò nghiệp vụ và thanh tra xem thông tin vùng trồng."""
    from app.services.rbac import get_effective_role
    if get_effective_role(current_user) not in FARM_READER_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vai trò của bạn không có quyền xem thông tin vùng trồng.",
        )
    return current_user


def get_current_organization_id(current_user: User = Depends(get_current_user)) -> int:
    """Dependency: tự động lấy organization_id từ phiên đăng nhập.

    Dùng để cách ly dữ liệu giữa các tổ chức.
    """
    if current_user.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tài khoản chưa được liên kết với tổ chức nào.",
        )
    return current_user.organization_id


def check_organization_access(current_user: User, target_org_id: int) -> None:
    """Kiểm tra quyền truy cập tài nguyên của tổ chức.

    Nguyên tắc mặc định từ chối: Nếu tài khoản không thuộc tổ chức nào
    hoặc khác tổ chức mục tiêu -> trả 403 Forbidden.
    """
    if current_user.organization_id is None or current_user.organization_id != target_org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền truy cập dữ liệu của tổ chức khác.",
        )


__all__ = [
    "AccountLockedError",
    "LOCKOUT_DURATION",
    "MAX_FAILED_LOGIN_ATTEMPTS",
    "authenticate_user",
    "authenticate_user_with_lockout",
    "basic_scheme",
    "build_lockout_message",
    "check_organization_access",
    "get_current_organization_id",
    "get_current_user",
    "get_user_by_identifier",
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
