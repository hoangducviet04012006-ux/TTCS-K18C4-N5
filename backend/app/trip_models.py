"""Khai báo ORM models cho module Quản lý Chuyến xe lạnh (Cold Trips - S-40).

Gồm 2 bảng:
1. cold_trips: Quản lý chuyến xe lạnh (mã chuyến, mã thùng, tài xế, trạng thái, thời gian).
2. cold_trip_batches: Bảng trung gian liên kết nhiều lô nông sản với một chuyến xe.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _naive_utcnow() -> datetime:
    """Thời điểm hiện tại theo UTC, không kèm tzinfo."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# Trạng thái chuyến vận chuyển
TRIP_STATUS_IN_TRANSIT: str = "IN_TRANSIT"
TRIP_STATUS_COMPLETED: str = "COMPLETED"
TRIP_STATUS_CANCELLED: str = "CANCELLED"
TRIP_STATUSES: tuple[str, ...] = (
    TRIP_STATUS_IN_TRANSIT,
    TRIP_STATUS_COMPLETED,
    TRIP_STATUS_CANCELLED,
)

# Loại sự kiện vòng đời chuyến xe và giám sát nhiệt độ trên hash-chain của lô
EVENT_TRIP_DISPATCH: str = "TRIP_DISPATCH"
EVENT_TRIP_DELIVER: str = "TRIP_DELIVER"
EVENT_TEMPERATURE_VIOLATION: str = "TEMPERATURE_VIOLATION"


