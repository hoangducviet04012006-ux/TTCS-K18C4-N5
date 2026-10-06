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
from datetime import datetime, timedelta, timezone
from hmac import compare_digest

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ROLE_ADMIN, ROLE_FARMER, User

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

    def __init__(self, email: str, locked_until: datetime) -> None:
        self.email = email
        self.locked_until = locked_until
        super().__init__(build_lockout_message(email, locked_until))


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


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    """Tra bảng users và trả về tài khoản nếu thông tin đăng nhập đúng."""
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(password, user.password):
        return None
    return user


def get_user_by_email(db: Session, email: str) -> User | None:
    """Tra tài khoản theo email."""
    return db.scalar(select(User).where(User.email == email))


def is_account_locked(locked_until: datetime | None) -> bool:
    """Kiểm tra thời điểm mở khoá locked_until còn ở tương lai hay không."""
    return locked_until is not None and locked_until > utcnow()


def lockout_seconds_remaining(locked_until: datetime) -> int:
    """Số giây còn lại của thời gian khoá."""
    remaining = locked_until - utcnow()
    return max(0, math.ceil(remaining.total_seconds()))


def build_lockout_message(email: str, locked_until: datetime) -> str:
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
        f"Tài khoản '{email}' đã bị tạm khoá do nhập sai mật khẩu "
        f"{MAX_FAILED_LOGIN_ATTEMPTS} lần liên tiếp. Vui lòng thử lại sau {wait_time}."
    )


def register_failed_login(db: Session, user: User) -> None:
    """Ghi nhận một lần đăng nhập sai và khóa 15 phút nếu đạt ngưỡng."""
    user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
    if user.failed_login_attempts >= MAX_FAILED_LOGIN_ATTEMPTS:
        user.locked_until = utcnow() + LOCKOUT_DURATION
    db.commit()


def reset_login_attempts(db: Session, user: User) -> None:
    """Xoá bộ đếm sai và mở khoá tài khoản khi đăng nhập thành công."""
    if user.failed_login_attempts or user.locked_until is not None:
        user.failed_login_attempts = 0
        user.locked_until = None
        db.commit()


def authenticate_user_with_lockout(db: Session, email: str, password: str) -> User | None:
    """Xác thực đăng nhập có kiểm tra số lần sai và tạm khoá tài khoản."""
    user = get_user_by_email(db, email)
    if user is None:
        return None

    if user.locked_until is not None and not is_account_locked(user.locked_until):
        reset_login_attempts(db, user)

    if is_account_locked(user.locked_until):
        raise AccountLockedError(user.email, user.locked_until)

    if not verify_password(password, user.password):
        register_failed_login(db, user)
        if is_account_locked(user.locked_until):
            raise AccountLockedError(user.email, user.locked_until)
        return None

    reset_login_attempts(db, user)
    return user


# ----------------------------------------------------------- Dependencies ---
def get_current_user(
    credentials: HTTPBasicCredentials | None = Depends(basic_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Lấy tài khoản đang gọi API từ header Authorization (HTTP Basic)."""
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Chưa đăng nhập hoặc thông tin đăng nhập không đúng.",
        headers={"WWW-Authenticate": "Basic"},
    )

    if credentials is None:
        raise unauthorized

    user = authenticate_user(db, credentials.email, credentials.password)
    if user is None:
        raise unauthorized

    if is_account_locked(user.locked_until):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=build_lockout_message(user.email, user.locked_until),
        )

    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Dependency: chỉ tài khoản role admin được phép gọi API."""
    if current_user.role != ROLE_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chỉ tài khoản admin được phép thực hiện chức năng này.",
        )
    return current_user


def require_farmer(current_user: User = Depends(get_current_user)) -> User:
    """Dependency: cho phép farmer và admin."""
    if current_user.role not in (ROLE_FARMER, ROLE_ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chỉ tài khoản nông dân (farmer) hoặc admin được phép thực hiện chức năng này.",
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

    Nếu cố tình truy cập tài nguyên của tổ chức khác -> trả 403 Forbidden.
    """
    if current_user.organization_id is not None and current_user.organization_id != target_org_id:
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
    "get_user_by_email",
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
