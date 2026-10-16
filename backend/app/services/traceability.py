"""Module thuật toán truy ngược nguồn gốc BFS (Breadth-First Search) và Cache (T-49, T-50).

- Tuyệt đối không dùng đệ quy để tránh tràn ngăn xếp (Stack Overflow) với đồ thị sâu.
- Duyệt từng tầng (Level-by-level) bằng collections.deque.
- Phát hiện chu trình (Cycle detection) và ném HTTP 400 nếu có vòng lặp phả hệ.
- Trả về cây phả hệ phân tầng và danh sách các lô thu hoạch gốc (thửa đất / vùng trồng ban đầu).
- Cache 60 giây in-memory giảm tải truy vấn DB (T-50).
"""

import time
from collections import deque
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import Batch, BatchRelation


# Bộ nhớ đệm in-memory (60s TTL - T-50)
# Structure: {batch_id: (expires_at_timestamp, cached_data)}
_TRACE_CACHE: dict[int, tuple[float, dict[str, Any]]] = {}
_FORWARD_CACHE: dict[int, tuple[float, dict[str, Any]]] = {}
CACHE_TTL_SECONDS: int = 60


def clear_trace_cache(batch_id: int | None = None) -> None:
    """Xóa bộ nhớ đệm truy xuất (truy ngược & truy xuôi)."""
    if batch_id is not None:
        _TRACE_CACHE.pop(batch_id, None)
        _FORWARD_CACHE.pop(batch_id, None)
    else:
        _TRACE_CACHE.clear()
        _FORWARD_CACHE.clear()


