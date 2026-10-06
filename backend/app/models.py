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
    Index,
    Integer,
    String,
    text,
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

# ----------------------------------------------- Trạng thái bàn giao ---
HANDOVER_PENDING: str = "PENDING"
HANDOVER_ACCEPTED: str = "ACCEPTED"
HANDOVER_REJECTED: str = "REJECTED"
HANDOVER_STATUSES: tuple[str, ...] = (
    HANDOVER_PENDING,
    HANDOVER_ACCEPTED,
    HANDOVER_REJECTED,
)

EVENT_HANDOVER_PENDING: str = "HANDOVER_PENDING"
EVENT_HANDOVER_ACCEPTED: str = "HANDOVER_ACCEPTED"
EVENT_HANDOVER_REJECTED: str = "HANDOVER_REJECTED"


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

    # Tổ chức hiện tại đang nắm giữ / sở hữu lô (chuyển đổi qua bàn giao)
    current_org_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id"),
        nullable=True,
        index=True,
    )

    farm: Mapped["Farm"] = relationship(back_populates="batches")
    current_org: Mapped["Organization | None"] = relationship(foreign_keys=[current_org_id])
    handovers: Mapped[list["Handover"]] = relationship(
        back_populates="batch",
        cascade="all, delete-orphan",
        order_by="Handover.created_at.desc()",
    )
    events: Mapped[list["BatchEvent"]] = relationship(
        back_populates="batch",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="BatchEvent.created_at.desc()",
    )

    @property
    def holder_org_id(self) -> int | None:
        """ID tổ chức hiện tại đang giữ lô (nếu chưa gán thì fallback theo farm)."""
        if self.current_org_id is not None:
            return self.current_org_id
        if self.farm is not None:
            return self.farm.organization_id
        return None

    @property
    def current_org_name(self) -> str | None:
        """Tên tổ chức hiện tại đang giữ lô."""
        if self.current_org is not None:
            return self.current_org.name
        if self.farm is not None and self.farm.organization is not None:
            return self.farm.organization.name
        return None

    @property
    def pending_handover(self) -> "Handover | None":
        """Yêu cầu bàn giao đang ở trạng thái PENDING (nếu có)."""
        for h in self.handovers:
            if h.status == HANDOVER_PENDING:
                return h
        return None

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Batch id={self.id} farm_id={self.farm_id} product_name={self.product_name!r}>"


class Handover(Base):
    """Bàn giao lô nông sản giữa các tổ chức - bảng ``handovers``."""

    __tablename__ = "handovers"
    __table_args__ = (
        Index(
            "uq_batch_pending_handover",
            "batch_id",
            unique=True,
            sqlite_where=text("status = 'PENDING'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("batches.id"),
        nullable=False,
        index=True,
    )
    from_org_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"),
        nullable=False,
        index=True,
    )
    to_org_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=HANDOVER_PENDING,
    )
    reject_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_naive_utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_naive_utcnow,
        onupdate=_naive_utcnow,
    )

    batch: Mapped["Batch"] = relationship(back_populates="handovers")
    from_org: Mapped["Organization"] = relationship(foreign_keys=[from_org_id])
    to_org: Mapped["Organization"] = relationship(foreign_keys=[to_org_id])

    @property
    def batch_product_name(self) -> str | None:
        return self.batch.product_name if self.batch else None

    @property
    def batch_quantity(self) -> float | None:
        return self.batch.quantity if self.batch else None

    @property
    def from_org_name(self) -> str | None:
        return self.from_org.name if self.from_org else None

    @property
    def to_org_name(self) -> str | None:
        return self.to_org.name if self.to_org else None

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Handover id={self.id} batch_id={self.batch_id} "
            f"from={self.from_org_id} to={self.to_org_id} status={self.status!r}>"
        )


class BatchEvent(Base):
    """Sự kiện vòng đời lô hàng phục vụ truy xuất nguồn gốc - bảng ``batch_events``."""

    __tablename__ = "batch_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )
    from_org_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id"),
        nullable=True,
    )
    to_org_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id"),
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    event_data: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_naive_utcnow,
    )
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="0" * 64, server_default="0" * 64)
    record_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")

    batch: Mapped["Batch"] = relationship(back_populates="events")
    user: Mapped["User | None"] = relationship()
    from_org: Mapped["Organization | None"] = relationship(foreign_keys=[from_org_id])
    to_org: Mapped["Organization | None"] = relationship(foreign_keys=[to_org_id])

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<BatchEvent id={self.id} batch_id={self.batch_id} "
            f"event_type={self.event_type!r}>"
        )


from sqlalchemy import event  # noqa: E402


@event.listens_for(BatchEvent, "before_update")
def _prevent_batch_event_update(mapper, connection, target):
    raise PermissionError("S-11: Batch events are append-only and cannot be updated.")


@event.listens_for(BatchEvent, "before_delete")
def _prevent_batch_event_delete(mapper, connection, target):
    raise PermissionError("S-11: Batch events are append-only and cannot be deleted.")


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
    "BatchEvent",
    "ENTITIES",
    "ENTITY_BATCH",
    "ENTITY_FARM",
    "EVENT_HANDOVER_ACCEPTED",
    "EVENT_HANDOVER_PENDING",
    "EVENT_HANDOVER_REJECTED",
    "Farm",
    "HANDOVER_ACCEPTED",
    "HANDOVER_PENDING",
    "HANDOVER_REJECTED",
    "HANDOVER_STATUSES",
    "Handover",
    "Organization",
    "ROLE_ADMIN",
    "ROLE_FARMER",
    "ROLES",
    "User",
]
