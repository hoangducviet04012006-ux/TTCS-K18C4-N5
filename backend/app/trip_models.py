"""Khai báo ORM models cho module Quản lý Chuyến xe lạnh (Cold Trips - S-40).

Gồm 2 bảng:
1. cold_trips: Quản lý chuyến xe lạnh (mã chuyến, mã thùng, tài xế, trạng thái, thời gian).
2. cold_trip_batches: Bảng trung gian liên kết nhiều lô nông sản với một chuyến xe.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
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

# Loại sự kiện vòng đời chuyến xe trên hash-chain của lô
EVENT_TRIP_DISPATCH: str = "TRIP_DISPATCH"
EVENT_TRIP_DELIVER: str = "TRIP_DELIVER"


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

    @property
    def batch_count(self) -> int:
        return len(self.trip_batches)

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