def trace_backwards(  # noqa: C901
    db: Session,
    batch_id: int,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Truy ngược phả hệ tổ tiên theo chiều con -> cha bằng thuật toán BFS lặp (T-49, T-50).

    Args:
        db: SQLAlchemy Session.
        batch_id: ID lô nông sản đích cần truy xuất.
        use_cache: Có sử dụng cache 60s hay không (mặc định True).

    Returns:
        Dict chứa:
        - target_batch: thông tin lô đích.
        - ancestors_by_level: dict {level: [TraceNode, ...]}.
        - root_batches: list các lô thu hoạch gốc (không có cha) kèm thửa đất.
        - total_ancestors: tổng số lô tổ tiên.

    Raises:
        HTTPException 404: nếu không tìm thấy lô.
        HTTPException 400: nếu phát hiện chu trình phả hệ bất thường (Cycle detected).
    """
    now = time.time()
    if use_cache and batch_id in _TRACE_CACHE:
        expires_at, cached_data = _TRACE_CACHE[batch_id]
        if now < expires_at:
            return cached_data

    target = db.get(Batch, batch_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy lô nông sản có id={batch_id}.",
        )

    # Queue lưu: (current_batch_id, current_level, path_tuple)
    # path_tuple lưu chuỗi các ID từ target ngược lên để phát hiện chu trình
    queue: deque[tuple[int, int, tuple[int, ...]]] = deque()
    queue.append((batch_id, 0, (batch_id,)))

    ancestors_by_level: dict[int, list[dict[str, Any]]] = {}
    visited_nodes: dict[int, dict[str, Any]] = {}  # batch_id -> node_dict
    all_ancestor_ids: set[int] = set()

    # Pre-load thông tin target_batch
    target_info = {
        "id": target.id,
        "code": target.code,
        "unit": target.unit,
        "product_id": target.product_id,
        "product_name": target.product_name or (target.product.name if target.product else None),
        "harvest_date": str(target.harvest_date),
        "initial_quantity": float(target.initial_quantity) if target.initial_quantity is not None else None,
        "remaining_quantity": float(target.remaining_quantity) if target.remaining_quantity is not None else None,
        "current_org_id": target.current_org_id,
        "current_org_name": target.current_org_name,
        "status": target.status,
    }

    while queue:
        curr_id, curr_level, path = queue.popleft()

        # Tìm các quan hệ mà curr_id là con (parent_batch -> curr_id)
        parent_relations = list(
            db.scalars(
                select(BatchRelation)
                .where(BatchRelation.child_batch_id == curr_id)
                .order_by(BatchRelation.parent_batch_id.asc())
            ).all()
        )

        next_level = curr_level + 1

        for rel in parent_relations:
            parent_id = rel.parent_batch_id

            # PHÁT HIỆN CHU TRÌNH (Cycle detection - T-49):
            # Nếu parent_id đã xuất hiện trên đường đi hiện tại -> chu trình!
            if parent_id in path:
                parent_batch = db.get(Batch, parent_id)
                code_str = parent_batch.code if parent_batch else str(parent_id)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Phát hiện chu trình phả hệ bất thường (Cycle detected) tại lô {code_str}",
                )

            all_ancestor_ids.add(parent_id)
            new_path = path + (parent_id,)

            # Nạp thông tin parent batch nếu chưa có
            parent_batch = db.get(Batch, parent_id)
            if parent_batch is None:
                continue

            plot_name = parent_batch.plot.name if parent_batch.plot else None
            farm_name = parent_batch.farm.name if parent_batch.farm else plot_name
            location = (
                parent_batch.plot.location if parent_batch.plot
                else (parent_batch.farm.location if parent_batch.farm else None)
            )
            owner = parent_batch.plot.owner if parent_batch.plot else (parent_batch.farm.owner if parent_batch.farm else None)
            prod_name = parent_batch.product_name or (parent_batch.product.name if parent_batch.product else None)

            node_dict = {
                "batch_id": parent_batch.id,
                "code": parent_batch.code,
                "unit": parent_batch.unit,
                "product_id": parent_batch.product_id,
                "product_name": prod_name,
                "plot_id": parent_batch.plot_id,
                "plot_name": plot_name,
                "farm_name": farm_name,
                "plot_area": float(parent_batch.plot.area) if parent_batch.plot else None,
                "location": location,
                "owner": owner,
                "current_org_id": parent_batch.current_org_id,
                "current_org_name": parent_batch.current_org_name,
                "initial_quantity": (
                    float(parent_batch.initial_quantity)
                    if parent_batch.initial_quantity is not None else None
                ),
                "remaining_quantity": (
                    float(parent_batch.remaining_quantity)
                    if parent_batch.remaining_quantity is not None else None
                ),
                "harvest_date": str(parent_batch.harvest_date),
                "relation_type": rel.relation_type,
                "transferred_quantity": float(rel.transferred_quantity),
                "level": next_level,
            }

            if next_level not in ancestors_by_level:
                ancestors_by_level[next_level] = []

            # Tránh lặp node trong cùng một tầng
            if not any(n["batch_id"] == parent_id for n in ancestors_by_level[next_level]):
                ancestors_by_level[next_level].append(node_dict)

            visited_nodes[parent_id] = node_dict

            # Tiếp tục duyệt lên cha của parent này
            queue.append((parent_id, next_level, new_path))

    # Tìm các root_batches: Các lô tổ tiên KHÔNG có cha nào khác trong hệ thống
    root_batches: list[dict[str, Any]] = []
    for anc_id in sorted(all_ancestor_ids):
        has_parents = db.scalar(
            select(BatchRelation.id)
            .where(BatchRelation.child_batch_id == anc_id)
            .limit(1)
        ) is not None

        if not has_parents:
            b = db.get(Batch, anc_id)
            if b:
                p_name = b.plot.name if b.plot else None
                f_name = b.farm.name if b.farm else p_name
                loc = b.plot.location if b.plot else (b.farm.location if b.farm else None)
                own = b.plot.owner if b.plot else (b.farm.owner if b.farm else None)
                root_batches.append({
                    "batch_id": b.id,
                    "code": b.code,
                    "unit": b.unit,
                    "product_name": b.product_name or (b.product.name if b.product else None),
                    "plot_id": b.plot_id,
                    "plot_name": p_name,
                    "farm_name": f_name,
                    "plot_area": float(b.plot.area) if b.plot else None,
                    "location": loc,
                    "owner": own,
                    "harvest_date": str(b.harvest_date),
                    "initial_quantity": float(b.initial_quantity) if b.initial_quantity is not None else None,
                })

    # Nếu chính target là lô gốc (không có cha)
    if not all_ancestor_ids:
        has_parents = db.scalar(
            select(BatchRelation.id)
            .where(BatchRelation.child_batch_id == target.id)
            .limit(1)
        ) is not None
        if not has_parents:
            p_name = target.plot.name if target.plot else None
            f_name = target.farm.name if target.farm else p_name
            loc = target.plot.location if target.plot else (target.farm.location if target.farm else None)
            own = target.plot.owner if target.plot else (target.farm.owner if target.farm else None)
            root_batches.append({
                "batch_id": target.id,
                "code": target.code,
                "unit": target.unit,
                "product_name": target.product_name or (target.product.name if target.product else None),
                "plot_id": target.plot_id,
                "plot_name": p_name,
                "farm_name": f_name,
                "plot_area": float(target.plot.area) if target.plot else None,
                "location": loc,
                "owner": own,
                "harvest_date": str(target.harvest_date),
                "initial_quantity": float(target.initial_quantity) if target.initial_quantity is not None else None,
            })

    result = {
        "target_batch": target_info,
        "ancestors_by_level": ancestors_by_level,
        "root_batches": root_batches,
        "total_ancestors": len(all_ancestor_ids),
    }

    # Lưu cache 60s
    if use_cache:
        _TRACE_CACHE[batch_id] = (now + CACHE_TTL_SECONDS, result)

    return result


def _detect_directed_cycle_3state(adj: dict[int, list[int]], root_id: int) -> int | None:
    """Thuật toán DFS 3 trạng thái (White-Gray-Black) phát hiện chu trình có hướng (Directed Cycle).

    Trạng thái:
      0: WHITE (chưa thăm)
      1: GRAY (đang trên đường đi khám phá hiện tại - in recursion stack)
      2: BLACK (đã thăm xong toàn bộ nhánh con mà không có chu trình)

    Nếu gặp một cạnh u -> v mà v đang ở trạng thái GRAY:
      v chính là tổ tiên trên đường đi hiện tại dẫn tới u.
      Do đó u -> v hoàn thành chu trình có hướng v ~> u -> v!
      Trả về v (ID của nút chu trình).
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[int, int] = {}

    # Explicit DFS frames preserve the gray/black semantics without Python's
    # recursion limit. A shared merge child is black, not a back edge.
    for start in (root_id, *adj):
        if color.get(start, WHITE) != WHITE:
            continue
        color[start] = GRAY
        stack = [(start, iter(adj.get(start, [])))]
        while stack:
            node, children = stack[-1]
            child = next(children, None)
            if child is None:
                color[node] = BLACK
                stack.pop()
                continue
            state = color.get(child, WHITE)
            if state == GRAY:
                return child
            if state == WHITE:
                color[child] = GRAY
                stack.append((child, iter(adj.get(child, []))))

    return None


def trace_forward(  # noqa: C901
    db: Session,
    batch_id: int,
    use_cache: bool = True,
    max_nodes: int = 1000,
) -> dict[str, Any]:
    """Truy xuôi phả hệ hậu duệ theo chiều cha -> con bằng thuật toán Level-by-Level Bulk BFS (S-26, S-27).

    Args:
        db: SQLAlchemy Session.
        batch_id: ID lô nông sản gốc cần truy xuất xuôi.
        use_cache: Có sử dụng cache 60s hay không (mặc định True).
        max_nodes: Giới hạn tối đa số nút hậu duệ tránh truy vấn quá tải.

    Returns:
        Dict chứa:
        - target_batch: thông tin lô gốc.
        - descendants_by_level: dict {level: [TraceForwardNode, ...]}.
        - terminal_batches: list các lô lá cuối cùng (chưa có con hoặc đã CONSUMED).
        - total_descendants: tổng số lô hậu duệ.

    Raises:
        HTTPException 404: nếu không tìm thấy lô.
        HTTPException 400: nếu phát hiện chu trình phả hệ bất thường (Cycle detected).
    """
    now = time.time()
    if use_cache and batch_id in _FORWARD_CACHE:
        expires_at, cached_data = _FORWARD_CACHE[batch_id]
        if now < expires_at:
            return cached_data

    target = db.scalars(
        select(Batch)
        .options(
            joinedload(Batch.plot),
            joinedload(Batch.farm),
            joinedload(Batch.product),
        )
        .where(Batch.id == batch_id)
    ).first()

    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy lô nông sản có id={batch_id}.",
        )

    # Pre-load thông tin target_batch (giữ tương thích 100% schema hiện tại)
    target_info = {
        "id": target.id,
        "code": target.code,
        "unit": target.unit,
        "product_id": target.product_id,
        "product_name": target.product_name or (target.product.name if target.product else None),
        "harvest_date": str(target.harvest_date),
        "initial_quantity": float(target.initial_quantity) if target.initial_quantity is not None else None,
        "remaining_quantity": float(target.remaining_quantity) if target.remaining_quantity is not None else None,
        "current_org_id": target.current_org_id,
        "current_org_name": target.current_org_name,
        "status": target.status,
        "is_truncated": False,
    }

    descendants_by_level: dict[int, list[dict[str, Any]]] = {}
    all_descendant_ids: set[int] = set()
    batch_cache: dict[int, Batch] = {target.id: target}
    is_truncated = False

    # Đồ thị kề phục vụ phát hiện chu trình có hướng chuẩn xác bằng DFS 3 trạng thái
    graph_adj: dict[int, list[int]] = {}

    current_level_parents: list[int] = [batch_id]
    curr_level = 0
    visited_expanded: set[int] = set()

    while current_level_parents and len(all_descendant_ids) < max_nodes:
        curr_level += 1

        for p_id in current_level_parents:
            visited_expanded.add(p_id)

        # 1. Gom 1 câu truy vấn lấy toàn bộ quan hệ con của tất cả cha trong tầng hiện tại
        relations = list(
            db.scalars(
                select(BatchRelation)
                .where(BatchRelation.parent_batch_id.in_(current_level_parents))
                .order_by(BatchRelation.child_batch_id.asc())
            ).all()
        )
        if not relations:
            break

        # 2. Xây dựng đồ thị kề & thu thập lô cần nạp chi tiết
        needed_batch_ids: list[int] = []
        for rel in relations:
            child_id = rel.child_batch_id
            parent_id = rel.parent_batch_id

            # Kiểm tra nhanh: tự trỏ hoặc trỏ lại trực tiếp vào root
            if child_id == parent_id or child_id == batch_id:
                child_batch = batch_cache.get(child_id) or db.get(Batch, child_id)
                code_str = child_batch.code if child_batch else str(child_id)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Phát hiện chu trình phả hệ bất thường (Cycle detected) tại lô {code_str}",
                )

            graph_adj.setdefault(parent_id, []).append(child_id)

            if child_id not in batch_cache and child_id not in needed_batch_ids:
                needed_batch_ids.append(child_id)

        # PHÁT HIỆN CHU TRÌNH CÓ HƯỚNG BẰNG DFS 3 TRẠNG THÁI (White-Gray-Black):
        # Đảm bảo 100% phát hiện mọi chu trình trong đồ thị nhiều cha, đa tầng và cạnh nối chéo
        cycle_node_id = _detect_directed_cycle_3state(graph_adj, batch_id)
        if cycle_node_id is not None:
            child_batch = batch_cache.get(cycle_node_id) or db.get(Batch, cycle_node_id)
            code_str = child_batch.code if child_batch else str(cycle_node_id)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Phát hiện chu trình phả hệ bất thường (Cycle detected) tại lô {code_str}",
            )

        # 3. Gom 1 câu truy vấn eager-loading (joinedload) cho tất cả lô con mới của tầng
        if needed_batch_ids:
            fetched_batches = list(
                db.scalars(
                    select(Batch)
                    .options(
                        joinedload(Batch.plot),
                        joinedload(Batch.farm),
                        joinedload(Batch.product),
                    )
                    .where(Batch.id.in_(needed_batch_ids))
                ).all()
            )
            for b in fetched_batches:
                batch_cache[b.id] = b

        # 4. Xây dựng node cho tầng và chuẩn bị ứng viên cho tầng kế tiếp
        next_level_nodes: list[dict[str, Any]] = []
        seen_in_this_level: set[int] = set()
        next_level_candidates: list[int] = []

        for rel in relations:
            child_id = rel.child_batch_id
            curr_id = rel.parent_batch_id

            # Giới hạn max_nodes: nếu đã chạm ngưỡng và chưa từng ghi nhận child_id
            if len(all_descendant_ids) >= max_nodes and child_id not in all_descendant_ids:
                is_truncated = True
                continue

            all_descendant_ids.add(child_id)

            child_batch = batch_cache.get(child_id)
            if child_batch is None:
                continue

            p_name = child_batch.plot.name if child_batch.plot else None
            f_name = child_batch.farm.name if child_batch.farm else p_name
            loc = (
                child_batch.plot.location
                if child_batch.plot
                else (child_batch.farm.location if child_batch.farm else None)
            )
            own = (
                child_batch.plot.owner
                if child_batch.plot
                else (child_batch.farm.owner if child_batch.farm else None)
            )
            prod_name = child_batch.product_name or (child_batch.product.name if child_batch.product else None)

            status_val = child_batch.status or "ACTIVE"
            is_consumed = (status_val == "CONSUMED")
            rem_qty = (
                0.0
                if is_consumed
                else (float(child_batch.remaining_quantity) if child_batch.remaining_quantity is not None else 0.0)
            )

            # Xử lý quan hệ hình thoi: trong cùng 1 tầng, mỗi child_id chỉ xuất hiện đúng 1 lần
            if child_id not in seen_in_this_level:
                seen_in_this_level.add(child_id)
                node_dict = {
                    "batch_id": child_batch.id,
                    "code": child_batch.code,
                    "parent_batch_id": curr_id,
                    "relation_type": rel.relation_type,
                    "transferred_quantity": float(rel.transferred_quantity),
                    "level": curr_level,
                    "current_org_id": child_batch.current_org_id,
                    "current_org_name": child_batch.current_org_name,
                    "location": loc,
                    "owner": own,
                    "plot_id": child_batch.plot_id,
                    "plot_name": p_name,
                    "farm_name": f_name,
                    "initial_quantity": (
                        float(child_batch.initial_quantity)
                        if child_batch.initial_quantity is not None
                        else None
                    ),
                    "remaining_quantity": rem_qty,
                    "status": status_val,
                    "is_consumed": is_consumed,
                    "harvest_date": str(child_batch.harvest_date),
                    "product_id": child_batch.product_id,
                    "product_name": prod_name,
                    "unit": child_batch.unit,
                    "is_masked": False,
                }
                next_level_nodes.append(node_dict)

                # Chỉ tiếp tục mở rộng con nếu lô chưa bị tiêu thụ (CONSUMED) và chưa từng được mở rộng
                if not is_consumed and child_id not in visited_expanded:
                    next_level_candidates.append(child_id)

        if next_level_nodes:
            descendants_by_level[curr_level] = next_level_nodes

        unexplored_next = [
            cid for cid in dict.fromkeys(next_level_candidates) if cid not in visited_expanded
        ]

        # Kiểm tra xem có thực sự bị cắt ngang khi dừng ở max_nodes hay không
        if len(all_descendant_ids) >= max_nodes and unexplored_next:
            has_more = db.scalar(
                select(BatchRelation.id)
                .where(BatchRelation.parent_batch_id.in_(unexplored_next))
                .limit(1)
            ) is not None
            if has_more:
                is_truncated = True
            current_level_parents = []
            break

        current_level_parents = unexplored_next

    target_info["is_truncated"] = is_truncated
    target_info["max_nodes_reached"] = (len(all_descendant_ids) >= max_nodes)

    # 5. Xác định terminal_batches: Lô lá cuối chuỗi hoặc đã CONSUMED
    terminal_batches: list[dict[str, Any]] = []
    if not all_descendant_ids:
        has_children = db.scalar(
            select(BatchRelation.id)
            .where(BatchRelation.parent_batch_id == target.id)
            .limit(1)
        ) is not None
        if not has_children:
            loc = target.plot.location if target.plot else (target.farm.location if target.farm else None)
            is_c = (target.status == "CONSUMED")
            terminal_batches.append({
                "batch_id": target.id,
                "code": target.code,
                "unit": target.unit,
                "product_name": target.product_name or (target.product.name if target.product else None),
                "current_org_id": target.current_org_id,
                "current_org_name": target.current_org_name,
                "location": loc,
                "initial_quantity": float(target.initial_quantity) if target.initial_quantity is not None else None,
                "remaining_quantity": (
                    0.0
                    if is_c
                    else (float(target.remaining_quantity) if target.remaining_quantity is not None else 0.0)
                ),
                "status": target.status,
                "is_consumed": is_c,
                "harvest_date": str(target.harvest_date),
            })
    else:
        # Gom 1 câu truy vấn xác định tất cả parent_batch_id có con trong tập all_descendant_ids
        parents_with_children = set(
            db.scalars(
                select(BatchRelation.parent_batch_id)
                .where(BatchRelation.parent_batch_id.in_(all_descendant_ids))
                .distinct()
            ).all()
        )

        missing_ids = [d_id for d_id in all_descendant_ids if d_id not in batch_cache]
        if missing_ids:
            missing_batches = list(
                db.scalars(
                    select(Batch)
                    .options(
                        joinedload(Batch.plot),
                        joinedload(Batch.farm),
                        joinedload(Batch.product),
                    )
                    .where(Batch.id.in_(missing_ids))
                ).all()
            )
            for mb in missing_batches:
                batch_cache[mb.id] = mb

        for desc_id in sorted(all_descendant_ids):
            b = batch_cache.get(desc_id)
            if not b:
                continue
            has_children = (desc_id in parents_with_children)
            is_c = (b.status == "CONSUMED")
            if not has_children or is_c:
                loc = b.plot.location if b.plot else (b.farm.location if b.farm else None)
                terminal_batches.append({
                    "batch_id": b.id,
                    "code": b.code,
                    "unit": b.unit,
                    "product_name": b.product_name or (b.product.name if b.product else None),
                    "current_org_id": b.current_org_id,
                    "current_org_name": b.current_org_name,
                    "location": loc,
                    "initial_quantity": float(b.initial_quantity) if b.initial_quantity is not None else None,
                    "remaining_quantity": (
                        0.0
                        if is_c
                        else (float(b.remaining_quantity) if b.remaining_quantity is not None else 0.0)
                    ),
                    "status": b.status,
                    "is_consumed": is_c,
                    "harvest_date": str(b.harvest_date),
                })

    # Fetch real relations only between represented nodes; never add ancestors
    # outside the forward result to complete a merge.
    represented_ids = {batch_id, *all_descendant_ids}
    edges = [
        {"parent_batch_id": rel.parent_batch_id,
         "child_batch_id": rel.child_batch_id,
         "relation_type": rel.relation_type,
         "transferred_quantity": float(rel.transferred_quantity)}
        for rel in db.scalars(
            select(BatchRelation)
            .where(BatchRelation.parent_batch_id.in_(represented_ids),
                   BatchRelation.child_batch_id.in_(represented_ids))
            .order_by(BatchRelation.parent_batch_id, BatchRelation.child_batch_id)
        ).all()
    ]

    result = {
        "edges": edges,
        "target_batch": target_info,
        "descendants_by_level": descendants_by_level,
        "terminal_batches": terminal_batches,
        "total_descendants": len(all_descendant_ids),
    }

    from app.services.locations import attach_forward_locations
    attach_forward_locations(db, result)

    if use_cache:
        _FORWARD_CACHE[batch_id] = (now + CACHE_TTL_SECONDS, result)

    return result
