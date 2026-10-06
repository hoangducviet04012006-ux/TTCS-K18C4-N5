"""Module dịch vụ hỗ trợ T-58: Truy vấn tổng hợp chi tiết lô kèm lô mẹ và lô con trực tiếp.

Đảm bảo:
1. Chỉ lấy lô mẹ TRỰC TIẾP (direct parent) và các lô con TRỰC TIẾP (direct children).
2. Tối ưu hóa câu lệnh SQL (Joinedload / Selectinload) để hoàn toàn KHÔNG bị lỗi N+1 query.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models import Batch


def get_batch_with_direct_relations(db: Session, batch_id: int) -> Batch | None:
    """Truy vấn một lô nông sản theo batch_id kèm thông tin quan hệ trực tiếp.

    Sử dụng ``joinedload`` và ``selectinload`` để nạp trước (eager load):
    - Vùng trồng (farm) và tổ chức nắm giữ (current_org) của lô chính.
    - Lô mẹ trực tiếp (parent) kèm tổ chức nắm giữ của lô mẹ.
    - Các lô con trực tiếp (children) kèm tổ chức nắm giữ của từng lô con.

    Hành vi này loại bỏ hoàn toàn N+1 query (chỉ phát sinh đúng 1-2 câu SQL).

    Args:
        db: Session SQLAlchemy.
        batch_id: ID lô nông sản cần tìm.

    Returns:
        Batch | None: Đối tượng Batch đã nạp đủ dữ liệu hoặc None nếu không tìm thấy.
    """
    stmt = (
        select(Batch)
        .options(
            joinedload(Batch.farm),
            joinedload(Batch.current_org),
            joinedload(Batch.parent).joinedload(Batch.current_org),
            selectinload(Batch.children).joinedload(Batch.current_org),
        )
        .where(Batch.id == batch_id)
    )
    return db.scalar(stmt)


def build_batch_tree_response(batch: Batch) -> dict[str, Any]:
    """Chuyển đổi đối tượng Batch ORM thành dict chuẩn cấu trúc T-58.

    Cấu trúc trả về:
    - ``batch``: Thông tin lô hiện tại (id, product, remaining_quantity, unit, location, status, ...).
    - ``parent``: Thông tin lô mẹ trực tiếp (hoặc None nếu không có).
    - ``children``: Danh sách các lô con trực tiếp (hoặc [] nếu không có).

    Args:
        batch: Bản ghi Batch đã được nạp đủ quan hệ.

    Returns:
        dict: Dữ liệu JSON sẵn sàng trả về cho API client.
    """
    holding_org = batch.current_org_name or "Tổ chức chưa xác định"
    location_str = batch.farm.location if batch.farm else holding_org

    main_info = {
        "id": batch.id,
        "product": batch.product_name,
        "product_name": batch.product_name,
        "quantity": batch.quantity,
        "remaining_quantity": batch.remaining_qty,
        "unit": batch.batch_unit,
        "location": location_str,
        "status": batch.batch_status,
        "current_org_name": holding_org,
        "harvest_date": batch.harvest_date,
        "farm_id": batch.farm_id,
        "farm_name": batch.farm.name if batch.farm else None,
    }

    parent_info = None
    if batch.parent is not None:
        parent_info = {
            "id": batch.parent.id,
            "product": batch.parent.product_name,
            "product_name": batch.parent.product_name,
            "quantity": batch.parent.quantity,
            "remaining_quantity": batch.parent.remaining_qty,
            "unit": batch.parent.batch_unit,
            "status": batch.parent.batch_status,
            "current_org_name": batch.parent.current_org_name or "Tổ chức chưa xác định",
        }

    children_info = []
    if batch.children:
        for child in batch.children:
            children_info.append(
                {
                    "id": child.id,
                    "product": child.product_name,
                    "product_name": child.product_name,
                    "quantity": child.quantity,
                    "remaining_quantity": child.remaining_qty,
                    "unit": child.batch_unit,
                    "status": child.batch_status,
                    "current_org_name": child.current_org_name or "Tổ chức chưa xác định",
                }
            )

    return {
        "batch": main_info,
        "parent": parent_info,
        "children": children_info,
    }
