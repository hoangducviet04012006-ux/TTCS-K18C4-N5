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
``LOCKOUT_DURATION`` (15 phút) và endpoint trả **403 Forbidden** kèm message rõ
ràng + header ``Retry-After``. Số lần sai và thời điểm mở khoá lưu ở 2 cột
``users.failed_login_attempts`` / ``users.locked_until``.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app.database import DATABASE_FILE, DATABASE_URL, get_db
from app.schemas import AccountLockedResponse, DemoLoginRequest, LoginRequest, LoginResponse
from app.models import User
from app.audit import record_action
from app.security import (
    AccountLockedError,
    authenticate_user_with_lockout,
    build_lockout_message,
    lockout_seconds_remaining,
    get_current_user,
    hash_password,
    verify_password,
)
from app.services.session_store import (
    CSRF_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    create_session,
    get_session,
    revoke_all_user_sessions,
    revoke_session,
)

router = APIRouter(
    prefix="/auth",
    tags=["Auth"],
)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


@router.post("/change-password")
def change_password(
    payload: PasswordChange,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if not verify_password(payload.current_password, current_user.password):
        raise HTTPException(403, "Mật khẩu hiện tại không đúng.")
    if payload.current_password == payload.new_password:
        raise HTTPException(400, "Mật khẩu mới phải khác mật khẩu hiện tại.")
    current_user.password = hash_password(payload.new_password)
    record_action(db, current_user, "change_password", "user", current_user.id)
    # Thu hồi tất cả phiên cũ của user này
    revoke_all_user_sessions(current_user.id, db)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")
    db.commit()
    return {"message": "Mật khẩu đã đổi; thông tin đăng nhập cũ mất hiệu lực."}


@router.get("/me", response_model=LoginResponse, summary="Xem thông tin tài khoản hiện tại")
def get_me(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LoginResponse:
    """Trả về thông tin hồ sơ của tài khoản đang đăng nhập."""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    sess = get_session(session_id, db) if session_id else None
    return LoginResponse(
        username=current_user.username,
        email=current_user.email,
        role=current_user.role,
        organization_id=current_user.organization_id,
        organization_name=current_user.organization.name if current_user.organization else None,
        csrf_token=sess.csrf_token if sess else None,
    )


@router.post("/logout", summary="Đăng xuất và hủy phiên làm việc")
def logout(
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Thu hồi phiên đăng nhập server-side và xóa cookie."""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id:
        try:
            revoke_session(session_id, db)
        except Exception:
            pass
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")
    return {"message": "Đăng xuất thành công, phiên làm việc đã bị hủy."}


@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Đăng nhập",
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Sai tên đăng nhập hoặc mật khẩu.",
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "Tài khoản đang bị tạm khoá do nhập sai mật khẩu quá nhiều lần.",
            "model": AccountLockedResponse,
        },
    },
)
def login(
    payload: LoginRequest,
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
) -> LoginResponse:
    """Đăng nhập bằng tài khoản trong bảng ``users`` và khởi tạo phiên đăng nhập server-side."""
    try:
        user = authenticate_user_with_lockout(db, payload.username, payload.password)
    except AccountLockedError as exc:
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

    # Khởi tạo phiên server-side và thiết lập Cookie HttpOnly
    session_data = create_session(user.id, db)
    import os
    is_secure = (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto", "").lower() == "https"
        or os.getenv("COOKIE_SECURE", "").lower() in ("true", "1")
        or os.getenv("ENVIRONMENT", "").lower() in ("production", "prod")
    )

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_data.session_id,
        httponly=True,
        samesite="lax",
        secure=is_secure,
        path="/",
        max_age=86400,
    )
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=session_data.csrf_token,
        httponly=False,
        samesite="lax",
        secure=is_secure,
        path="/",
        max_age=86400,
    )

    return LoginResponse(
        username=user.username,
        email=user.email,
        role=user.role,
        organization_id=user.organization_id,
        organization_name=user.organization.name if user.organization else None,
        csrf_token=session_data.csrf_token,
    )


ALLOWED_DEMO_ACCOUNTS = {
    "s123_admin",
    "s123_farm",
    "s123_packing",
    "s123_receiver",
    "s123_transport",
    "s123_distribution",
    "s123_inspector",
    "s123_org_admin",
}


@router.post(
    "/demo-login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Đăng nhập nhanh tài khoản Demo (Sprint 1–3, chỉ localhost và DB demo)",
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": (
                "Bị từ chối khi không ở localhost, không dùng database demo Sprint 1–3, "
                "hoặc tài khoản ngoài danh sách 8 tài khoản demo."
            ),
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "Không tìm thấy tài khoản demo.",
        },
    },
)
def demo_login(
    payload: DemoLoginRequest,
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
) -> LoginResponse:
    """Đăng nhập nhanh một trong 8 tài khoản demo Sprint 1–3 mà không cần mật khẩu từ client."""
    # 1. Kiểm tra môi trường localhost
    client_host = request.client.host if request.client else ""
    is_loopback = client_host in ("127.0.0.1", "::1", "localhost", "testclient")
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first_ip = forwarded.split(",")[0].strip()
        if first_ip not in ("127.0.0.1", "::1", "localhost", "testclient"):
            is_loopback = False

    if not is_loopback:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chức năng đăng nhập nhanh Demo chỉ được phép truy cập từ localhost.",
        )

    # 2. Kiểm tra database: từ chối tuyệt đối database gốc ttcs.db
    clean_db_url = DATABASE_URL.replace("sqlite:///", "").replace("\\", "/")
    orig_path = DATABASE_FILE.resolve().as_posix()
    if clean_db_url == orig_path or clean_db_url.endswith("/backend/ttcs.db") or clean_db_url.endswith("/ttcs.db"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chức năng đăng nhập nhanh Demo bị từ chối trên cơ sở dữ liệu gốc.",
        )

    # 3. Kiểm tra marker database demo Sprint 1–3
    try:
        marker = db.execute(text("SELECT value FROM sprint_demo_marker WHERE name='scope'")).scalar()
        if marker != "sprint123":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Chức năng đăng nhập nhanh chỉ khả dụng với database demo Sprint 1–3 được chỉ định.",
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chức năng đăng nhập nhanh chỉ khả dụng với database demo Sprint 1–3 được chỉ định.",
        ) from exc

    # 4. Kiểm tra chỉ cho phép 8 tài khoản demo được chỉ định
    ident = payload.username.strip().lower()
    account_name = ident.split("@")[0] if "@" in ident else ident
    if account_name not in ALLOWED_DEMO_ACCOUNTS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Tài khoản '{payload.username}' không thuộc danh sách 8 tài khoản demo được phép đăng nhập nhanh.",
        )

    # 5. Tra cứu người dùng
    user = db.scalar(
        select(User).where(
            (User.username == account_name) | (func.lower(User.email) == ident)
        )
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy tài khoản demo '{account_name}'.",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Tài khoản demo '{account_name}' đang bị vô hiệu hóa.",
        )

    # Thu hồi session cũ nếu có cookie
    old_session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if old_session_id:
        try:
            revoke_session(old_session_id, db)
        except Exception:
            pass

    # 6. Khởi tạo phiên server-side và thiết lập Cookie HttpOnly
    session_data = create_session(user.id, db)
    import os
    is_secure = (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto", "").lower() == "https"
        or os.getenv("COOKIE_SECURE", "").lower() in ("true", "1")
        or os.getenv("ENVIRONMENT", "").lower() in ("production", "prod")
    )

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_data.session_id,
        httponly=True,
        samesite="lax",
        secure=is_secure,
        path="/",
        max_age=86400,
    )
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=session_data.csrf_token,
        httponly=False,
        samesite="lax",
        secure=is_secure,
        path="/",
        max_age=86400,
    )

    return LoginResponse(
        username=user.username,
        email=user.email,
        role=user.role,
        organization_id=user.organization_id,
        organization_name=user.organization.name if user.organization else None,
        csrf_token=session_data.csrf_token,
    )
