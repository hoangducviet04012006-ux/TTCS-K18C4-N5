"""Khai báo ORM models (bảng dữ liệu) bằng SQLAlchemy 2.0.

Sprint 1:
- Module Organization (tổ chức / hợp tác xã - bảng ``organizations``).
- Module User (tài khoản đăng nhập gắn với ``organization_id`` - bảng ``users``).
- Module Farm (thửa đất / vùng trồng có tọa độ GPS, diện tích > 0 gắn với ``organization_id`` - bảng ``farms``).
- Module Batch (lô nông sản - bảng ``batches``).
- Module AuditLog (nhật ký hoạt động - bảng ``audit_logs``).

Quan hệ giữa các bảng:
    Organization 1 ---- N User
    Organization 1 ---- N Farm
    Farm 1         ---- N Batch
    User 1         ---- N AuditLog
"""

from datetime import date, datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _naive_utcnow() -> datetime:
    """Thời điểm hiện tại theo UTC, không kèm tzinfo."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ------------------------------------------------------------- Vai trò ---
ROLE_ADMIN: str = "admin"
ROLE_FARMER: str = "farmer"
ROLES: tuple[str, ...] = (ROLE_ADMIN, ROLE_FARMER)


class Organization(Base):
    """Tổ chức / Hợp tác xã / Doanh nghiệp nông nghiệp - bảng ``organizations``.

    Kiến trúc Multi-tenant: mỗi người dùng và vùng trồng đều gắn với một tổ chức.
    """

    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_naive_utcnow,
    )

    users: Mapped[list["User"]] = relationship(
        back_populates="organization",
    )
    farms: Mapped[list["Farm"]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Organization id={self.id} code={self.code!r} name={self.name!r}>"


class User(Base):
    """Tài khoản đăng nhập của hệ thống - bảng ``users``.

    Mỗi tài khoản gắn với một ``organization_id`` (trừ admin hệ thống có thể quản lý chung).
    Mật khẩu băm bằng chuẩn Argon2id.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id"),
        nullable=True,
        index=True,
    )
    username: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        unique=True,
        index=True,
    )
    # 255 ký tự để chứa chuỗi băm Argon2id (~97-100 ký tự)
    password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=ROLE_FARMER)

    # Bảo mật đăng nhập: đếm số lần sai liên tiếp, khóa 15 phút nếu sai 5 lần
    failed_login_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    organization: Mapped["Organization | None"] = relationship(back_populates="users")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User id={self.id} username={self.username!r} role={self.role}>"


class Farm(Base):
    """Vùng trồng nông sản / thửa đất - bảng ``farms``.

    Thuộc sở hữu của một ``organization_id`` cụ thể để cách ly dữ liệu.
    Diện tích (area) bắt buộc > 0 (ràng buộc CheckConstraint ở DB).
    """

    __tablename__ = "farms"
    __table_args__ = (
        CheckConstraint("area > 0", name="check_farm_area_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[str] = mapped_column(String(255), nullable=False)
    area: Mapped[float] = mapped_column(Float, nullable=False)
    coordinates: Mapped[str | None] = mapped_column(String(255), nullable=True)  # Tọa độ GPS (VD: "10.4539, 105.6324")
    owner: Mapped[str] = mapped_column(String(255), nullable=False)

    organization: Mapped["Organization"] = relationship(back_populates="farms")
    batches: Mapped[list["Batch"]] = relationship(
        back_populates="farm",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Farm id={self.id} name={self.name!r} area={self.area}ha>"


class Batch(Base):
    """Lô nông sản thu hoạch từ một vùng trồng - bảng ``batches``."""

    __tablename__ = "batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    farm_id: Mapped[int] = mapped_column(
        ForeignKey("farms.id"),
        nullable=False,
        index=True,
    )
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    harvest_date: Mapped[date] = mapped_column(Date, nullable=False)

    farm: Mapped["Farm"] = relationship(back_populates="batches")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Batch id={self.id} farm_id={self.farm_id} product_name={self.product_name!r}>"


# ------------------------------------- Lịch sử thao tác (audit log) ---
ACTION_CREATE: str = "create"
ACTION_UPDATE: str = "update"
ACTION_DELETE: str = "delete"
ACTIONS: tuple[str, ...] = (ACTION_CREATE, ACTION_UPDATE, ACTION_DELETE)

ENTITY_FARM: str = "farm"
ENTITY_BATCH: str = "batch"
ENTITIES: tuple[str, ...] = (ENTITY_FARM, ENTITY_BATCH)


class AuditLog(Base):
    """Một dòng lịch sử thao tác - bảng ``audit_logs``."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    entity: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_naive_utcnow,
    )

    user: Mapped["User"] = relationship()

    @property
    def username(self) -> str:
        return self.user.username if self.user is not None else ""

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<AuditLog id={self.id} user_id={self.user_id} "
            f"action={self.action!r} entity={self.entity!r} "
            f"entity_id={self.entity_id}>"
        )


__all__ = [
    "ACTION_CREATE",
    "ACTION_DELETE",
    "ACTION_UPDATE",
    "ACTIONS",
    "AuditLog",
    "Base",
    "Batch",
    "ENTITIES",
    "ENTITY_BATCH",
    "ENTITY_FARM",
    "Farm",
    "Organization",
    "ROLE_ADMIN",
    "ROLE_FARMER",
    "ROLES",
    "User",
]
