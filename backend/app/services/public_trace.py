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


def _build_public_milestones(batch: Batch, db: Session) -> list[PublicMilestoneInfo]:
    """Tổng hợp các mốc công đoạn chuỗi cung ứng công khai theo chuẩn S-48."""
    events = (
        db.query(BatchEvent)
        .options(
            joinedload(BatchEvent.from_org),
            joinedload(BatchEvent.to_org),
            joinedload(BatchEvent.organization),
        )
        .filter(BatchEvent.batch_id == batch.id)
        .order_by(BatchEvent.id.asc())
        .all()
    )

    milestones: list[PublicMilestoneInfo] = []
    step = 1

    for evt in events:
        evt_type = evt.event_type.upper() if evt.event_type else ""

        # Xác định công đoạn và loại tổ chức chung (không lộ tên riêng đối tác)
        if evt_type in ("HARVEST", "BATCH_CREATED"):
            stage = "Thu hoạch tại vùng trồng"
            org_type = "Hợp tác xã nông nghiệp"
        elif evt_type in ("SPLIT", "MERGE"):
            stage = "Sơ chế & Phân loại"
            org_type = "Cơ sở sơ chế / chế biến"
        elif evt_type in ("TRIP_DISPATCH", "TRIP_DELIVER"):
            stage = "Vận chuyển chuỗi lạnh"
            org_type = "Đơn vị vận chuyển"
        elif evt_type in ("HANDOVER_ACCEPT", "HANDOVER_INIT"):
            stage = "Bàn giao chuỗi cung ứng"
            org_type = "Nhà phân phối"
        elif evt_type == "CONSUMED":
            stage = "Phân phối đến người tiêu dùng"
            org_type = "Điểm bán lẻ"
        else:
            org_name = None
            if evt.organization:
                org_name = evt.organization.name
            elif evt.from_org:
                org_name = evt.from_org.name
            stage = "Ghi nhận mốc sự kiện"
            org_type = get_public_organization_type(org_name)

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
                status="Đã hoàn thành",
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
    milestones = _build_public_milestones(batch, db)

    # 4. Đóng gói và xác thực qua PublicBatchTraceResponse (chặn mọi trường nội bộ)
    prod_name = batch.product_name or (batch.product.name if batch.product else "Nông sản")
    pub_response = PublicBatchTraceResponse(
        batch_code=batch.code,
        product_name=prod_name,
        harvest_date=str(batch.harvest_date) if batch.harvest_date else None,
        status=_format_public_status(batch.status),
        origin=origin_info,
        root_batches=roots,
        milestones=milestones,
    )

    return pub_response.model_dump()
