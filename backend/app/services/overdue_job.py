"""Kiểm tra và gắn cờ bàn giao quá hạn 48 giờ (T-56, T-57)."""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import HANDOVER_PENDING, Handover

logger = logging.getLogger(__name__)


def check_overdue_handovers(db: Session, threshold_hours: int = 48) -> int:
    """Quét các yêu cầu bàn giao đang PENDING quá threshold_hours và đánh dấu is_overdue = True.

    Args:
        db: SQLAlchemy Session.
        threshold_hours: Số giờ tính là quá hạn (mặc định 48h).

    Returns:
        Số lượng bản ghi vừa được cập nhật cờ is_overdue.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now - timedelta(hours=threshold_hours)

    handovers = list(
        db.scalars(
            select(Handover).where(
                Handover.status == HANDOVER_PENDING,
                Handover.created_at <= cutoff,
                Handover.is_overdue.is_(False),
            )
        ).all()
    )

    count = 0
    for h in handovers:
        h.is_overdue = True
        count += 1

    if count > 0:
        db.commit()
        logger.info(f"[T-56] Đã gắn cờ is_overdue = True cho {count} yêu cầu bàn giao quá hạn {threshold_hours}h.")

    return count
