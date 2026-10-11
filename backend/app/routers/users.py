"""Account administration using the existing admin role and HTTP Basic identity."""
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import record_action
from app.database import get_db
from app.models import (
    ROLE_ADMIN,
    ROLE_DISTRIBUTOR,
    ROLE_FARMER,
    ROLE_INSPECTOR,
    ROLE_ORG_ADMIN,
    ROLE_PROCESSOR,
    ROLE_SYSTEM_ADMIN,
    ROLE_TRANSPORTER,
    Organization,
    User,
)
from app.schemas import UserResponse
from app.security import hash_password, require_admin, utcnow, verify_password
from app.services.session_store import revoke_all_user_sessions

router = APIRouter(prefix="/users", tags=["Users"])


RoleType = Literal[
    "system_admin",
    "org_admin",
    "farmer",
    "processor",
    "transporter",
    "distributor",
    "inspector",
    "admin",
]

# Các vai trò nhân viên mà Quản trị tổ chức (org_admin) được phép khởi tạo/gán
ORG_ADMIN_ALLOWED_ROLES: set[str] = {
    ROLE_FARMER,
    ROLE_PROCESSOR,
    ROLE_TRANSPORTER,
    ROLE_DISTRIBUTOR,
}


class AccountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_.-]+$")
    email: str = Field(max_length=255)
    password: str = Field(min_length=12, max_length=128)
    role: RoleType = "farmer"
    organization_id: int = Field(gt=0)

    @field_validator("email")
    @classmethod
    def email_valid(cls, value: str) -> str:
        value = value.strip()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Email không hợp lệ.")
        return value.lower()


class AccountUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    email: str | None = Field(default=None, max_length=255)
    role: RoleType | None = None
    organization_id: int | None = Field(default=None, gt=0)
    is_active: bool | None = None
    is_locked: bool | None = None

    @field_validator("email")
    @classmethod
    def email_valid(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("Không được xóa email.")
        return AccountCreate.email_valid(value)


class PasswordReset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    admin_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


def lock_accounts(db: Session) -> None:
    # Serialize lifecycle changes before counting usable administrators on SQLite.
    db.execute(update(User).values(is_active=User.is_active))
    db.expire_all()


def check_identity(db: Session, email: str, username: str | None = None, exclude: int = 0) -> None:
    stmt = select(User.id).where(User.id != exclude)
    condition = (func.lower(User.email) == email.lower()) | (func.lower(User.username) == email.lower())
    if username:
        condition |= (func.lower(User.username) == username.lower()) | (func.lower(User.email) == username.lower())
    if db.scalar(stmt.where(condition)) is not None:
        raise HTTPException(409, "Tên đăng nhập hoặc email đã được sử dụng.")


def save(db: Session, actor: User, target: User, action: str) -> User:
    try:
        db.flush()
        record_action(db, actor, action, "user", target.id)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Thông tin tài khoản bị trùng hoặc không hợp lệ.") from exc
    db.refresh(target)
    return target


@router.get("", response_model=list[UserResponse])
def list_users(
    search: str | None = Query(None, max_length=255),
    role: str | None = None,
    organization_id: int | None = Query(None, gt=0),
    is_active: bool | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=100),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[User]:
    stmt = select(User).order_by(User.id)

    # Phân quyền: Organization Admin chỉ được xem nhân viên thuộc tổ chức của mình
    if current_user.role == ROLE_ORG_ADMIN:
        if current_user.organization_id is None:
            raise HTTPException(403, "Tài khoản quản trị tổ chức chưa được gắn với tổ chức nào.")
        if organization_id is not None and organization_id != current_user.organization_id:
            raise HTTPException(403, "Quản trị tổ chức không được xem người dùng của tổ chức khác.")
        stmt = stmt.where(User.organization_id == current_user.organization_id)
    elif organization_id is not None:
        stmt = stmt.where(User.organization_id == organization_id)

    if search:
        term = f"%{search.strip()}%"
        stmt = stmt.where(User.username.ilike(term) | User.email.ilike(term))
    if role is not None:
        stmt = stmt.where(User.role == role)
    if is_active is not None:
        stmt = stmt.where(User.is_active == is_active)

    return list(db.scalars(stmt.offset((page - 1) * limit).limit(limit)).all())


@router.post("", response_model=UserResponse, status_code=201)
def create_user(
    payload: AccountCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> User:
    lock_accounts(db)

    # Kiểm tra quyền tạo tài khoản
    if current_user.role == ROLE_ORG_ADMIN:
        if current_user.organization_id is None:
            raise HTTPException(403, "Tài khoản quản trị chưa được gán tổ chức.")
        if payload.organization_id != current_user.organization_id:
            raise HTTPException(403, "Quản trị tổ chức chỉ được tạo tài khoản thuộc tổ chức của mình.")
        if payload.role not in ORG_ADMIN_ALLOWED_ROLES:
            raise HTTPException(
                403,
                f"Quản trị tổ chức không có quyền cấp vai trò '{payload.role}'. "
                "Chỉ được cấp các vai trò nhân viên: farmer, processor, transporter, distributor.",
            )

    if db.get(Organization, payload.organization_id) is None:
        raise HTTPException(404, "Không tìm thấy tổ chức.")
    check_identity(db, payload.email, payload.username)
    target = User(**payload.model_dump(exclude={"password"}), password=hash_password(payload.password))
    db.add(target)
    return save(db, current_user, target, "create")


@router.patch("/{user_id}", response_model=UserResponse)
def edit_user(  # noqa: C901
    user_id: int,
    payload: AccountUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> User:
    lock_accounts(db)
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "Không tìm thấy tài khoản.")

    # Phân quyền Organization Admin: chỉ quản lý tài khoản thuộc tổ chức của mình
    if current_user.role == ROLE_ORG_ADMIN:
        if target.organization_id != current_user.organization_id:
            raise HTTPException(403, "Quản trị tổ chức chỉ được quản lý tài khoản trong tổ chức của mình.")
        if target.role in (ROLE_SYSTEM_ADMIN, ROLE_ADMIN, ROLE_INSPECTOR):
            raise HTTPException(403, "Không được phép chỉnh sửa tài khoản quản trị hệ thống hoặc thanh tra.")

    changes = payload.model_dump(exclude_unset=True)
    if any(value is None for value in changes.values()):
        raise HTTPException(422, "Thông tin cập nhật không được null.")

    if current_user.role == ROLE_ORG_ADMIN:
        if "organization_id" in changes and changes["organization_id"] != current_user.organization_id:
            raise HTTPException(403, "Quản trị tổ chức không thể chuyển tài khoản sang tổ chức khác.")
        if "role" in changes and changes["role"] not in ORG_ADMIN_ALLOWED_ROLES:
            raise HTTPException(
                403,
                f"Quản trị tổ chức không thể gán vai trò '{changes['role']}' vượt quá thẩm quyền.",
            )

    if "organization_id" in changes and db.get(Organization, changes["organization_id"]) is None:
        raise HTTPException(404, "Không tìm thấy tổ chức.")
    if "email" in changes:
        check_identity(db, changes["email"], exclude=user_id)

    # Bảo vệ admin / system_admin cuối cùng
    admin_roles = {"admin", "system_admin"}
    losing_admin = (
        (target.role in admin_roles and changes.get("role", target.role) not in admin_roles)
        or not changes.get("is_active", target.is_active)
        or changes.get("is_locked", target.is_locked)
    )
    if target.role in admin_roles and losing_admin:
        other = db.scalar(
            select(User.id).where(
                User.id != target.id,
                User.role.in_(admin_roles),
                User.is_active.is_(True),
                User.is_locked.is_(False),
                (User.locked_until.is_(None)) | (User.locked_until <= utcnow()),
            )
        )
        if other is None:
            raise HTTPException(409, "Không thể khóa, vô hiệu hóa hoặc hạ quyền quản trị viên cuối cùng.")

    for name, value in changes.items():
        setattr(target, name, value)

    if changes.get("is_locked") is False:
        target.locked_until = None
        target.failed_login_attempts = 0
    elif changes.get("is_locked") is True or changes.get("is_active") is False:
        # Thu hồi toàn bộ phiên nếu tài khoản bị khóa hoặc vô hiệu hóa
        revoke_all_user_sessions(target.id, db)

    return save(db, current_user, target, "update")


@router.post("/{user_id}/reset-password", response_model=UserResponse)
def reset_password(
    user_id: int,
    payload: PasswordReset,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> User:
    if not verify_password(payload.admin_password, current_user.password):
        raise HTTPException(403, "Mật khẩu xác nhận của quản trị viên không đúng.")

    lock_accounts(db)
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "Không tìm thấy tài khoản.")

    # Phân quyền: org_admin chỉ được reset mật khẩu nhân viên thuộc tổ chức của mình
    if current_user.role == ROLE_ORG_ADMIN:
        if target.organization_id != current_user.organization_id:
            raise HTTPException(403, "Quản trị tổ chức chỉ được đặt lại mật khẩu cho tài khoản trong tổ chức của mình.")
        if target.role in (ROLE_SYSTEM_ADMIN, ROLE_ADMIN, ROLE_INSPECTOR):
            raise HTTPException(403, "Không được phép đặt lại mật khẩu cho tài khoản quản trị hệ thống hoặc thanh tra.")

    target.password = hash_password(payload.new_password)
    # Thu hồi toàn bộ phiên làm việc của target khi reset mật khẩu
    revoke_all_user_sessions(target.id, db)
    return save(db, current_user, target, "reset_password")
