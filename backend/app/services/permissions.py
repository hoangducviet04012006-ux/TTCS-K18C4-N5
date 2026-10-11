"""Phân quyền truy cập thông tin lô theo phả hệ tổ tiên (T-54, T-55).

Quy tắc (T-54):
Một tổ chức được phép xem thông tin lô nếu:
1. Đang trực tiếp nắm giữ lô (current_org_id == user_org_id).
2. Từng nắm giữ lô thông qua bàn giao (Handover có status == 'ACCEPTED').
3. Lô đó là TỔ TIÊN của một lô mà tổ chức đang/từng nắm giữ.
Nếu không thỏa mãn -> Từ chối (HTTP 403 Forbidden).
"""

from collections import deque
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    HANDOVER_ACCEPTED,
    ROLE_INSPECTOR,
    Batch,
    BatchRelation,
    Handover,
)


def has_held_batch(db: Session, batch_id: int, org_id: int) -> bool:
    """Kiểm tra tổ chức đã từng nhận hoặc chuyển giao lô này qua handover hợp lệ."""
    handover_exists = db.scalar(
        select(Handover.id)
        .where(
            Handover.batch_id == batch_id,
            Handover.status == HANDOVER_ACCEPTED,
            (Handover.from_org_id == org_id) | (Handover.to_org_id == org_id),
        )
        .limit(1)
    )
    return handover_exists is not None


def can_view_batch(
    db: Session,
    user_org_id: int | None,
    batch_id: int,
    user_role: str | None = None,
) -> bool:
    """Kiểm tra quyền xem lô nông sản theo quan hệ sở hữu, phả hệ hoặc vai trò thanh tra."""
    target = db.get(Batch, batch_id)
    if target is None:
        return False

    # Vai trò thanh tra (inspector) có quyền đọc liên tổ chức
    if user_role == ROLE_INSPECTOR:
        return True

    if user_org_id is None:
        return False

    # 1. Tổ chức đang trực tiếp nắm giữ lô
    if target.current_org_id == user_org_id:
        return True

    # 2. Tổ chức từng nắm giữ lô qua bàn giao đã chấp nhận
    if has_held_batch(db, batch_id, user_org_id):
        return True

    # 3. Lô này là TỔ TIÊN của một lô mà tổ chức đang hoặc từng giữ.
    # Duyệt xuôi đồ thị theo chiều cha -> con (descendants) bằng BFS.
    visited_descendants: set[int] = {batch_id}
    queue: deque[int] = deque([batch_id])

    while queue:
        curr_id = queue.popleft()

        # Lấy tất cả các con trực tiếp của curr_id
        child_relations = db.scalars(
            select(BatchRelation.child_batch_id)
            .where(BatchRelation.parent_batch_id == curr_id)
        ).all()

        for child_id in child_relations:
            if child_id in visited_descendants:
                continue
            visited_descendants.add(child_id)

            child_batch = db.get(Batch, child_id)
            if child_batch:
                # Nếu tổ chức đang giữ con cháu này
                if child_batch.current_org_id == user_org_id:
                    return True
                # Hoặc từng giữ con cháu này qua bàn giao
                if has_held_batch(db, child_id, user_org_id):
                    return True

            queue.append(child_id)

    return False
