"""Khai báo ORM models (bảng dữ liệu) bằng SQLAlchemy 2.0.

Sprint 1:
- Module Organization (tổ chức / hợp tác xã - bảng ``organizations``).
- Module User (tài khoản đăng nhập gắn với ``organization_id`` - bảng ``users``).
- Module Farm (thửa đất / vùng trồng có tọa độ GPS, diện tích > 0 gắn với ``organization_id`` - bảng ``farms``).
- Module AuditLog (nhật ký hoạt động - bảng ``audit_logs``).

Sprint 2:
- Module Product (sản phẩm dùng chung toàn hệ thống - bảng ``products``) (T-16).
- Module Plot (thửa đất canh tác - bảng ``plots``).
- Module Batch (lô nông sản thu hoạch, mã 8 ký tự, trạng thái - bảng ``batches``) (T-18).
- Module BatchEvent (sự kiện truy xuất nguồn gốc append-only hash-chain - bảng ``batch_events``) (T-23).
- Module Handover (bàn giao lô hàng giữa các tổ chức - bảng ``handovers``) (T-35).
"""

import enum
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum as SQLEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _naive_utcnow() -> datetime:
    """Thời điểm hiện tại theo UTC, không kèm tzinfo."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ------------------------------------------------------------- 7 Vai trò chính thức (Giai đoạn 1B) ---
ROLE_SYSTEM_ADMIN: str = "system_admin"
ROLE_ORG_ADMIN: str = "org_admin"
ROLE_FARMER: str = "farmer"
ROLE_PROCESSOR: str = "processor"
ROLE_TRANSPORTER: str = "transporter"
ROLE_DISTRIBUTOR: str = "distributor"
ROLE_INSPECTOR: str = "inspector"

# Legacy alias để tương thích ngược với tài khoản cũ trước migration
ROLE_ADMIN: str = "admin"

OFFICIAL_ROLES: tuple[str, ...] = (
    ROLE_SYSTEM_ADMIN,
    ROLE_ORG_ADMIN,
    ROLE_FARMER,
    ROLE_PROCESSOR,
    ROLE_TRANSPORTER,
    ROLE_DISTRIBUTOR,
    ROLE_INSPECTOR,
)

ROLES: tuple[str, ...] = OFFICIAL_ROLES + (ROLE_ADMIN,)

# ----------------------------------------------- Trạng thái bàn giao ---
HANDOVER_PENDING: str = "PENDING"
HANDOVER_ACCEPTED: str = "ACCEPTED"
HANDOVER_REJECTED: str = "REJECTED"
HANDOVER_STATUSES: tuple[str, ...] = (
    HANDOVER_PENDING,
    HANDOVER_ACCEPTED,
    HANDOVER_REJECTED,
)

# Các loại sự kiện vòng đời lô hàng (Sprint 2 - T-23)
EVENT_HARVEST: str = "HARVEST"
EVENT_HANDOVER_INIT: str = "HANDOVER_INIT"
EVENT_HANDOVER_ACCEPT: str = "HANDOVER_ACCEPT"
EVENT_HANDOVER_REJECT: str = "HANDOVER_REJECT"

EVENT_SPLIT: str = "SPLIT"
EVENT_GENESIS_SPLIT: str = "GENESIS_SPLIT"
EVENT_MERGE: str = "MERGE"
EVENT_EXPORT_MERGE: str = "EXPORT_MERGE"
EVENT_CONSUMED: str = "CONSUMED"

# Các loại quan hệ phả hệ lô (Sprint 3 - T-39)
RELATION_SPLIT: str = "SPLIT"
RELATION_MERGE: str = "MERGE"
RELATION_TYPES: tuple[str, ...] = (RELATION_SPLIT, RELATION_MERGE)

# Trạng thái lô nông sản (Sprint 4 - S-29)
BATCH_STATUS_ACTIVE: str = "ACTIVE"
BATCH_STATUS_CONSUMED: str = "CONSUMED"
BATCH_STATUS_SPLIT: str = "SPLIT"
BATCH_STATUS_MERGED: str = "MERGED"
BATCH_STATUSES: tuple[str, ...] = (
    BATCH_STATUS_ACTIVE,
    BATCH_STATUS_CONSUMED,
    BATCH_STATUS_SPLIT,
    BATCH_STATUS_MERGED,
)

# Hỗ trợ tương thích ngược Sprint 1
EVENT_HANDOVER_PENDING: str = "HANDOVER_INIT"
EVENT_HANDOVER_ACCEPTED: str = "HANDOVER_ACCEPT"
EVENT_HANDOVER_REJECTED: str = "HANDOVER_REJECT"

# Sự kiện chuỗi lạnh & vi phạm nhiệt độ (Sprint Epic E-07 / User Story S-45)
EVENT_TEMPERATURE_VIOLATION: str = "TEMPERATURE_VIOLATION"
EVENT_SHIPMENT_START: str = "SHIPMENT_START"
EVENT_SHIPMENT_END: str = "SHIPMENT_END"

# Trạng thái chuỗi lạnh của lô nông sản (S-45)
COLD_CHAIN_NORMAL: str = "NORMAL"
COLD_CHAIN_WARNING: str = "WARNING"
COLD_CHAIN_VIOLATED: str = "VIOLATED"
COLD_CHAIN_STATUSES: tuple[str, ...] = (
    COLD_CHAIN_NORMAL,
    COLD_CHAIN_WARNING,
    COLD_CHAIN_VIOLATED,
)

# Trạng thái chuyến vận chuyển lạnh (S-40)
SHIPMENT_STATUS_IN_TRANSIT: str = "IN_TRANSIT"
SHIPMENT_STATUS_COMPLETED: str = "COMPLETED"
SHIPMENT_STATUS_CANCELLED: str = "CANCELLED"
SHIPMENT_STATUSES: tuple[str, ...] = (
    SHIPMENT_STATUS_IN_TRANSIT,
    SHIPMENT_STATUS_COMPLETED,
    SHIPMENT_STATUS_CANCELLED,
)

ENTITY_SHIPMENT: str = "shipment"


class ProductUnit(str, enum.Enum):
    """Đơn vị tính sản phẩm (T-16)."""

    KG = "kg"
    TAN = "tấn"
    THUNG = "thùng"


# ==============================================================================
# 1. BẢNG PRODUCTS (T-16)
# ==============================================================================
class Product(Base):
    """Bảng sản phẩm dùng chung toàn hệ thống - bảng ``products`` (T-16).

    Không có cột organization_id, không bị lọc theo tổ chức.
    """

    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("unit IN ('kg', 'tấn', 'thùng')", name="check_product_unit_enum"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    unit: Mapped[str] = mapped_column(
        SQLEnum(ProductUnit, values_callable=lambda x: [e.value for e in x], native_enum=False),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_naive_utcnow,
    )

    batches: Mapped[list["Batch"]] = relationship(back_populates="product")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Product id={self.id} name={self.name!r} unit={self.unit!r}>"


# ==============================================================================
# 2. BẢNG ORGANIZATIONS & USERS
# ==============================================================================
class Organization(Base):
    """Tổ chức / Hợp tác xã / Doanh nghiệp nông nghiệp - bảng ``organizations``."""

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

    users: Mapped[list["User"]] = relationship(back_populates="organization")
    farms: Mapped[list["Farm"]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    plots: Mapped[list["Plot"]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Organization id={self.id} code={self.code!r} name={self.name!r}>"


class User(Base):
    """Tài khoản đăng nhập của hệ thống - bảng ``users``."""

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
    # S-04: cho phép đăng nhập bằng email. Nullable để tương thích ngược với
    # các bản ghi cũ (chưa có email) - người dùng vẫn đăng nhập được bằng username.
    email: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )
    password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=ROLE_FARMER)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")

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


# ==============================================================================
# 3. BẢNG PLOTS & FARMS (THỬA ĐẤT / VÙNG TRỒNG)
# ==============================================================================
class Plot(Base):
    """Thửa đất canh tác - bảng ``plots`` (T-18)."""

    __tablename__ = "plots"
    __table_args__ = (
        CheckConstraint("area > 0", name="check_plot_area_positive"),
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
    coordinates: Mapped[str | None] = mapped_column(String(255), nullable=True)
    owner: Mapped[str] = mapped_column(String(255), nullable=False)

    organization: Mapped["Organization"] = relationship(back_populates="plots")
    batches: Mapped[list["Batch"]] = relationship(
        back_populates="plot",
        foreign_keys="Batch.plot_id",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Plot id={self.id} name={self.name!r} area={self.area}ha>"


class Farm(Base):
    """Vùng trồng nông sản / thửa đất - bảng ``farms`` (Sprint 1)."""

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
    coordinates: Mapped[str | None] = mapped_column(String(255), nullable=True)
    owner: Mapped[str] = mapped_column(String(255), nullable=False)

    organization: Mapped["Organization"] = relationship(back_populates="farms")
    batches: Mapped[list["Batch"]] = relationship(
        back_populates="farm",
        cascade="all, delete-orphan",
        foreign_keys="Batch.farm_id",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Farm id={self.id} name={self.name!r} area={self.area}ha>"


# ==============================================================================
# 4. BẢNG BATCHES (LÔ THU HOẠCH - T-18)
# ==============================================================================
class Batch(Base):
    """Lô thu hoạch nông sản - bảng ``batches`` (T-18).

    Bao gồm:
    - id: Integer, primary key
    - code: String(20), unique=True, index=True
    - plot_id: Integer, ForeignKey('plots.id'), nullable=False
    - product_id: Integer, ForeignKey('products.id'), nullable=False
    - harvest_date: Date, nullable=False
    - initial_quantity: Numeric(10, 2), nullable=False
    - remaining_quantity: Numeric(10, 2), nullable=False (remaining_quantity >= 0)
    - current_org_id: Integer, ForeignKey('organizations.id'), index=True, nullable=False
    - status: String(30), default='ACTIVE'
    """

    __tablename__ = "batches"
    __table_args__ = (
        CheckConstraint("remaining_quantity >= 0", name="check_batch_remaining_quantity_non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    plot_id: Mapped[int] = mapped_column(
        ForeignKey("plots.id"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id"),
        nullable=False,
        index=True,
    )
    harvest_date: Mapped[date] = mapped_column(Date, nullable=False)
    initial_quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    remaining_quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    current_org_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="ACTIVE", server_default="ACTIVE")

    # Giám sát chuỗi lạnh và cảnh báo vi phạm nhiệt độ (Task S-45)
    cold_chain_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="NORMAL", server_default="NORMAL"
    )
    has_temperature_violation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )

    # Thuộc tính nguồn gốc dữ liệu phục vụ kiến trúc hợp nhất thống nhất (Unified AgriTrace)
    origin_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dataset_source: Mapped[str] = mapped_column(
        String(50), nullable=False, default="operational", server_default="operational"
    )
    is_simulation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")

    # Các cột hỗ trợ tương thích ngược Sprint 1
    farm_id: Mapped[int | None] = mapped_column(ForeignKey("farms.id"), nullable=True, index=True)
    product_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Relationships
    plot: Mapped["Plot | None"] = relationship(foreign_keys=[plot_id], back_populates="batches")
    farm: Mapped["Farm | None"] = relationship(foreign_keys=[farm_id], back_populates="batches")
    product: Mapped["Product | None"] = relationship(back_populates="batches")
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
        order_by="BatchEvent.timestamp.desc()",
    )
    parent_relations: Mapped[list["BatchRelation"]] = relationship(
        "BatchRelation",
        foreign_keys="BatchRelation.child_batch_id",
        back_populates="child_batch",
        cascade="all, delete-orphan",
    )
    child_relations: Mapped[list["BatchRelation"]] = relationship(
        "BatchRelation",
        foreign_keys="BatchRelation.parent_batch_id",
        back_populates="parent_batch",
        cascade="all, delete-orphan",
    )
    temperature_violations: Mapped[list["TemperatureViolation"]] = relationship(
        "TemperatureViolation",
        back_populates="batch",
        cascade="all, delete-orphan",
        order_by="TemperatureViolation.created_at.desc()",
    )
    shipments: Mapped[list["Shipment"]] = relationship(
        "Shipment",
        secondary="shipment_batches",
        back_populates="batches",
    )

    @property
    def location_id(self):
        return getattr(self, "_phase_c_location", {}).get("id")

    @property
    def current_location(self):
        return getattr(self, "_phase_c_location", {}).get("address")

    @property
    def current_location_name(self):
        return getattr(self, "_phase_c_location", {}).get("name")

    def __init__(self, **kwargs: Any) -> None:
        """Hỗ trợ tự động điền các trường mặc định và tương thích Sprint 1."""
        from app.utils.batch_code import generate_batch_code

        # Tự sinh mã lô nếu chưa có
        if "code" not in kwargs or not kwargs["code"]:
            kwargs["code"] = generate_batch_code()

        # Đồng bộ plot_id và farm_id
        if "plot_id" in kwargs and kwargs["plot_id"] is not None:
            if "farm_id" not in kwargs or kwargs["farm_id"] is None:
                kwargs["farm_id"] = kwargs["plot_id"]
        elif "farm_id" in kwargs and kwargs["farm_id"] is not None:
            kwargs["plot_id"] = kwargs["farm_id"]

        # Đồng bộ khối lượng
        if "initial_quantity" in kwargs and kwargs["initial_quantity"] is not None:
            qty_dec = Decimal(str(kwargs["initial_quantity"]))
            kwargs["initial_quantity"] = qty_dec
            if "remaining_quantity" not in kwargs or kwargs["remaining_quantity"] is None:
                kwargs["remaining_quantity"] = qty_dec
            if "quantity" not in kwargs or kwargs["quantity"] is None:
                kwargs["quantity"] = float(qty_dec)
        elif "quantity" in kwargs and kwargs["quantity"] is not None:
            qty_dec = Decimal(str(kwargs["quantity"]))
            kwargs["initial_quantity"] = qty_dec
            kwargs["remaining_quantity"] = qty_dec

        # Đảm bảo remaining_quantity có giá trị
        if "remaining_quantity" not in kwargs and "initial_quantity" in kwargs:
            kwargs["remaining_quantity"] = kwargs["initial_quantity"]

        # Tự động gán product_id mặc định = 1 nếu chỉ có product_name (cho test cũ)
        if ("product_id" not in kwargs or kwargs["product_id"] is None) and "product_name" in kwargs:
            kwargs["product_id"] = 1

        if "cold_chain_status" not in kwargs or not kwargs["cold_chain_status"]:
            kwargs["cold_chain_status"] = "NORMAL"
        if "has_temperature_violation" not in kwargs:
            kwargs["has_temperature_violation"] = False

        super().__init__(**kwargs)

    @property
    def unit(self) -> str:
        if not self.product:
            return "kg"
        unit = self.product.unit
        return str(unit.value if isinstance(unit, ProductUnit) else unit)

    @property
    def holder_org_id(self) -> int | None:
        """ID tổ chức hiện tại đang giữ lô."""
        if self.current_org_id is not None:
            return self.current_org_id
        if self.plot is not None:
            return self.plot.organization_id
        if self.farm is not None:
            return self.farm.organization_id
        return None

    @property
    def current_org_name(self) -> str | None:
        """Tên tổ chức hiện tại đang giữ lô."""
        if self.current_org is not None:
            return self.current_org.name
        if self.plot is not None and self.plot.organization is not None:
            return self.plot.organization.name
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

    @property
    def is_pending(self) -> bool:
        """Lô đang có yêu cầu bàn giao chờ xác nhận (PENDING) hay không (T-56, T-57).

        Được dùng để đánh dấu trạng thái chờ bàn giao hiển thị cho CẢ bên gửi
        (xem trong danh sách lô) lẫn bên nhận (xem trong danh sách chờ duyệt).
        """
        return self.pending_handover is not None

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Batch id={self.id} code={self.code!r} plot_id={self.plot_id} status={self.status}>"


# ==============================================================================
# 4.1. BẢNG BATCH_RELATIONS (QUAN HỆ PHẢ HỆ LÔ TÁCH / GỘP - T-39)
# ==============================================================================
class BatchRelation(Base):
    """Quan hệ phả hệ lô nông sản (tách / gộp) - bảng ``batch_relations`` (T-39).

    Bao gồm:
    - id: Integer, primary key
    - parent_batch_id: Integer, ForeignKey('batches.id'), index=True, nullable=False
    - child_batch_id: Integer, ForeignKey('batches.id'), index=True, nullable=False
    - transferred_quantity: Numeric(10, 2), nullable=False
    - relation_type: String(20), nullable=False ('SPLIT' hoặc 'MERGE')
    - created_at: DateTime(timezone=True), nullable=False
    - UniqueConstraint('parent_batch_id', 'child_batch_id')
    - Index trên cả parent_batch_id và child_batch_id để tối ưu truy vấn 2 chiều.
    """

    __tablename__ = "batch_relations"
    __table_args__ = (
        UniqueConstraint("parent_batch_id", "child_batch_id", name="uq_parent_child_batch"),
        Index("idx_batch_relations_parent", "parent_batch_id"),
        Index("idx_batch_relations_child", "child_batch_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parent_batch_id: Mapped[int] = mapped_column(
        ForeignKey("batches.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    child_batch_id: Mapped[int] = mapped_column(
        ForeignKey("batches.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    transferred_quantity: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
    )
    relation_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_naive_utcnow,
    )

    parent_batch: Mapped["Batch"] = relationship(
        "Batch",
        foreign_keys=[parent_batch_id],
        back_populates="child_relations",
    )
    child_batch: Mapped["Batch"] = relationship(
        "Batch",
        foreign_keys=[child_batch_id],
        back_populates="parent_relations",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<BatchRelation id={self.id} parent={self.parent_batch_id} "
            f"child={self.child_batch_id} type={self.relation_type!r} qty={self.transferred_quantity}>"
        )


# ==============================================================================
# 5. BẢNG HANDOVERS (BÀN GIAO LÔ HÀNG - T-35)
# ==============================================================================
class Handover(Base):
    """Bàn giao lô nông sản giữa các tổ chức - bảng ``handovers`` (T-35).

    Ràng buộc: Mỗi lô tại một thời điểm chỉ có tối đa 1 bản ghi handover ở trạng thái PENDING.
    """

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
        server_default=HANDOVER_PENDING,
    )
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_overdue: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_naive_utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_naive_utcnow,
        onupdate=_naive_utcnow,
    )

    batch: Mapped["Batch"] = relationship(back_populates="handovers")
    from_org: Mapped["Organization"] = relationship(foreign_keys=[from_org_id])
    to_org: Mapped["Organization"] = relationship(foreign_keys=[to_org_id])

    @property
    def batch_product_name(self) -> str | None:
        if self.batch:
            if self.batch.product:
                return self.batch.product.name
            return self.batch.product_name
        return None

    @property
    def batch_code(self) -> str | None:
        return self.batch.code if self.batch else None

    @property
    def batch_quantity(self) -> float | None:
        if self.batch:
            if self.batch.remaining_quantity is not None:
                return float(self.batch.remaining_quantity)
            return self.batch.quantity
        return None

    @property
    def batch_unit(self) -> str:
        return self.batch.unit if self.batch else "kg"

    @property
    def note(self) -> str | None:
        for entry in self.batch.events if self.batch else []:
            payload = entry.payload or {}
            if entry.event_type == EVENT_HANDOVER_INIT and payload.get("handover_id") == self.id:
                return payload.get("note")
        return None

    @property
    def from_org_name(self) -> str | None:
        return self.from_org.name if self.from_org else None

    @property
    def to_org_name(self) -> str | None:
        return self.to_org.name if self.to_org else None

    @property
    def has_temperature_violation(self) -> bool:
        """Cờ cảnh báo lô hàng từng có sự cố vi phạm nhiệt độ chuỗi lạnh (S-45)."""
        if self.batch:
            return bool(getattr(self.batch, "has_temperature_violation", False))
        return False

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Handover id={self.id} batch_id={self.batch_id} "
            f"from={self.from_org_id} to={self.to_org_id} status={self.status!r}>"
        )


# ==============================================================================
# 6. BẢNG BATCH_EVENTS (SỰ KIỆN APPEND-ONLY HASH CHAIN - T-23)
# ==============================================================================
class BatchEvent(Base):
    """Sự kiện vòng đời lô hàng phục vụ truy xuất nguồn gốc - bảng ``batch_events`` (T-23).

    Bao gồm:
    - id: Integer, primary key
    - batch_id: Integer, ForeignKey('batches.id'), index=True, nullable=False
    - event_type: String(50), nullable=False (HARVEST, HANDOVER_INIT, HANDOVER_ACCEPT, HANDOVER_REJECT)
    - payload: JSON, nullable=False
    - organization_id: Integer, ForeignKey('organizations.id'), nullable=False
    - created_by_user_id: Integer, ForeignKey('users.id'), nullable=False
    - timestamp: DateTime(timezone=True), index=True, nullable=False
    - prev_hash: String(64), nullable=False
    - current_hash: String(64), nullable=False
    - Index kép trên (batch_id, timestamp)
    """

    __tablename__ = "batch_events"
    __table_args__ = (
        Index("idx_batch_events_batch_timestamp", "batch_id", "timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"),
        nullable=False,
        index=True,
    )
    created_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        default=_naive_utcnow,
    )
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="0" * 64, server_default="0" * 64)
    current_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")

    # Các cột tương thích ngược Sprint 1
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    from_org_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    to_org_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    event_data: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_naive_utcnow)
    record_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    origin_batch_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Relationships
    batch: Mapped["Batch"] = relationship(back_populates="events")
    user: Mapped["User | None"] = relationship(foreign_keys=[created_by_user_id])
    organization: Mapped["Organization | None"] = relationship(foreign_keys=[organization_id])
    from_org: Mapped["Organization | None"] = relationship(foreign_keys=[from_org_id])
    to_org: Mapped["Organization | None"] = relationship(foreign_keys=[to_org_id])

    def __init__(self, **kwargs: Any) -> None:
        # Tự động đồng bộ các trường alias nếu thiếu
        if "user_id" in kwargs and ("created_by_user_id" not in kwargs or kwargs["created_by_user_id"] is None):
            kwargs["created_by_user_id"] = kwargs["user_id"]
        elif "created_by_user_id" in kwargs and ("user_id" not in kwargs or kwargs["user_id"] is None):
            kwargs["user_id"] = kwargs["created_by_user_id"]

        if "current_hash" in kwargs and ("record_hash" not in kwargs or kwargs["record_hash"] is None):
            kwargs["record_hash"] = kwargs["current_hash"]
        elif "record_hash" in kwargs and ("current_hash" not in kwargs or kwargs["current_hash"] is None):
            kwargs["current_hash"] = kwargs["record_hash"]

        if "timestamp" in kwargs and ("created_at" not in kwargs or kwargs["created_at"] is None):
            kwargs["created_at"] = kwargs["timestamp"]
        elif "created_at" in kwargs and ("timestamp" not in kwargs or kwargs["timestamp"] is None):
            kwargs["timestamp"] = kwargs["created_at"]

        if "payload" not in kwargs:
            data = kwargs.get("event_data") or kwargs.get("notes") or ""
            kwargs["payload"] = {"description": data} if isinstance(data, str) else (data or {})

        if "organization_id" not in kwargs or kwargs["organization_id"] is None:
            kwargs["organization_id"] = kwargs.get("from_org_id") or 1

        super().__init__(**kwargs)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<BatchEvent id={self.id} batch_id={self.batch_id} "
            f"event_type={self.event_type!r} current_hash={self.current_hash[:8]}...>"
        )


# Immutability triggers ở tầng SQLAlchemy ORM (T-26, T-27)
@event.listens_for(BatchEvent, "before_update")
def _prevent_batch_event_update(mapper, connection, target):
    raise PermissionError("S-11: Batch events are append-only and cannot be updated.")


@event.listens_for(BatchEvent, "before_delete")
def _prevent_batch_event_delete(mapper, connection, target):
    raise PermissionError("S-11: Batch events are append-only and cannot be deleted.")


# ==============================================================================
# 7. BẢNG AUDIT_LOGS
# ==============================================================================
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

    @property
    def source_ip(self):
        return getattr(self, "_audit_details", {}).get("source_ip", None)

    @property
    def operation(self):
        return getattr(self, "_audit_details", {}).get("operation", None)

    @property
    def organization_id(self):
        return getattr(self, "_audit_details", {}).get("organization_id", None)

    @property
    def batch_ids(self):
        return getattr(self, "_audit_details", {}).get("batch_ids", [])

    @property
    def location_id(self):
        return getattr(self, "_audit_details", {}).get("location_id", None)

    @property
    def location_name(self):
        return getattr(self, "_audit_details", {}).get("location_name", None)

    @property
    def location_address(self):
        return getattr(self, "_audit_details", {}).get("location_address", None)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<AuditLog id={self.id} user_id={self.user_id} "
            f"action={self.action!r} entity={self.entity!r} "
            f"entity_id={self.entity_id}>"
        )


# ==============================================================================
# 8. BẢNG SHIPMENTS, SHIPMENT_BATCHES & TEMPERATURE_VIOLATIONS (S-40, S-45)
# ==============================================================================
class Shipment(Base):
    """Chuyến vận chuyển lạnh liên kết các lô hàng và thùng lạnh (S-40, S-45)."""

    __tablename__ = "shipments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    container_code: Mapped[str | None] = mapped_column(String(50), index=True, nullable=True)
    transporter_org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=SHIPMENT_STATUS_IN_TRANSIT, server_default=SHIPMENT_STATUS_IN_TRANSIT
    )
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_naive_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_naive_utcnow)

    transporter_org: Mapped["Organization"] = relationship(foreign_keys=[transporter_org_id])
    batches: Mapped[list["Batch"]] = relationship("Batch", secondary="shipment_batches", back_populates="shipments")
    violations: Mapped[list["TemperatureViolation"]] = relationship(
        "TemperatureViolation", back_populates="shipment", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Shipment id={self.id} code={self.code!r} status={self.status!r}>"


class ShipmentBatch(Base):
    """Bảng liên kết Nhiều - Nhiều giữa Shipment và Batch (S-40)."""

    __tablename__ = "shipment_batches"
    __table_args__ = (
        UniqueConstraint("shipment_id", "batch_id", name="uq_shipment_batch"),
        Index("idx_shipment_batches_shipment", "shipment_id"),
        Index("idx_shipment_batches_batch", "batch_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shipment_id: Mapped[int] = mapped_column(ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_naive_utcnow)


class TemperatureViolation(Base):
    """Bản ghi chi tiết sự cố vi phạm nhiệt độ chuỗi lạnh (S-43, S-45)."""

    __tablename__ = "temperature_violations"
    __table_args__ = (
        Index("idx_temp_violations_batch", "batch_id"),
        Index("idx_temp_violations_shipment", "shipment_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id", ondelete="CASCADE"), nullable=False, index=True)
    shipment_id: Mapped[int | None] = mapped_column(
        ForeignKey("shipments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    recorded_temperature: Mapped[float] = mapped_column(Float, nullable=False)
    min_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    peak_temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_naive_utcnow)
    end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="CRITICAL", server_default="CRITICAL")
    warning_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    event_id: Mapped[int | None] = mapped_column(
        ForeignKey("batch_events.id", ondelete="SET NULL"), nullable=True, index=True
    )
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_naive_utcnow)

    batch: Mapped["Batch"] = relationship("Batch", back_populates="temperature_violations")
    shipment: Mapped["Shipment | None"] = relationship("Shipment", back_populates="violations")
    event: Mapped["BatchEvent | None"] = relationship("BatchEvent")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TemperatureViolation id={self.id} batch_id={self.batch_id} temp={self.recorded_temperature}>"


__all__ = [
    "ACTION_CREATE",
    "ACTION_DELETE",
    "ACTION_UPDATE",
    "ACTIONS",
    "AuditLog",
    "Base",
    "Batch",
    "BatchEvent",
    "BatchRelation",
    "COLD_CHAIN_NORMAL",
    "COLD_CHAIN_STATUSES",
    "COLD_CHAIN_VIOLATED",
    "COLD_CHAIN_WARNING",
    "ENTITIES",
    "ENTITY_BATCH",
    "ENTITY_FARM",
    "ENTITY_SHIPMENT",
    "EVENT_EXPORT_MERGE",
    "EVENT_GENESIS_SPLIT",
    "EVENT_HANDOVER_ACCEPT",
    "EVENT_HANDOVER_ACCEPTED",
    "EVENT_HANDOVER_INIT",
    "EVENT_HANDOVER_PENDING",
    "EVENT_HANDOVER_REJECT",
    "EVENT_HANDOVER_REJECTED",
    "EVENT_HARVEST",
    "EVENT_MERGE",
    "EVENT_SHIPMENT_END",
    "EVENT_SHIPMENT_START",
    "EVENT_SPLIT",
    "EVENT_TEMPERATURE_VIOLATION",
    "RELATION_MERGE",
    "RELATION_SPLIT",
    "RELATION_TYPES",
    "Farm",
    "HANDOVER_ACCEPTED",
    "HANDOVER_PENDING",
    "HANDOVER_REJECTED",
    "HANDOVER_STATUSES",
    "Handover",
    "Organization",
    "Plot",
    "Product",
    "ProductUnit",
    "ROLE_ADMIN",
    "ROLE_FARMER",
    "ROLES",
    "Shipment",
    "ShipmentBatch",
    "TemperatureViolation",
    "User",
    "_naive_utcnow",
]

# Register trial Recall tables in metadata; startup excludes them explicitly.
from app.recall_models import Recall, RecallAcknowledgment, IdempotencyRecord  # noqa: E402,F401
from app.recall_models import register_event_evidence_index  # noqa: E402
register_event_evidence_index(BatchEvent.__table__)