class ColdTrip(Base):
    """Bảng quản lý chuyến vận chuyển chuỗi lạnh - ``cold_trips`` (S-40).

    Khóa chính id INTEGER để tương thích hoàn toàn với S-41 (TemperatureLog).
    """

    __tablename__ = "cold_trips"
    __table_args__ = (
        Index("idx_cold_trips_container_status", "container_code", "status"),
        Index("idx_cold_trips_org_status", "transporter_org_id", "status"),
        Index(
            "uq_cold_trips_active_container",
            "container_code",
            unique=True,
            sqlite_where=text("status = 'IN_TRANSIT'"),
            postgresql_where=text("status = 'IN_TRANSIT'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trip_code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    container_code: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    transporter_org_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=TRIP_STATUS_IN_TRANSIT,
        server_default=TRIP_STATUS_IN_TRANSIT,
    )
    driver_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vehicle_plate: Mapped[str | None] = mapped_column(String(30), nullable=True)
    start_location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    destination_location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_time: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_naive_utcnow,
    )
    end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
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

    # Relationships
    transporter_org: Mapped["Organization"] = relationship(foreign_keys=[transporter_org_id])  # noqa: F821
    created_by_user: Mapped["User"] = relationship(foreign_keys=[created_by_user_id])  # noqa: F821
    trip_batches: Mapped[list["ColdTripBatch"]] = relationship(
        back_populates="trip",
        cascade="all, delete-orphan",
        order_by="ColdTripBatch.attached_at.asc()",
    )
    temperature_logs: Mapped[list["TemperatureLog"]] = relationship(
        back_populates="trip",
        cascade="all, delete-orphan",
        order_by="TemperatureLog.recorded_at.asc()",
    )
    violations: Mapped[list["TemperatureViolation"]] = relationship(
        back_populates="trip",
        foreign_keys="TemperatureViolation.trip_id",
        cascade="all, delete-orphan",
        order_by="TemperatureViolation.start_time.asc()",
    )

    @property
    def batch_count(self) -> int:
        return len(self.trip_batches)

    @property
    def violation_count(self) -> int:
        return len(self.violations) + len(self.detected_violations)

    detected_violations: Mapped[list["TemperatureViolation"]] = relationship(
        foreign_keys="TemperatureViolation.source_trip_id", viewonly=True,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ColdTrip id={self.id} code={self.trip_code!r} container={self.container_code!r} status={self.status}>"


class ColdTripBatch(Base):
    """Bảng trung gian N-N gán nhiều lô vào chuyến xe lạnh - ``cold_trip_batches`` (S-40)."""

    __tablename__ = "cold_trip_batches"
    __table_args__ = (
        UniqueConstraint("trip_id", "batch_id", name="uq_trip_batch"),
        Index("idx_cold_trip_batches_batch", "batch_id"),
        Index(
            "uq_cold_trip_batches_active_batch",
            "batch_id",
            unique=True,
            sqlite_where=text("detached_at IS NULL"),
            postgresql_where=text("detached_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trip_id: Mapped[int] = mapped_column(
        ForeignKey("cold_trips.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("batches.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    attached_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_naive_utcnow,
    )
    detached_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Relationships
    trip: Mapped["ColdTrip"] = relationship(back_populates="trip_batches")
    batch: Mapped["Batch"] = relationship(foreign_keys=[batch_id])  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ColdTripBatch id={self.id} trip_id={self.trip_id} batch_id={self.batch_id}>"


class TemperatureLog(Base):
    """Bảng lưu trữ số đo cảm biến nhiệt độ theo thời gian của chuyến xe - ``temperature_logs`` (S-41)."""

    __tablename__ = "temperature_logs"
    __table_args__ = (
        Index("idx_temperature_logs_trip_recorded", "trip_id", "recorded_at"),
        Index("idx_temperature_logs_container_recorded", "container_code", "recorded_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trip_id: Mapped[int] = mapped_column(
        ForeignKey("cold_trips.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    container_code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    temperature: Mapped[float] = mapped_column(Float, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=_naive_utcnow,
    )

    # Relationships
    trip: Mapped["ColdTrip"] = relationship(back_populates="temperature_logs")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TemperatureLog id={self.id} trip_id={self.trip_id} temp={self.temperature}°C at={self.recorded_at}>"


class TemperatureViolation(Base):
    """Bảng ghi nhận sự cố vi phạm nhiệt độ chuỗi lạnh - ``temperature_violations`` (S-43, S-45)."""

    __tablename__ = "temperature_violations"
    __table_args__ = (
        Index("idx_temp_violations_trip", "trip_id"),
        Index("idx_temp_violations_container", "container_code"),
        Index("idx_temp_violations_start_time", "start_time"),
        Index(
            "uq_temp_violations_trip_start",
            "trip_id",
            "start_time",
            unique=True,
            sqlite_where=text("trip_id IS NOT NULL"),
            postgresql_where=text("trip_id IS NOT NULL"),
        ),
        Index(
            "uq_temp_violations_batch_start",
            "batch_id",
            "start_time",
            unique=True,
            sqlite_where=text("batch_id IS NOT NULL"),
            postgresql_where=text("batch_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trip_id: Mapped[int | None] = mapped_column(
        ForeignKey("cold_trips.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("batches.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    source_trip_id: Mapped[int | None] = mapped_column(ForeignKey("cold_trips.id"), nullable=True)
    container_code: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_minutes: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    peak_temperature: Mapped[float] = mapped_column(Float, nullable=False)
    threshold_temperature: Mapped[float] = mapped_column(Float, nullable=False)
    min_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    violation_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="TEMPERATURE_EXCEEDED",
    )
    severity: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="WARNING",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="RESOLVED",
    )
    affected_batch_ids: Mapped[list[int]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
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

    # Relationships
    trip: Mapped["ColdTrip | None"] = relationship(back_populates="violations", foreign_keys=[trip_id])
    batch: Mapped["Batch | None"] = relationship(foreign_keys=[batch_id])  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<TemperatureViolation id={self.id} trip_id={self.trip_id} peak={self.peak_temperature}°C "
            f"duration={self.duration_minutes}m status={self.status}>"
        )


class ProductTemperatureSetting(Base):
    """Explicit product policy; absence means measurements cannot be evaluated."""

    __tablename__ = "product_temperature_settings"
    __table_args__ = (
        CheckConstraint("min_temperature < max_temperature", name="ck_temperature_range"),
        CheckConstraint("delay_minutes >= 30", name="ck_temperature_delay"),
    )

    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), primary_key=True)
    min_temperature: Mapped[float] = mapped_column(Float, nullable=False)
    max_temperature: Mapped[float] = mapped_column(Float, nullable=False)
    delay_minutes: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_naive_utcnow, onupdate=_naive_utcnow)
