"""Quản lý phiên đăng nhập phía server (Server-Side Session Store) và CSRF - Giai đoạn 2.

Đặc tính:
1. Session ID là token ngẫu nhiên mật mã an toàn (256-bit URL-safe).
2. Thời hạn phiên 24h, hỗ trợ thu hồi tức thì (revocation) khi đăng xuất hoặc đổi mật khẩu.
3. Sinh CSRF token ngẫu nhiên gắn với từng phiên làm việc.
4. Lưu trữ bền vững hỗ trợ cả DB table `user_sessions` (nếu đã migrate)
   và fallback storage để không gây lỗi khi chạy trên database gốc chưa migrate.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os
import secrets
import threading
from typing import Any
from sqlalchemy import select, text
from sqlalchemy.orm import Session

SESSION_COOKIE_NAME = "session_id"
CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"
SESSION_DURATION = timedelta(hours=24)


def is_production_mode() -> bool:
    """Kiểm tra có đang chạy trong môi trường production yêu cầu DB bền vững hay không."""
    return (
        os.getenv("ENVIRONMENT", "").lower() in ("production", "prod")
        or os.getenv("AGRITRACE_ENV", "").lower() in ("production", "prod")
        or os.getenv("STRICT_SESSION_DB", "0") in ("1", "true")
    )


def mask_session_id(token: str | None) -> str:
    """Che giấu Session ID an toàn khi ghi log hoặc debug, ngăn ngừa rò rỉ token."""
    if not token or len(token) < 10:
        return "***"
    return f"{token[:4]}...{token[-4:]}"


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class SessionData:
    session_id: str
    user_id: int
    csrf_token: str
    created_at: datetime
    expires_at: datetime
    is_revoked: bool = False

    @property
    def is_valid(self) -> bool:
        return not self.is_revoked and self.expires_at > utcnow()


# Bộ nhớ đệm thread-safe hỗ trợ fallback trong môi trường dev/demo và tra cứu nhanh
_memory_sessions: dict[str, SessionData] = {}
_lock = threading.Lock()


def clear_memory_sessions() -> None:
    """Xóa toàn bộ memory session (dùng cho test suite)."""
    with _lock:
        _memory_sessions.clear()


def _has_user_sessions_table(db: Session) -> bool:
    """Kiểm tra xem bảng user_sessions đã tồn tại trong schema DB hay chưa."""
    try:
        result = db.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='user_sessions'")).scalar()
        return bool(result)
    except Exception:
        return False


def create_session(user_id: int, db: Session | None = None) -> SessionData:
    """Tạo một phiên đăng nhập mới cho người dùng.
    
    Trong môi trường production (is_production_mode=True):
    Bắt buộc phải lưu vào bảng DB `user_sessions`. Nếu chưa migrate bảng hoặc DB lỗi,
    sẽ ném RuntimeError chứ tuyệt đối không âm thầm fallback in-memory.
    """
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_hex(16)
    now = utcnow()
    expires = now + SESSION_DURATION

    sess = SessionData(
        session_id=token,
        user_id=user_id,
        csrf_token=csrf,
        created_at=now,
        expires_at=expires,
        is_revoked=False,
    )

    if is_production_mode():
        if db is None or not _has_user_sessions_table(db):
            raise RuntimeError(
                "Môi trường production yêu cầu bảng 'user_sessions' đã được migrate trong cơ sở dữ liệu. "
                "Không được phép fallback in-memory."
            )
        try:
            db.execute(
                text(
                    """
                    INSERT INTO user_sessions (session_id, user_id, csrf_token, created_at, expires_at, is_revoked)
                    VALUES (:token, :uid, :csrf, :created, :expires, 0)
                    """
                ),
                {
                    "token": token,
                    "uid": user_id,
                    "csrf": csrf,
                    "created": now,
                    "expires": expires,
                },
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            raise RuntimeError(f"Lỗi lưu phiên đăng nhập vào database trong production: {exc}") from exc

        with _lock:
            _memory_sessions[token] = sess
        return sess

    # Môi trường Development / Demo: Cho phép fallback in-memory nếu DB chưa chạy migration
    with _lock:
        _memory_sessions[token] = sess

    if db is not None and _has_user_sessions_table(db):
        try:
            db.execute(
                text(
                    """
                    INSERT INTO user_sessions (session_id, user_id, csrf_token, created_at, expires_at, is_revoked)
                    VALUES (:token, :uid, :csrf, :created, :expires, 0)
                    """
                ),
                {
                    "token": token,
                    "uid": user_id,
                    "csrf": csrf,
                    "created": now,
                    "expires": expires,
                },
            )
            db.commit()
        except Exception:
            db.rollback()

    return sess


def get_session(session_id: str | None, db: Session | None = None) -> SessionData | None:
    """Lấy thông tin phiên nếu tồn tại và còn hiệu lực."""
    if not session_id:
        return None

    # 1. Tra trong memory cache nếu hợp lệ
    with _lock:
        sess = _memory_sessions.get(session_id)
        if sess is not None:
            if not sess.is_valid:
                return None
            return sess

    # 2. Tra trong DB nếu có bảng
    if db is not None and _has_user_sessions_table(db):
        try:
            row = db.execute(
                text(
                    """
                    SELECT session_id, user_id, csrf_token, created_at, expires_at, is_revoked
                    FROM user_sessions
                    WHERE session_id = :token
                    """
                ),
                {"token": session_id},
            ).fetchone()
            if row:
                s = SessionData(
                    session_id=row[0],
                    user_id=row[1],
                    csrf_token=row[2],
                    created_at=row[3] if isinstance(row[3], datetime) else datetime.fromisoformat(str(row[3])),
                    expires_at=row[4] if isinstance(row[4], datetime) else datetime.fromisoformat(str(row[4])),
                    is_revoked=bool(row[5]),
                )
                if s.is_valid:
                    with _lock:
                        _memory_sessions[session_id] = s
                    return s
        except Exception:
            pass

    if is_production_mode():
        if db is None or not _has_user_sessions_table(db):
            raise RuntimeError(
                "Môi trường production yêu cầu bảng 'user_sessions' đã được migrate trong cơ sở dữ liệu."
            )

    return None


def revoke_session(session_id: str | None, db: Session | None = None) -> bool:
    """Thu hồi một phiên làm việc (khi đăng xuất)."""
    if not session_id:
        return False

    with _lock:
        sess = _memory_sessions.get(session_id)
        if sess:
            sess.is_revoked = True

    if db is not None and _has_user_sessions_table(db):
        try:
            db.execute(
                text("UPDATE user_sessions SET is_revoked = 1 WHERE session_id = :token"),
                {"token": session_id},
            )
            db.commit()
        except Exception:
            db.rollback()

    return True


def revoke_all_user_sessions(user_id: int, db: Session | None = None) -> None:
    """Thu hồi tất cả phiên của một người dùng (khi đổi mật khẩu hoặc bị khóa)."""
    with _lock:
        for s in _memory_sessions.values():
            if s.user_id == user_id:
                s.is_revoked = True

    if db is not None and _has_user_sessions_table(db):
        try:
            db.execute(
                text("UPDATE user_sessions SET is_revoked = 1 WHERE user_id = :uid"),
                {"uid": user_id},
            )
            db.commit()
        except Exception:
            db.rollback()
