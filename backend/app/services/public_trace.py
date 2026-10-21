"""Dịch vụ chuẩn hóa và làm sạch dữ liệu truy xuất công khai theo Story S-48.

Cung cấp logic nghiệp vụ:
- Thu thập dữ liệu truy xuất nguồn gốc của lô.
- Áp dụng nguyên tắc whitelist và bảo mật S-48:
  + Loại bỏ 100% khối lượng và giá cả.
  + Loại bỏ 100% ID nội bộ database.
  + Ẩn tên đối tác riêng lẻ, chỉ giữ loại hình đơn vị (HTX, vận chuyển, phân phối...).
  + Giữ nguyên thông tin vùng trồng/thửa đất phục vụ người tiêu dùng.
"""

from typing import Any
from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.models import Batch, BatchEvent
from app.schemas_public import (
    PublicBatchTraceResponse,
    PublicMilestoneInfo,
    PublicOriginInfo,
    PublicRootBatchInfo,
    get_public_organization_type,
)
from app.services.traceability import trace_backwards
from app.services.recall import ensure_not_recalled


def _format_public_status(raw_status: str | None) -> str:
    """Định dạng trạng thái lô thành chuỗi thân thiện với người tiêu dùng."""
    if not raw_status:
        return "Đang lưu kho"
    st = raw_status.strip().upper()
    if st == "ACTIVE":
        return "Đang lưu kho"
    if st == "CONSUMED":
        return "Đã tiêu thụ"
    if st in ("IN_TRANSIT", "SHIPPING"):
        return "Đang vận chuyển"
    if st in ("RECALLED", "RECALL"):
        return "Đang thu hồi"
    return raw_status


def _resolve_milestone_stage_and_org(evt: BatchEvent) -> tuple[str, str]:
    """Xác định công đoạn và loại tổ chức chung (không lộ tên riêng đối tác theo S-48)."""
    evt_type = evt.event_type.upper() if evt.event_type else ""
    if evt_type in ("HARVEST", "BATCH_CREATED"):
        return "Thu hoạch tại vùng trồng", "Hợp tác xã nông nghiệp"
    if evt_type in ("SPLIT", "MERGE"):
        org_name = evt.organization.name if evt.organization else None
        role = evt.user.role if evt.user else None
        return "Sơ chế & Phân loại", get_public_organization_type(org_name, role)
    if evt_type in ("TRIP_DISPATCH", "TRIP_DELIVER"):
        return "Vận chuyển chuỗi lạnh", "Đơn vị vận chuyển"
    if evt_type in ("HANDOVER_ACCEPT", "HANDOVER_INIT", "HANDOVER_REJECT"):
        to_name = evt.to_org.name if evt.to_org else None
        return "Bàn giao chuỗi cung ứng", get_public_organization_type(to_name)
    if evt_type == "CONSUMED":
        return "Phân phối đến người tiêu dùng", "Điểm bán lẻ"
    if evt_type == "TEMPERATURE_VIOLATION":
        return "Cảnh báo vi phạm nhiệt độ", "Đơn vị vận chuyển / bảo quản"
    if evt_type == "RECALL_INIT":
        return "Khởi tạo lệnh thu hồi (lô gốc)", "Đơn vị quản lý chuỗi cung ứng"
    if evt_type == "RECALL_AFFECTED":
        return "Áp dụng thu hồi lan truyền (lô thành phẩm phái sinh)", "Đơn vị quản lý chuỗi cung ứng"
    if evt_type == "RECALL_ACKNOWLEDGED":
        return "Xác nhận cách ly sản phẩm", "Đơn vị quản lý chuỗi cung ứng"
    if evt_type == "RECALL_COMPLETED":
        return "Hoàn tất xử lý thu hồi", "Đơn vị quản lý chuỗi cung ứng"
    if evt_type.startswith("RECALL_"):
        return "Thu hồi / cách ly sản phẩm", "Đơn vị quản lý chuỗi cung ứng"

    org_name = evt.organization.name if evt.organization else (evt.from_org.name if evt.from_org else None)
    return "Ghi nhận mốc sự kiện", get_public_organization_type(org_name)


