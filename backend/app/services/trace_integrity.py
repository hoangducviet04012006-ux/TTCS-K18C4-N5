"""Dịch vụ Kiểm tra Tính Toàn vẹn Dữ liệu Truy xuất Nguồn gốc (Story S-50).

Module này mở rộng cơ chế băm mật mã SHA-256 từ cấp độ một lô đơn lẻ (T-28)
lên toàn bộ chuỗi phả hệ hành trình truy xuất nguồn gốc (End-to-End Traceability Integrity):
- Thẩm định tính toàn vẹn toán học của toàn bộ các lô tổ tiên từ thửa ruộng/nông hộ gốc.
- Phát hiện các can thiệp sửa trực tiếp SQL (HASH_MISMATCH) hoặc đứt gãy liên kết (CHAIN_BROKEN).
- Tạo con dấu xác thực mật mã (Cryptographic Verification Seal) niêm phong kết quả.
- Hỗ trợ bộ nhớ đệm cache 60s và cơ chế chống quét dò mã lô.
"""

from collections import deque
from datetime import datetime, timezone
import hashlib
import time
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.hash_chain import GENESIS_HASH, verify_batch_chain
from app.models import Batch, BatchEvent, BatchRelation

# Bộ nhớ đệm in-memory (60s TTL)
_TRACE_INTEGRITY_CACHE: dict[int, tuple[float, dict[str, Any]]] = {}
CACHE_TTL_SECONDS: int = 60


def clear_trace_integrity_cache(batch_id: int | None = None) -> None:
    """Xóa bộ đệm kết quả xác thực toàn vẹn."""
    if batch_id is not None:
        _TRACE_INTEGRITY_CACHE.pop(batch_id, None)
    else:
        _TRACE_INTEGRITY_CACHE.clear()


