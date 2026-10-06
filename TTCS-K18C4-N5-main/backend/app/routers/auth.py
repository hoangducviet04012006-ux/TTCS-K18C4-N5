"""Router đăng nhập (``POST /auth/login``).

Đăng nhập bằng ``email`` và ``password`` với bảng ``users``, trả về ``email``,
``username`` + ``role`` + ``organization_id`` / ``organization_name``.

Bảo mật đăng nhập:
- Nhập sai mật khẩu ``MAX_FAILED_LOGIN_ATTEMPTS`` (5) lần liên tiếp thì tài khoản
  bị **tạm khoá 15 phút** (``LOCKOUT_DURATION``).
- Endpoint trả **403 Forbidden** kèm thông báo rõ ràng + header ``Retry-After``.
- Đăng nhập thành công sẽ reset số lần sai về 0.
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
        "Kiểm tra `email`/`password` với bảng `users`.\n\n"
        "**Thành công:** trả về `email`, `username` và `role` "
        "(`admin` hoặc `farmer`).\n\n"
        "**Bảo mật:** nhập sai mật khẩu **5 lần liên tiếp** thì tài khoản "
        "bị **tạm khoá 15 phút** - các lần đăng nhập sau đó (kể cả đúng mật khẩu) "
        "nhận `403 Forbidden` kèm thời gian chờ còn lại. Đăng nhập thành công hoặc "
        "hết thời gian khoá sẽ xoá số lần sai."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Sai email hoặc mật khẩu.",
        },
        status.HTTP_403_FORBIDDEN: {
            "description": (
                "Tài khoản đang bị tạm khoá do nhập sai mật khẩu quá nhiều lần."
            ),
            "model": AccountLockedResponse,
        },
    },
)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    """Đăng nhập bằng email và mật khẩu trong bảng ``users``.

    Args:
        payload: ``email`` + ``password`` đã được Pydantic validate.
        db: Session SQLAlchemy từ dependency ``get_db``.

    Returns:
        LoginResponse: ``{"email": ..., "username": ..., "role": ...}`` (HTTP 200).

    Raises:
        HTTPException: **401** nếu sai email hoặc mật khẩu; **403** nếu tài khoản
            đang bị tạm khoá.
    """
    try:
        user = authenticate_user_with_lockout(db, payload.email, payload.password)
    except AccountLockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=build_lockout_message(exc.identifier, exc.locked_until),
            headers={"Retry-After": str(lockout_seconds_remaining(exc.locked_until))},
        ) from exc

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sai email hoặc mật khẩu.",
        )

    return LoginResponse(
        email=user.email,
        username=user.username,
        role=user.role,
        organization_id=user.organization_id,
        organization_name=user.organization.name if user.organization else None,
    )

