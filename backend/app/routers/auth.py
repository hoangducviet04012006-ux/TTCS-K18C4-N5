"""Router đăng nhập (``POST /auth/login``) - Sprint 4.

Đặc điểm theo yêu cầu của sprint: **không JWT**, không token, không refresh
token. Endpoint chỉ kiểm tra ``username``/``password`` với bảng ``users`` rồi
trả về ``username`` + ``role`` để frontend hiển thị và ẩn/hiện chức năng.

Việc xác thực cho **các request sau** dùng HTTP Basic
(``Authorization: Basic base64(username:password)``) - xem dependency
``get_current_user`` / ``require_admin`` / ``require_farmer``
trong ``app/security.py``. Swagger UI tự hiện nút **Authorize** nhờ đó.

Sprint 6 - **bảo mật đăng nhập**: nhập sai mật khẩu
``MAX_FAILED_LOGIN_ATTEMPTS`` (5) lần liên tiếp thì tài khoản bị **tạm khoá**
``LOCKOUT_DURATION`` (5 phút) và endpoint trả **403 Forbidden** kèm message rõ
ràng + header ``Retry-After``. Số lần sai và thời điểm mở khoá lưu ở 2 cột
``users.failed_login_attempts`` / ``users.locked_until``.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import AccountLockedResponse, LoginRequest, LoginResponse
from app.security import (
    AccountLockedError,
    authenticate_user_with_lockout,
    build_lockout_message,
    lockout_seconds_remaining,
)

router = APIRouter(
    prefix="/auth",
    tags=["Auth"],
)


@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Đăng nhập",
    description=(
        "Kiểm tra `username`/`password` với bảng `users`.\n\n"
        "**Thành công:** trả về `username` và `role` "
        "(`admin` hoặc `farmer`). **Không sinh token** vì dự án không dùng JWT - "
        "client gửi lại thông tin đăng nhập qua header `Authorization` (HTTP Basic) "
        "ở những request cần quyền.\n\n"
        "**Bảo mật (Sprint 6):** nhập sai mật khẩu **5 lần liên tiếp** thì tài khoản "
        "bị **tạm khoá 5 phút** - các lần đăng nhập sau đó (kể cả đúng mật khẩu) "
        "nhận `403 Forbidden` kèm thời gian chờ còn lại. Đăng nhập thành công hoặc "
        "hết thời gian khoá sẽ xoá số lần sai."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Sai tên đăng nhập hoặc mật khẩu.",
        },
        status.HTTP_403_FORBIDDEN: {
            "description": (
                "Tài khoản đang bị tạm khoá do nhập sai mật khẩu quá nhiều lần "
                "(message nêu rõ thời gian chờ còn lại)."
            ),
            "model": AccountLockedResponse,
        },
    },
)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    """Đăng nhập bằng tài khoản trong bảng ``users``.

    Args:
        payload: ``username`` + ``password`` đã được Pydantic validate.
        db: Session SQLAlchemy từ dependency ``get_db``.

    Returns:
        LoginResponse: ``{"username": ..., "role": ...}`` (HTTP 200).

    Raises:
        HTTPException: **401** nếu sai tên đăng nhập hoặc mật khẩu (chưa đủ số
            lần để khoá); **403** nếu tài khoản đang bị tạm khoá hoặc lần sai này
            chạm ngưỡng khoá.
    """
    try:
        user = authenticate_user_with_lockout(db, payload.username, payload.password)
    except AccountLockedError as exc:
        # Đang bị khoá (hoặc vừa chạm ngưỡng 5 lần sai) -> 403 + thời gian chờ.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=build_lockout_message(exc.username, exc.locked_until),
            headers={"Retry-After": str(lockout_seconds_remaining(exc.locked_until))},
        ) from exc

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sai tên đăng nhập hoặc mật khẩu.",
        )

    return LoginResponse(
        username=user.username,
        role=user.role,
        organization_id=user.organization_id,
        organization_name=user.organization.name if user.organization else None,
    )