def verify_traceability_integrity(  # noqa: C901
    db: Session,
    batch_id: int | None = None,
    batch_code: str | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Kiểm tra toàn diện tính toàn vẹn của chuỗi dữ liệu truy xuất nguồn gốc (Story S-50).

    Args:
        db: SQLAlchemy Session.
        batch_id: ID lô nông sản cần kiểm tra.
        batch_code: Mã lô nông sản cần kiểm tra (ưu tiên nếu truyền).
        use_cache: Sử dụng bộ nhớ đệm 60s (mặc định True).

    Returns:
        dict: Kết quả thẩm định toàn diện bao gồm:
            - is_valid: True nếu 100% mắt xích trong chuỗi phả hệ đều toàn vẹn.
            - valid: Alias tương thích ngược.
            - status: 'VERIFIED' | 'TAMPERED' | 'CHAIN_BROKEN' | 'NO_EVENTS'.
            - total_batches_checked: Tổng số lô đã thẩm định.
            - total_events_checked: Tổng số sự kiện đã duyệt qua.
            - verification_seal: Chuỗi băm SHA-256 niêm phong kết quả.
            - verified_at: Thời điểm thẩm định ISO 8601 UTC.
            - nodes: Danh sách chi tiết từng lô trong phả hệ.
            - tampered_node: Chi tiết vị trí vi phạm (nếu có).

    Raises:
        HTTPException 404: Nếu không tìm thấy lô nông sản.
        HTTPException 400: Nếu phát hiện chu trình phả hệ bất thường.
    """
    now_ts = time.time()

    # 1. Xác định lô nông sản đích
    if batch_code:
        target = db.scalar(
            select(Batch)
            .options(joinedload(Batch.product), joinedload(Batch.current_org))
            .where(Batch.code == batch_code.strip())
        )
    elif batch_id:
        target = db.scalar(
            select(Batch)
            .options(joinedload(Batch.product), joinedload(Batch.current_org))
            .where(Batch.id == batch_id)
        )
    else:
        raise ValueError("Cần cung cấp ít nhất batch_id hoặc batch_code.")

    if target is None:
        identifier = batch_code or str(batch_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy lô nông sản '{identifier}' trong hệ thống.",
        )

    # 2. Kiểm tra Cache 60s
    if use_cache and target.id in _TRACE_INTEGRITY_CACHE:
        expires_at, cached_res = _TRACE_INTEGRITY_CACHE[target.id]
        if now_ts < expires_at:
            return cached_res

    # 3. Thuật toán BFS lặp duyệt ngược phả hệ (ancestors)
    queue: deque[tuple[int, int, tuple[int, ...]]] = deque()
    queue.append((target.id, 0, (target.id,)))

    visited_ids: set[int] = {target.id}
    ordered_batch_ids: list[int] = [target.id]
    levels_map: dict[int, int] = {target.id: 0}

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

        for rel in parent_relations:
            p_id = rel.parent_batch_id

            # Phát hiện chu trình phả hệ bất thường
            if p_id in path:
                p_batch = db.get(Batch, p_id)
                code_str = p_batch.code if p_batch else str(p_id)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Phát hiện chu trình phả hệ bất thường liên quan đến lô '{code_str}'.",
                )

            if p_id not in visited_ids:
                visited_ids.add(p_id)
                ordered_batch_ids.append(p_id)
                levels_map[p_id] = curr_level + 1
                queue.append((p_id, curr_level + 1, path + (p_id,)))

    # 4. Thẩm định tính toàn vẹn của từng lô trong phả hệ
    nodes_integrity: list[dict[str, Any]] = []
    total_events_checked = 0
    overall_valid = True
    overall_status = "VERIFIED"
    tampered_node_info: dict[str, Any] | None = None
    root_hashes: list[str] = []
    target_latest_hash: str | None = None

    for b_id in ordered_batch_ids:
        b = db.scalar(
            select(Batch)
            .options(joinedload(Batch.product), joinedload(Batch.current_org))
            .where(Batch.id == b_id)
        )
        if not b:
            continue

        # Thẩm định chuỗi băm của lô
        single_verify = verify_batch_chain(db, b_id)
        is_node_valid = single_verify.get("is_valid", False)
        node_events_count = single_verify.get("total_events", 0)
        total_events_checked += node_events_count

        # Lấy sự kiện đầu và cuối để trích xuất hash
        last_evt = db.scalar(
            select(BatchEvent)
            .where(BatchEvent.batch_id == b_id)
            .order_by(BatchEvent.id.desc())
            .limit(1)
        )
        first_evt = db.scalar(
            select(BatchEvent)
            .where(BatchEvent.batch_id == b_id)
            .order_by(BatchEvent.id.asc())
            .limit(1)
        )

        node_latest_hash = last_evt.current_hash if last_evt else None
        node_genesis_hash = first_evt.prev_hash if first_evt else GENESIS_HASH

        if b_id == target.id:
            target_latest_hash = node_latest_hash

        # Xác định trạng thái của node
        if not is_node_valid:
            overall_valid = False
            node_err = single_verify.get("error_type", "TAMPERED")
            node_status = node_err
            if overall_status == "VERIFIED":
                overall_status = node_err
            if tampered_node_info is None:
                tampered_node_info = {
                    "batch_id": b.id,
                    "batch_code": b.code,
                    "level": levels_map.get(b.id, 0),
                    "error_type": node_err,
                    "tampered_event_id": single_verify.get("tampered_event_id"),
                    "message": single_verify.get("message"),
                }
        else:
            node_status = "VERIFIED" if node_events_count > 0 else "NO_EVENTS"

        # Nếu là lô gốc (không có cha trong phả hệ)
        has_parent = db.scalar(
            select(BatchRelation.id).where(BatchRelation.child_batch_id == b.id).limit(1)
        ) is not None
        if not has_parent and node_latest_hash:
            root_hashes.append(node_latest_hash)

        prod_name = b.product_name or (b.product.name if b.product else None)
        org_name = b.current_org_name or (b.current_org.name if b.current_org else None)

        nodes_integrity.append({
            "batch_id": b.id,
            "code": b.code,
            "level": levels_map.get(b.id, 0),
            "product_name": prod_name,
            "current_org_id": b.current_org_id,
            "current_org_name": org_name,
            "total_events": node_events_count,
            "is_valid": is_node_valid,
            "status": node_status,
            "latest_hash": node_latest_hash,
            "genesis_hash": node_genesis_hash,
            "error_type": single_verify.get("error_type") if not is_node_valid else None,
            "tampered_event_id": single_verify.get("tampered_event_id") if not is_node_valid else None,
            "message": single_verify.get("message"),
        })

    # 5. Nếu không có sự kiện nào trong toàn bộ chuỗi
    if total_events_checked == 0 and overall_valid:
        overall_status = "NO_EVENTS"

    # 6. Tạo con dấu xác thực mật mã (Cryptographic Seal)
    verified_time_str = datetime.now(timezone.utc).isoformat()
    seal_payload = (
        f"{target.code}:{target.id}:{target_latest_hash or 'NONE'}:"
        f"{total_events_checked}:{overall_valid}:{len(ordered_batch_ids)}"
    )
    verification_seal = hashlib.sha256(seal_payload.encode("utf-8")).hexdigest()

    if overall_valid:
        if total_events_checked > 0:
            user_msg = (
                f"Dữ liệu truy xuất nguồn gốc của lô '{target.code}' đã được xác thực toàn vẹn 100%. "
                f"Đã kiểm tra {len(ordered_batch_ids)} lô phả hệ và {total_events_checked} sự kiện mật mã SHA-256."
            )
        else:
            user_msg = f"Lô '{target.code}' hợp lệ nhưng chưa có sự kiện nào được ghi nhận trong hệ thống."
    else:
        err_msg = tampered_node_info.get("message") if tampered_node_info else "Phát hiện sai lệch chuỗi băm."
        user_msg = (
            f"CẢNH BÁO VI PHẠM TOÀN VẸN: Dữ liệu truy xuất nguồn gốc của lô '{target.code}' "
            f"đã bị can thiệp trái phép tại lô '{tampered_node_info.get('batch_code') if tampered_node_info else 'N/A'}'. "
            f"{err_msg}"
        )

    result = {
        "is_valid": overall_valid,
        "valid": overall_valid,
        "batch_id": target.id,
        "batch_code": target.code,
        "status": overall_status,
        "total_batches_checked": len(ordered_batch_ids),
        "total_events_checked": total_events_checked,
        "root_hashes": root_hashes,
        "latest_hash": target_latest_hash,
        "verification_seal": verification_seal,
        "verified_at": verified_time_str,
        "message": user_msg,
        "nodes": nodes_integrity,
        "tampered_node": tampered_node_info,
    }

    # 7. Lưu Cache 60s nếu dữ liệu hợp lệ
    if use_cache and overall_valid:
        _TRACE_INTEGRITY_CACHE[target.id] = (now_ts + CACHE_TTL_SECONDS, result)

    return result
