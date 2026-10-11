"""Recall trial schema. Never automatically migrated by application startup."""
from datetime import datetime

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint, event, func, text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


@event.listens_for(Base.metadata, "before_create")
def refuse_recall_schema_on_original(metadata, connection, tables, **kwargs):
    from app.services.recall_database import is_protected_engine
    if tables and is_protected_engine(connection.engine):
        raise RuntimeError("Schema creation is forbidden on backend/ttcs.db during the Recall trial")


def register_event_evidence_index(table):
    """One immutable event per Recall/action/batch/org, enforced by SQLite too."""
    return Index(
        "uq_recall_event_evidence", table.c.event_type, table.c.batch_id,
        func.json_extract(table.c.payload, "$.recall_id"),
        func.coalesce(func.json_extract(table.c.payload, "$.organization_id"), -1),
        unique=True,
        sqlite_where=table.c.event_type.in_([
            "RECALL_INIT", "RECALL_AFFECTED", "RECALL_ACKNOWLEDGED", "RECALL_COMPLETED"
        ]),
    )


class Recall(Base):
    __tablename__ = "recalls"
    __table_args__ = (
        CheckConstraint("length(trim(reason)) >= 20", name="check_recall_reason_len"),
        CheckConstraint("status IN ('OPEN','COMPLETED')", name="check_recall_status"),
        CheckConstraint(
            "(status='OPEN' AND completed_at IS NULL) OR "
            "(status='COMPLETED' AND completed_at IS NOT NULL)", name="check_recall_completed_at",
        ),
        # Temporary lifetime policy, pending mentor confirmation.
        Index("uq_recall_root_lifetime", "root_batch_id", unique=True),
        Index("uq_recall_open_per_root_batch", "root_batch_id", unique=True, sqlite_where=text("status='OPEN'")),
        {"info": {"recall_trial": True}},
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recall_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    root_batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id", ondelete="RESTRICT"), index=True)
    reason: Mapped[str] = mapped_column(Text)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_by_org_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(20), server_default="OPEN", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class RecallAcknowledgment(Base):
    __tablename__ = "recall_acknowledgments"
    __table_args__ = (
        UniqueConstraint("recall_id", "organization_id", name="uq_recall_org_ack"),
        CheckConstraint("status IN ('PENDING','ACKNOWLEDGED')", name="check_ack_status"),
        CheckConstraint(
            "(status='PENDING' AND acknowledged_by_user_id IS NULL AND acknowledged_at IS NULL) OR "
            "(status='ACKNOWLEDGED' AND acknowledged_by_user_id IS NOT NULL AND acknowledged_at IS NOT NULL)",
            name="check_ack_evidence",
        ),
        {"info": {"recall_trial": True}},
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recall_id: Mapped[int] = mapped_column(ForeignKey("recalls.id", ondelete="RESTRICT"), index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"), index=True)
    status: Mapped[str] = mapped_column(String(20), server_default="PENDING")
    acknowledged_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        CheckConstraint("length(key) BETWEEN 1 AND 128", name="check_idempotency_key"),
        {"info": {"recall_trial": True}},
    )
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True)
    endpoint: Mapped[str] = mapped_column(String(100), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    response_code: Mapped[int] = mapped_column(Integer)
    response_body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"), index=True)