def _build_public_milestones(batch: Batch, db: Session, ancestor_ids=()) -> list[PublicMilestoneInfo]:
    """Tổng hợp các mốc công đoạn chuỗi cung ứng công khai theo chuẩn S-48."""
    events = (
        db.query(BatchEvent)
        .options(
            joinedload(BatchEvent.from_org),
            joinedload(BatchEvent.to_org),
            joinedload(BatchEvent.organization),
            joinedload(BatchEvent.user),
        )
        .filter(BatchEvent.batch_id.in_({batch.id, *ancestor_ids}))
        .order_by(BatchEvent.timestamp.asc(), BatchEvent.id.asc())
        .all()
    )

    milestones: list[PublicMilestoneInfo] = []
    step = 1

    for evt in events:
        evt_type = evt.event_type.upper() if evt.event_type else ""
        stage, org_type = _resolve_milestone_stage_and_org(evt)

        # Thời gian
        ts = None
        if hasattr(evt, "timestamp") and evt.timestamp:
            ts = evt.timestamp.isoformat()
        elif hasattr(evt, "created_at") and evt.created_at:
            ts = evt.created_at.isoformat()

        milestones.append(
            PublicMilestoneInfo(
                step=step,
                stage=stage,
                organization_type=org_type,
                timestamp=ts,
                status=("Chờ xác nhận" if evt_type == "HANDOVER_INIT" else
                        "Đã từ chối" if evt_type == "HANDOVER_REJECT" else
                        "Đang vận chuyển" if evt_type == "TRIP_DISPATCH" else "Đã ghi nhận"),
            )
        )
        step += 1

    # Nếu chưa có event nào trong DB, tạo mốc khởi nguyên từ thông tin thu hoạch
    if not milestones:
        milestones.append(
            PublicMilestoneInfo(
                step=1,
                stage="Thu hoạch tại vùng trồng",
                organization_type="Hợp tác xã nông nghiệp",
                timestamp=str(batch.harvest_date) if batch.harvest_date else None,
                status="Đã hoàn thành",
            )
        )

    return milestones


def get_public_batch_trace(batch_code: str, db: Session) -> dict[str, Any]:
    """Lấy dữ liệu truy xuất công khai đã được làm sạch và xác thực theo Story S-48.

    Args:
        batch_code: Mã lô nông sản cần tra cứu.
        db: SQLAlchemy Session.

    Returns:
        dict: Dữ liệu công khai tuân thủ tuyệt đối Pydantic schema PublicBatchTraceResponse.

    Raises:
        HTTPException 404: Nếu mã lô không tồn tại.
    """
    clean_code = batch_code.strip()
    batch = (
        db.query(Batch)
        .options(
            joinedload(Batch.product),
            joinedload(Batch.plot),
            joinedload(Batch.farm),
        )
        .filter(Batch.code == clean_code)
        .first()
    )

    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy lô nông sản có mã '{clean_code}'.",
        )

    # 1. Thông tin vùng trồng gốc (Được phép hiển thị theo quy định "trừ vùng trồng" của S-48)
    plot = batch.plot
    farm = batch.farm
    origin_info = PublicOriginInfo(
        farm_name=(farm.name if farm else None) or (plot.name if plot else None),
        plot_name=plot.name if plot else None,
        location=(plot.location if plot else None) or (farm.location if farm else None),
    )

    # 2. Truy ngược phả hệ để lấy danh sách các lô thu hoạch gốc (cho lô gộp nhiều nguồn)
    lineage = trace_backwards(db, batch.id)
    raw_roots = lineage.get("root_batches", [])

    roots: list[PublicRootBatchInfo] = []
    seen_root_codes: set[str] = set()

    for r in raw_roots:
        r_code = r.get("code") or r.get("batch_code")
        if not r_code or r_code in seen_root_codes:
            continue
        seen_root_codes.add(r_code)
        roots.append(
            PublicRootBatchInfo(
                batch_code=r_code,
                product_name=r.get("product_name") or "Nông sản",
                harvest_date=r.get("harvest_date"),
                farm_name=r.get("farm_name") or r.get("plot_name"),
                plot_name=r.get("plot_name"),
                location=r.get("location"),
            )
        )

    # Nếu không có tổ tiên trong lineage thì chính lô hiện tại là lô gốc
    if not roots:
        roots.append(
            PublicRootBatchInfo(
                batch_code=batch.code,
                product_name=batch.product_name or (batch.product.name if batch.product else "Nông sản"),
                harvest_date=str(batch.harvest_date) if batch.harvest_date else None,
                farm_name=origin_info.farm_name,
                plot_name=origin_info.plot_name,
                location=origin_info.location,
            )
        )

    # 3. Hành trình các mốc chuỗi cung ứng (đã ẩn tên riêng đối tác)
    ancestor_ids = [node["batch_id"] for level in lineage.get("ancestors_by_level", {}).values() for node in level]
    milestones = _build_public_milestones(batch, db, ancestor_ids)
    recall_warning = (batch.status or "").upper() in {"RECALLED", "QUARANTINED", "RECALL"}
    try:
        ensure_not_recalled(db, batch.id)
    except HTTPException as exc:
        if exc.status_code != 409:
            raise
        recall_warning = True

    # 4. Đóng gói và xác thực qua PublicBatchTraceResponse (chặn mọi trường nội bộ)
    prod_name = batch.product_name or (batch.product.name if batch.product else "Nông sản")
    pub_response = PublicBatchTraceResponse(
        batch_code=batch.code,
        product_name=prod_name,
        harvest_date=str(batch.harvest_date) if batch.harvest_date else None,
        status="Thu hồi / cách ly — Không sử dụng" if recall_warning else _format_public_status(batch.status),
        recall_warning=recall_warning,
        recall_message="CẢNH BÁO: Lô hàng bị thu hồi hoặc cách ly. Không sử dụng sản phẩm." if recall_warning
        else "Không ghi nhận cảnh báo thu hồi",
        origin=origin_info,
        root_batches=roots,
        milestones=milestones,
    )

    return pub_response.model_dump()
