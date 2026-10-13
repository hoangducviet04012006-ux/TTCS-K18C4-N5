"""Router quản lý lô nông sản (Batch - T-18, T-19, T-21, T-25, T-33).

- POST /batches: Thu hoạch / tạo lô mới, sinh mã ngẫu nhiên 8 ký tự an toàn,
  kiểm tra ràng buộc nghiệp vụ (ngày tương lai, khối lượng âm, thửa đất tổ chức khác),
  ghi sự kiện HARVEST vào hash-chain trong cùng transaction (atomic).
- GET /batches: Lấy danh sách lô phân trang 20 lô/trang, sắp xếp theo ngày thu hoạch
  mới nhất trước, hỗ trợ tìm kiếm theo mã lô (case-insensitive) và lọc theo product_id,
  cô lập dữ liệu theo current_org_id của người dùng.
- GET /batches/{batch_id}: Chi tiết lô nông sản.
- PUT /batches/{batch_id}: Cập nhật thông tin lô.
- DELETE /batches/{batch_id}: Xóa lô (chỉ admin).
"""

from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session, joinedload

from app.audit import record_action
from app.database import get_db
from app.hash_chain import record_event
from app.models import (
    ACTION_CREATE,
    ACTION_DELETE,
    ACTION_UPDATE,
    ENTITY_BATCH,
    EVENT_EXPORT_MERGE,
    EVENT_GENESIS_SPLIT,
    EVENT_HARVEST,
    EVENT_MERGE,
    EVENT_SPLIT,
    RELATION_MERGE,
    RELATION_SPLIT,
    Batch,
    BatchRelation,
    Farm,
    Plot,
    Product,
    ROLE_INSPECTOR,
    User,
)
from app.schemas import (
    BatchConsumeRequest,
    BatchConsumeResponse,
    BatchCreate,
    BatchMergeRequest,
    BatchMergeResponse,
    BatchResponse,
    BatchSplitRequest,
    BatchSplitResponse,
    BatchSummaryResponse,
    BatchUpdate,
    DeleteResponse,
    TraceBackResponse,
    TraceForwardResponse,
)
from app.security import (
    get_current_user,
    require_admin,
    require_farmer,
)
from app.services.overdue_job import check_overdue_handovers
from app.services.permissions import can_view_batch
from app.services.recall import ensure_not_recalled
from app.services.recall_database import prepare_physical_write
from app.services.rbac import check_action_permission
from app.services.traceability import clear_trace_cache, trace_backwards, trace_forward
from app.utils.batch_code import generate_batch_code

router = APIRouter(
    prefix="/batches",
    tags=["Batches"],
)


@router.post(
    "",
    response_model=BatchResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Thu hoạch / Tạo lô nông sản mới (T-18, T-21, T-25)",
    description=(
        "Tạo một lô thu hoạch nông sản mới gắn với thửa đất và sản phẩm.\n\n"
        "Kiểm tra nghiệp vụ (Server-side validation T-21):\n"
        "- Chặn nếu `harvest_date` ở tương lai so với ngày hiện tại (HTTP 400).\n"
        "- Chặn nếu `initial_quantity` <= 0 (HTTP 400).\n"
        "- Chặn nếu thửa đất thuộc tổ chức khác (HTTP 403 Forbidden).\n"
        "- Tự động sinh mã lô 8 ký tự an toàn (T-19) không chứa 0, O, 1, I, L.\n"
        "- Tự động ghi sự kiện HARVEST vào hash-chain trong cùng transaction (T-25)."
    ),
    responses={
        status.HTTP_400_BAD_REQUEST: {"description": "Dữ liệu không hợp lệ (ngày tương lai, số lượng âm)."},
        status.HTTP_401_UNAUTHORIZED: {"description": "Chưa đăng nhập."},
        status.HTTP_403_FORBIDDEN: {"description": "Thửa đất thuộc tổ chức khác."},
        status.HTTP_404_NOT_FOUND: {"description": "Không tìm thấy thửa đất hoặc sản phẩm."},
    },
)
def create_batch(  # noqa: C901
    payload: BatchCreate,
    current_user: User = Depends(require_farmer),
    db: Session = Depends(get_db),
) -> Batch:
    """Tạo lô nông sản thu hoạch mới với kiểm tra toàn diện."""
    check_action_permission(current_user, "HARVEST")
    errors: dict[str, str] = {}

    # 1. Kiểm tra ngày thu hoạch không ở tương lai (T-21)
    today = date.today()
    if payload.harvest_date > today:
        errors["harvest_date"] = "Ngày thu hoạch không thể ở tương lai so với ngày hiện tại."

    # 2. Kiểm tra khối lượng thu hoạch > 0 (T-21)
    raw_qty = payload.initial_quantity if payload.initial_quantity is not None else payload.quantity
    if raw_qty is None or float(raw_qty) <= 0:
        errors["initial_quantity"] = "Khối lượng thu hoạch ban đầu phải lớn hơn 0."

    if errors:
        first_msg = next(iter(errors.values()))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": first_msg, "errors": errors},
        )

    # 3. Xác định và kiểm tra thửa đất (plot_id hoặc farm_id)
    target_plot_id = payload.plot_id or payload.farm_id
    if not target_plot_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vui lòng cung cấp mã thửa đất thu hoạch (plot_id).",
        )

    plot = db.get(Plot, target_plot_id)
    farm = db.get(Farm, target_plot_id)
    if plot is None and farm is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy thửa đất có id={target_plot_id}.",
        )

    plot_org_id = plot.organization_id if plot else farm.organization_id  # type: ignore

    # 4. Kiểm tra phân quyền cách ly tổ chức (T-21) -> HTTP 403 Forbidden
    if current_user.organization_id is None or plot_org_id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền tạo lô nông sản cho thửa đất của tổ chức khác.",
        )

    # 5. Đảm bảo bản ghi plot tồn tại trong bảng plots (đồng bộ từ farm nếu cần)
    if plot is None and farm is not None:
        plot = Plot(
            id=farm.id,
            organization_id=farm.organization_id,
            name=farm.name,
            location=farm.location,
            area=farm.area,
            coordinates=farm.coordinates,
            owner=farm.owner,
        )
        db.add(plot)
        db.flush()

    # 6. Xác định sản phẩm (product_id hoặc product_name)
    product: Product | None = None
    if payload.product_id:
        product = db.get(Product, payload.product_id)
        if product is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Không tìm thấy sản phẩm có id={payload.product_id}.",
            )
    elif payload.product_name:
        product = db.scalar(select(Product).where(Product.name == payload.product_name.strip()))
        if product is None:
            # Tạo tự động nếu sản phẩm chưa có (cho các test cũ)
            product = Product(name=payload.product_name.strip(), unit="kg")
            db.add(product)
            db.flush()
    else:
        # Mặc định lấy sản phẩm đầu tiên hoặc tạo mới
        product = db.scalar(select(Product).order_by(Product.id.asc()))
        if product is None:
            product = Product(name="Nông sản thu hoạch", unit="kg")
            db.add(product)
            db.flush()

    qty_decimal = Decimal(str(raw_qty))

    # 7. Tạo lô với cơ chế retry mã lô nếu trùng lặp (T-19, T-25)
    max_retries = 5
    batch: Batch | None = None
    for attempt in range(max_retries):
        code = generate_batch_code()
        # Kiểm tra trước để giảm tỷ lệ đụng constraint
        if db.scalar(select(Batch.id).where(Batch.code == code)) is not None:
            continue

        try:
            batch = Batch(
                code=code,
                plot_id=target_plot_id,
                farm_id=target_plot_id,
                product_id=product.id,
                product_name=product.name,
                harvest_date=payload.harvest_date,
                initial_quantity=qty_decimal,
                remaining_quantity=qty_decimal,
                quantity=float(qty_decimal),
                current_org_id=plot_org_id,
                status="ACTIVE",
            )
            db.add(batch)
            db.flush()

            # Ghi sự kiện HARVEST vào hash-chain trong cùng transaction (T-25)
            harvest_payload = {
                "batch_code": batch.code,
                "plot_id": batch.plot_id,
                "product_id": batch.product_id,
                "product_name": product.name,
                "unit": product.unit,
                "initial_quantity": float(batch.initial_quantity),
                "harvest_date": str(batch.harvest_date),
            }
            record_event(
                db=db,
                batch_id=batch.id,
                event_type=EVENT_HARVEST,
                payload=harvest_payload,
                org_id=plot_org_id,
                user_id=current_user.id,
            )

            # Ghi audit log
            record_action(db, current_user, ACTION_CREATE, ENTITY_BATCH, batch.id)
            db.commit()
            break
        except IntegrityError:
            db.rollback()
            if attempt == max_retries - 1:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Không thể tạo mã lô duy nhất sau nhiều lần thử lại.",
                )
        except Exception as exc:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Không thể lưu lô nông sản vào cơ sở dữ liệu.",
            ) from exc

    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Tạo lô nông sản thất bại.",
        )

    db.refresh(batch)
    return batch


@router.get(
    "",
    response_model=list[BatchResponse],
    status_code=status.HTTP_200_OK,
    summary="Danh sách lô nông sản (T-33)",
    description=(
        "Lấy danh sách các lô nông sản mà tổ chức của người dùng đang nắm giữ.\n\n"
        "- Phân trang: 20 lô/trang (page=1, limit=20).\n"
        "- Sắp xếp: Ngày thu hoạch mới nhất trước.\n"
        "- Tìm kiếm: Tham số `search` theo mã lô không phân biệt hoa/thường.\n"
        "- Bộ lọc: Tham số `product_id` lọc theo sản phẩm."
    ),
)
def list_batches(
    page: int = Query(default=1, ge=1, description="Số trang (bắt đầu từ 1)."),
    limit: int = Query(default=20, ge=1, le=100, description="Số lượng mỗi trang (mặc định 20)."),
    search: str | None = Query(default=None, description="Tìm kiếm theo mã lô (case-insensitive)."),
    product_id: int | None = Query(default=None, ge=1, description="Lọc theo mã sản phẩm."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Batch]:
    """Lấy danh sách lô theo phân trang, sắp xếp và bộ lọc (T-33)."""
    try:
        # Tự động quét và cập nhật cờ quá hạn bàn giao 48h để bên gửi luôn thấy trạng thái mới nhất (T-56, T-57)
        check_overdue_handovers(db)
        stmt = select(Batch)

        # 1. Chỉ trả về các lô mà tổ chức của người dùng đang giữ (T-33). Inspector được xem liên tổ chức.
        if current_user.role == ROLE_INSPECTOR:
            pass
        else:
            if current_user.organization_id is None:
                raise HTTPException(403, "Tài khoản chưa được liên kết với tổ chức.")
            stmt = stmt.where(Batch.current_org_id == current_user.organization_id)

        # 2. Tìm kiếm theo mã lô không phân biệt hoa/thường (T-33)
        if search and search.strip():
            search_term = f"%{search.strip()}%"
            stmt = stmt.where(Batch.code.ilike(search_term))

        # 3. Lọc theo product_id (T-33)
        if product_id is not None:
            stmt = stmt.where(Batch.product_id == product_id)

        # 4. Sắp xếp theo ngày thu hoạch mới nhất trước (T-33)
        stmt = stmt.order_by(Batch.harvest_date.desc(), Batch.id.desc())

        # 5. Phân trang 20 lô/trang (T-33)
        offset = (page - 1) * limit
        stmt = stmt.offset(offset).limit(limit)

        return list(db.scalars(stmt).all())
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Lỗi khi truy vấn danh sách lô nông sản từ cơ sở dữ liệu.",
        ) from exc


@router.get(
    "/{batch_id}",
    response_model=BatchResponse,
    status_code=status.HTTP_200_OK,
    summary="Xem chi tiết một lô nông sản",
    description="Trả về thông tin chi tiết của lô theo `id`. Trả `404` nếu không tồn tại.",
)
def get_batch(
    batch_id: int = Path(..., ge=1, description="ID lô nông sản cần xem."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Batch:
    """Lấy chi tiết một lô nông sản theo ``id``."""
    check_overdue_handovers(db)
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy lô nông sản có id={batch_id}.",
        )
    if not can_view_batch(db, current_user.organization_id, batch_id, user_role=current_user.role):
        raise HTTPException(403, "Bạn không có quyền xem lô nông sản này.")
    return batch


def _validate_batch_update(db: Session, batch: Batch, payload: BatchUpdate):
    batch_id = batch.id
    if batch.status == "CONSUMED":
        raise HTTPException(400, "Lô nông sản đã tiêu thụ (CONSUMED), không thể chỉnh sửa.")
    if payload.harvest_date > date.today():
        raise HTTPException(400, "Ngày thu hoạch không thể ở tương lai.")
    if batch.pending_handover is not None:
        raise HTTPException(409, "Không thể sửa lô đang chờ bàn giao.")
    has_relations = db.scalar(select(BatchRelation.id).where(
        (BatchRelation.parent_batch_id == batch_id) | (BatchRelation.child_batch_id == batch_id))) is not None
    has_handover = bool(batch.handovers)
    raw_qty = payload.initial_quantity if payload.initial_quantity is not None else payload.quantity
    if raw_qty is not None and Decimal(str(raw_qty)) <= 0:
        raise HTTPException(400, "Khối lượng phải lớn hơn 0.")
    remaining = payload.remaining_quantity
    limit = Decimal(str(raw_qty if raw_qty is not None else batch.initial_quantity))
    if remaining is not None and (Decimal(str(remaining)) < 0 or Decimal(str(remaining)) > limit):
        raise HTTPException(400, "Khối lượng còn lại phải nằm trong khối lượng ban đầu.")
    if has_relations or has_handover:
        target_plot = payload.plot_id or payload.farm_id
        identity_changed = any((
            raw_qty is not None and Decimal(str(raw_qty)) != batch.initial_quantity,
            remaining is not None and Decimal(str(remaining)) != batch.remaining_quantity,
            payload.product_id is not None and payload.product_id != batch.product_id,
            payload.product_name is not None and payload.product_name != batch.product_name,
            target_plot is not None and target_plot != batch.plot_id,
            payload.harvest_date != batch.harvest_date,
        ))
        if identity_changed:
            raise HTTPException(409, "Lô đã tách/gộp hoặc bàn giao; không thể sửa nguồn gốc hay khối lượng.")
    return has_relations or has_handover, raw_qty, remaining


@router.put(
    "/{batch_id}",
    response_model=BatchResponse,
    status_code=status.HTTP_200_OK,
    summary="Cập nhật lô nông sản",
    description="Cập nhật thông tin lô theo ID. Yêu cầu đăng nhập farmer/admin.",
)
def update_batch(
    payload: BatchUpdate,
    batch_id: int = Path(..., ge=1, description="ID lô nông sản cần sửa."),
    current_user: User = Depends(require_farmer),
    db: Session = Depends(get_db),
) -> Batch:
    """Cập nhật thông tin lô nông sản."""
    check_action_permission(current_user, "BATCH_UPDATE")
    db.execute(update(Batch).where(Batch.id == batch_id).values(status=Batch.status))
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy lô nông sản có id={batch_id}.",
        )

    # Kiểm tra quyền tổ chức
    if (
        current_user.organization_id is None
        or batch.current_org_id != current_user.organization_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền sửa lô nông sản của tổ chức khác.",
        )

    has_history, raw_qty, remaining = _validate_batch_update(db, batch, payload)
    before = {"plot_id": batch.plot_id, "product_id": batch.product_id,
              "initial_quantity": str(batch.initial_quantity), "remaining_quantity": str(batch.remaining_quantity),
              "harvest_date": str(batch.harvest_date)}

    target_plot_id = payload.plot_id or payload.farm_id
    if target_plot_id:
        plot = db.get(Plot, target_plot_id)
        farm = db.get(Farm, target_plot_id)
        if plot is None and farm is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Không tìm thấy thửa đất có id={target_plot_id}.",
            )
        plot_org_id = plot.organization_id if plot else farm.organization_id  # type: ignore
        if current_user.organization_id is None or plot_org_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Bạn không có quyền chuyển lô nông sản sang vùng trồng của tổ chức khác.",
            )
        batch.plot_id = target_plot_id
        batch.farm_id = target_plot_id

    if payload.product_id:
        prod = db.get(Product, payload.product_id)
        if prod is None:
            raise HTTPException(404, "Không tìm thấy sản phẩm.")
        batch.product_id = prod.id
        batch.product_name = prod.name
    elif payload.product_name:
        batch.product_name = payload.product_name

    raw_qty = payload.initial_quantity if payload.initial_quantity is not None else payload.quantity
    if raw_qty is not None:
        batch.initial_quantity = Decimal(str(raw_qty))
        if payload.remaining_quantity is not None:
            batch.remaining_quantity = Decimal(str(payload.remaining_quantity))
        elif not has_history:
            batch.remaining_quantity = Decimal(str(raw_qty))
        batch.quantity = float(raw_qty)

    if raw_qty is None and remaining is not None:
        batch.remaining_quantity = Decimal(str(remaining))
    batch.harvest_date = payload.harvest_date

    try:
        after = {"plot_id": batch.plot_id, "product_id": batch.product_id,
                 "initial_quantity": str(batch.initial_quantity), "remaining_quantity": str(batch.remaining_quantity),
                 "harvest_date": str(batch.harvest_date)}
        record_event(db, batch_id, "BATCH_UPDATED", {"before": before, "after": after},
                     batch.current_org_id, current_user.id)
        record_action(db, current_user, ACTION_UPDATE, ENTITY_BATCH, batch_id)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể cập nhật lô nông sản trong cơ sở dữ liệu.",
        ) from exc

    clear_trace_cache()
    db.refresh(batch)
    return batch


@router.delete(
    "/{batch_id}",
    response_model=DeleteResponse,
    status_code=status.HTTP_200_OK,
    summary="Xoá lô nông sản (chỉ admin)",
    description="Xoá một lô nông sản theo `id`.",
)
def delete_batch(
    batch_id: int = Path(..., ge=1, description="ID lô nông sản cần xoá."),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> DeleteResponse:
    """Xoá một lô nông sản (chỉ admin)."""
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy lô nông sản có id={batch_id}.",
        )

    if (
        current_user.organization_id is None
        or batch.current_org_id != current_user.organization_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền xoá lô nông sản của tổ chức khác.",
        )

    from app.models import BatchEvent
    if db.scalar(select(BatchEvent.id).where(BatchEvent.batch_id == batch_id)) is not None:
        raise HTTPException(409, "Lô đã có lịch sử bất biến; không thể xóa.")
    batch_name = batch.product_name or batch.code
    db.delete(batch)
    try:
        record_action(db, current_user, ACTION_DELETE, ENTITY_BATCH, batch_id)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể xoá lô nông sản khỏi cơ sở dữ liệu.",
        ) from exc

    return DeleteResponse(
        message=f"Đã xoá lô nông sản #{batch_id} ({batch_name}).",
        deleted_id=batch_id,
        deleted_batches=None,
    )


# ==============================================================================
# SPRINT 3: TÁCH LÔ, GỘP LÔ, TRUY NGƯỢC NGUỒN GỐC & TỔNG HỢP (T-40, T-44, T-49, T-58)
# ==============================================================================
@router.post(
    "/merge",
    response_model=BatchMergeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Gộp nhiều lô nông sản (T-44, T-45, T-47)",
    description=(
        "Gộp tối thiểu 2 lô mẹ cùng loại sản phẩm thuộc tổ chức hiện tại thành một lô mới.\n\n"
        "- Chống Deadlock (T-44): Khóa dòng các lô mẹ theo thứ tự ID tăng dần.\n"
        "- Kiểm tra hợp lệ (T-45): Cùng sản phẩm, cùng tổ chức, khối lượng lấy > 0 và <= remaining_quantity.\n"
        "- Ghi sự kiện MERGE và EXPORT_MERGE vào Hash-Chain (T-47)."
    ),
)
def merge_batches(  # noqa: C901
    payload: BatchMergeRequest,
    current_user: User = Depends(require_farmer),
    db: Session = Depends(get_db),
) -> BatchMergeResponse:
    """Gộp nhiều lô nông sản cùng loại sản phẩm thành một lô mới (T-44, T-45, T-47)."""
    check_action_permission(current_user, "MERGE")
    db.execute(update(Batch).values(status=Batch.status))
    if len(payload.items) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Phải chọn ít nhất 2 lô mẹ để gộp.",
        )

    parent_ids = [it.parent_batch_id for it in payload.items]
    if len(set(parent_ids)) != len(parent_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Danh sách các lô mẹ bị trùng lặp trong cùng một yêu cầu gộp.",
        )

    # 1. Chống Deadlock (T-44): Sắp xếp danh sách parent_batch_id tăng dần trước khi khóa
    sorted_items = sorted(payload.items, key=lambda x: x.parent_batch_id)

    # Check quarantine for the whole requested set before quantity validation;
    # another exhausted input must not conceal an affected input's recall code.
    for item in sorted_items:
        candidate = db.get(Batch, item.parent_batch_id)
        if candidate is not None and candidate.current_org_id == current_user.organization_id:
            ensure_not_recalled(db, candidate.id)

    # 2. Khóa và kiểm tra từng dòng lô mẹ
    locked_parents: list[tuple[Batch, Decimal]] = []
    for item in sorted_items:
        p = db.scalar(
            select(Batch)
            .where(Batch.id == item.parent_batch_id)
            .with_for_update()
        )
        if p is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Không tìm thấy lô mẹ có id={item.parent_batch_id}.",
            )

        if current_user.organization_id is None or p.current_org_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Lô nông sản {p.code} (id={p.id}) không thuộc tổ chức của bạn.",
            )

        ensure_not_recalled(db, p.id)

        if p.status == "CONSUMED":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Lô {p.code} đã tiêu thụ (CONSUMED), không thể gộp.",
            )

        if p.product_id != payload.product_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Lô {p.code} có sản phẩm khác với mã sản phẩm yêu cầu gộp ({payload.product_id}).",
            )

        if p.pending_handover is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Lô {p.code} đang có yêu cầu bàn giao chờ xác nhận, không thể gộp.",
            )

        qty_take = Decimal(str(item.quantity))
        if qty_take <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Khối lượng lấy từ lô {p.code} phải lớn hơn 0.",
            )

        if qty_take > p.remaining_quantity:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Khối lượng lấy từ lô {p.code} ({qty_take}) vượt quá khối lượng còn lại ({p.remaining_quantity}).",
            )

        locked_parents.append((p, qty_take))

    product = db.get(Product, payload.product_id)
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy sản phẩm có id={payload.product_id}.",
        )

    # 3. Transaction nguyên tử: Trừ khối lượng, tạo lô mới, tạo quan hệ, ghi hash-chain
    total_merged_qty = Decimal("0")
    parent_summary: list[dict[str, Any]] = []

    try:
        for p, qty_take in locked_parents:
            # Trừ khối lượng nguyên tử để chống thất thoát/âm khối lượng khi gộp
            # đồng thời (T-44, T-45). Hoạt động đúng cả trên SQLite vì không phụ
            # thuộc vào `SELECT ... FOR UPDATE`.
            decremented = db.execute(
                update(Batch)
                .where(Batch.id == p.id, Batch.remaining_quantity >= qty_take)
                .values(
                    remaining_quantity=Batch.remaining_quantity - qty_take,
                    quantity=Batch.remaining_quantity - qty_take,
                )
                .execution_options(synchronize_session=False)
            )
            if decremented.rowcount != 1:
                db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Khối lượng lấy từ lô {p.code} ({qty_take}) vượt quá khối lượng còn lại "
                        "hoặc lô vừa bị thay đổi bởi giao dịch khác."
                    ),
                )

            db.refresh(p)
            if p.remaining_quantity == 0:
                p.status = "MERGED"
            total_merged_qty += qty_take
            parent_summary.append({
                "id": p.id,
                "code": p.code,
                "quantity_taken": float(qty_take),
            })

        db.flush()

        first_parent = locked_parents[0][0]
        user_org_id = current_user.organization_id or first_parent.current_org_id or 1
        new_batch = Batch(
            code=generate_batch_code(),
            plot_id=first_parent.plot_id,
            farm_id=first_parent.farm_id,
            product_id=product.id,
            product_name=product.name,
            harvest_date=max(p[0].harvest_date for p in locked_parents),
            initial_quantity=total_merged_qty,
            remaining_quantity=total_merged_qty,
            quantity=float(total_merged_qty),
            current_org_id=user_org_id,
            status="ACTIVE",
        )
        db.add(new_batch)
        db.flush()

        # Tạo quan hệ BatchRelation loại 'MERGE' và ghi hash events
        for p, qty_take in locked_parents:
            rel = BatchRelation(
                parent_batch_id=p.id,
                child_batch_id=new_batch.id,
                transferred_quantity=qty_take,
                relation_type=RELATION_MERGE,
            )
            db.add(rel)

            record_event(
                db=db,
                batch_id=p.id,
                event_type=EVENT_EXPORT_MERGE,
                payload={
                    "merged_batch_code": new_batch.code,
                    "merged_batch_id": new_batch.id,
                    "quantity_taken": float(qty_take),
                },
                org_id=user_org_id,
                user_id=current_user.id,
            )

        # Ghi sự kiện MERGE vào hash-chain của lô mới
        record_event(
            db=db,
            batch_id=new_batch.id,
            event_type=EVENT_MERGE,
            payload={
                "parent_batches": parent_summary,
                "total_quantity": float(total_merged_qty),
                "product_name": product.name,
            },
            org_id=user_org_id,
            user_id=current_user.id,
        )

        record_action(db, current_user, ACTION_CREATE, ENTITY_BATCH, new_batch.id)
        db.commit()
    except (OperationalError, SQLAlchemyError) as exc:
        db.rollback()
        err_msg = str(exc).lower()
        if "locked" in err_msg or "busy" in err_msg:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cơ sở dữ liệu đang bận xử lý giao dịch khác trên lô này, vui lòng thử lại sau giây lát.",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Lỗi cơ sở dữ liệu khi thực hiện gộp lô.",
        ) from exc

    db.refresh(new_batch)
    return BatchMergeResponse(
        merged_batch=new_batch,
        parent_batches=parent_summary,
        message=f"Gộp thành công {len(locked_parents)} lô thành lô mới {new_batch.code}.",
    )


@router.post(
    "/{batch_id}/split",
    response_model=BatchSplitResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Tách lô nông sản (T-40, T-42, T-47)",
    description=(
        "Tách một lô mẹ thành nhiều lô con mới.\n\n"
        "- Khóa dòng (T-42): Dùng with_for_update() để chống race condition khi 2 người cùng tách.\n"
        "- Kiểm tra: Thuộc tổ chức hiện tại, tổng khối lượng con <= remaining_quantity của lô mẹ.\n"
        "- Ghi Hash-Chain: Sự kiện SPLIT trên lô mẹ và GENESIS_SPLIT trên từng lô con (T-47)."
    ),
)
@router.post(
    "/{batch_id}/split/",
    response_model=BatchSplitResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
def split_batch(  # noqa: C901
    payload: BatchSplitRequest,
    batch_id: str = Path(..., description="ID số nguyên hoặc Mã chuỗi của lô mẹ cần tách."),
    current_user: User = Depends(require_farmer),
    db: Session = Depends(get_db),
) -> BatchSplitResponse:
    """Tách lô nông sản thành nhiều lô con (T-40, T-42, T-47)."""
    check_action_permission(current_user, "SPLIT")
    db.execute(update(Batch).values(status=Batch.status))
    # 1. Khóa dòng lô mẹ để chống Race Condition (T-42)
    # Hỗ trợ tìm kiếm theo cả ID số nguyên lẫn Mã định danh chuỗi (ví dụ: XK-000001)
    clean_id = str(batch_id).strip()
    if clean_id.startswith("#"):
        clean_id = clean_id[1:].strip()

    parent: Batch | None = None
    if clean_id.isdigit():
        parent = db.scalar(select(Batch).where(Batch.id == int(clean_id)).with_for_update())

    if parent is None:
        parent = db.scalar(select(Batch).where(Batch.code == str(batch_id).strip()).with_for_update())

    if parent is None and clean_id != str(batch_id).strip():
        parent = db.scalar(select(Batch).where(Batch.code == clean_id).with_for_update())

    if parent is None:
        parent = db.scalar(select(Batch).where(Batch.code.ilike(str(batch_id).strip())).with_for_update())

    if parent is None and clean_id != str(batch_id).strip():
        parent = db.scalar(select(Batch).where(Batch.code.ilike(clean_id)).with_for_update())

    if parent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy lô nông sản '{batch_id}'.",
        )

    if current_user.organization_id is None or parent.current_org_id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Lô nông sản không thuộc tổ chức của bạn.",
        )

    ensure_not_recalled(db, parent.id)

    if parent.pending_handover is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Không thể tách lô khi đang có yêu cầu bàn giao chờ xác nhận.",
        )

    if parent.status == "CONSUMED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Lô nông sản đã tiêu thụ (CONSUMED), không thể tách.",
        )

    if parent.status not in ("ACTIVE", "SPLIT"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Không thể tách lô có trạng thái '{parent.status}'.",
        )

    if not payload.items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Danh sách khối lượng lô con không được để trống.",
        )

    for it in payload.items:
        if it.quantity <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Khối lượng từng lô con phải lớn hơn 0.",
            )

    total_split = sum(Decimal(str(it.quantity)) for it in payload.items)
    if total_split > parent.remaining_quantity:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Tổng khối lượng tách ({total_split}) vượt quá "
                f"khối lượng còn lại của lô mẹ ({parent.remaining_quantity})."
            ),
        )

    child_batches: list[Batch] = []
    child_codes: list[str] = []
    user_org_id = current_user.organization_id or parent.current_org_id or 1

    try:
        # Trừ khối lượng lô mẹ bằng UPDATE có điều kiện NGUYÊN TỬ (T-42, T-43).
        # Cách này chống thất thoát/âm khối lượng khi 2 giao dịch tách đồng thời,
        # và quan trọng là hoạt động ĐÚNG cả trên SQLite - nơi `SELECT ... FOR UPDATE`
        # (with_for_update) không được hỗ trợ nên không thực sự khoá dòng.
        decremented = db.execute(
            update(Batch)
            .where(Batch.id == parent.id, Batch.remaining_quantity >= total_split)
            .values(
                remaining_quantity=Batch.remaining_quantity - total_split,
                quantity=Batch.remaining_quantity - total_split,
            )
            .execution_options(synchronize_session=False)
        )
        if decremented.rowcount != 1:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Tổng khối lượng tách ({total_split}) vượt quá khối lượng còn lại của lô mẹ "
                    "hoặc lô mẹ vừa bị thay đổi bởi giao dịch khác."
                ),
            )

        # Đồng bộ lại trạng thái mới nhất của lô mẹ sau khi cập nhật nguyên tử
        db.refresh(parent)
        if parent.remaining_quantity == 0:
            parent.status = "SPLIT"
        db.flush()

        # Tạo từng lô con
        for it in payload.items:
            c_qty = Decimal(str(it.quantity))
            code = generate_batch_code()
            child = Batch(
                code=code,
                plot_id=parent.plot_id,
                farm_id=parent.farm_id,
                product_id=parent.product_id,
                product_name=parent.product_name,
                harvest_date=parent.harvest_date,
                initial_quantity=c_qty,
                remaining_quantity=c_qty,
                quantity=float(c_qty),
                current_org_id=parent.current_org_id,
                status="ACTIVE",
            )
            db.add(child)
            db.flush()

            rel = BatchRelation(
                parent_batch_id=parent.id,
                child_batch_id=child.id,
                transferred_quantity=c_qty,
                relation_type=RELATION_SPLIT,
            )
            db.add(rel)

            record_event(
                db=db,
                batch_id=child.id,
                event_type=EVENT_GENESIS_SPLIT,
                payload={
                    "parent_batch_code": parent.code,
                    "parent_batch_id": parent.id,
                    "quantity": float(c_qty),
                },
                org_id=user_org_id,
                user_id=current_user.id,
            )
            record_action(db, current_user, ACTION_CREATE, ENTITY_BATCH, child.id)

            child_batches.append(child)
            child_codes.append(child.code)

        # Ghi sự kiện SPLIT vào hash-chain của lô mẹ
        record_event(
            db=db,
            batch_id=parent.id,
            event_type=EVENT_SPLIT,
            payload={
                "child_batch_codes": child_codes,
                "child_quantities": [float(it.quantity) for it in payload.items],
                "total_split_quantity": float(total_split),
            },
            org_id=user_org_id,
            user_id=current_user.id,
        )
        record_action(db, current_user, ACTION_UPDATE, ENTITY_BATCH, parent.id)

        # Chụp ảnh phản hồi NGAY khi transaction còn lành mạnh (trước commit).
        # Tránh việc đối tượng bị hết hạn sau commit (expire_on_commit) phải lazy-load
        # lại và có thể thất bại trong tình huống tách lô đồng thời (race condition).
        parent_response = BatchResponse.model_validate(parent)
        child_responses = [BatchResponse.model_validate(c) for c in child_batches]
        message_text = f"Tách thành công lô mẹ {parent.code} thành {len(child_batches)} lô con."
        parent_id_val = parent.id

        db.commit()
    except (OperationalError, SQLAlchemyError) as exc:
        db.rollback()
        err_msg = str(exc).lower()
        if "locked" in err_msg or "busy" in err_msg:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cơ sở dữ liệu đang bận xử lý giao dịch khác trên lô này, vui lòng thử lại sau giây lát.",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Lỗi cơ sở dữ liệu khi thực hiện tách lô.",
        ) from exc

    clear_trace_cache(parent_id_val)

    return BatchSplitResponse(
        parent_batch=parent_response,
        child_batches=child_responses,
        message=message_text,
    )


@router.get(
    "/{batch_id}/trace-back",
    response_model=TraceBackResponse,
    status_code=status.HTTP_200_OK,
    summary="Truy ngược nguồn gốc phả hệ BFS (T-49, T-50, T-54)",
    description=(
        "Truy ngược toàn bộ cây phả hệ tổ tiên theo thuật toán BFS lặp (Level-by-level).\n\n"
        "- Áp dụng cache ngắn 60 giây (T-50).\n"
        "- Phát hiện chu trình (Cycle detection) chống lỗi phả hệ vô tận (T-49).\n"
        "- Phân quyền tổ tiên (T-54): Chỉ cho phép xem nếu thuộc tổ chức hoặc nằm trong phả hệ."
    ),
)
def get_batch_traceback(
    batch_id: int = Path(..., ge=1, description="ID lô nông sản cần truy xuất nguồn gốc."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TraceBackResponse:
    """Truy ngược phả hệ theo thuật toán BFS và kiểm tra phân quyền tổ tiên (T-49, T-50, T-54)."""
    if not can_view_batch(db, current_user.organization_id, batch_id, user_role=current_user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền truy xuất thông tin nguồn gốc của lô nông sản này.",
        )

    result = trace_backwards(db, batch_id, use_cache=True)
    return TraceBackResponse(**result)


@router.get(
    "/{batch_id}/summary",
    response_model=BatchSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Tổng hợp chi tiết lô trung tâm tối ưu <= 3 truy vấn SQL (T-58)",
    description="Gom thông tin lô, thửa, sản phẩm, tổ chức đang giữ, cha trực tiếp, con trực tiếp trong tối đa 3 câu SQL.",
)
def get_batch_summary(
    batch_id: int = Path(..., ge=1, description="ID lô nông sản cần xem tổng hợp."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BatchSummaryResponse:
    """Tổng hợp chi tiết thông tin lô nông sản (T-58)."""
    # Truy vấn 1: Lô kèm plot, product, current_org
    batch = db.execute(
        select(Batch)
        .options(
            joinedload(Batch.plot),
            joinedload(Batch.product),
            joinedload(Batch.current_org),
            joinedload(Batch.farm),
            joinedload(Batch.handovers),
        )
        .where(Batch.id == batch_id)
    ).unique().scalar_one_or_none()
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy lô nông sản có id={batch_id}.",
        )

    if not can_view_batch(db, current_user.organization_id, batch_id, user_role=current_user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền xem thông tin chi tiết của lô nông sản này.",
        )

    # Truy vấn 2: Các quan hệ cha trực tiếp
    parent_rels = list(
        db.scalars(
            select(BatchRelation)
            .options(joinedload(BatchRelation.parent_batch))
            .where(BatchRelation.child_batch_id == batch_id)
        ).all()
    )

    # Truy vấn 3: Các quan hệ con trực tiếp
    child_rels = list(
        db.scalars(
            select(BatchRelation)
            .options(joinedload(BatchRelation.child_batch))
            .where(BatchRelation.parent_batch_id == batch_id)
        ).all()
    )

    direct_parents = [
        {
            "id": r.parent_batch.id,
            "code": r.parent_batch.code,
            "product_name": r.parent_batch.product_name,
            "transferred_quantity": float(r.transferred_quantity),
            "relation_type": r.relation_type,
            "created_at": str(r.created_at),
        }
        for r in parent_rels if r.parent_batch
    ]

    direct_children = [
        {
            "id": r.child_batch.id,
            "code": r.child_batch.code,
            "product_name": r.child_batch.product_name,
            "transferred_quantity": float(r.transferred_quantity),
            "relation_type": r.relation_type,
            "created_at": str(r.created_at),
        }
        for r in child_rels if r.child_batch
    ]

    has_pending = batch.pending_handover is not None
    pending_id = batch.pending_handover.id if has_pending else None
    is_active = batch.status in ("ACTIVE", "SPLIT")
    has_remaining = batch.remaining_quantity is not None and batch.remaining_quantity > 0
    is_owner = current_user.organization_id is not None and batch.current_org_id == current_user.organization_id

    actionable = bool(is_owner and is_active and (not has_pending) and has_remaining)
    can_split = actionable and check_action_permission(current_user, "SPLIT", raise_exception=False)
    can_merge = actionable and check_action_permission(current_user, "MERGE", raise_exception=False)
    can_handover = actionable and check_action_permission(current_user, "HANDOVER_INIT", raise_exception=False)

    is_consumer_role = check_action_permission(current_user, "BATCH_CONSUME", raise_exception=False)
    can_consume = bool(
        is_owner
        and is_active
        and (not has_pending)
        and has_remaining
        and is_consumer_role
        and batch.status != "CONSUMED"
    )

    plot_info = {
        "id": batch.plot.id,
        "name": batch.plot.name,
        "location": batch.plot.location,
        "area": batch.plot.area,
        "owner": batch.plot.owner,
        "coordinates": batch.plot.coordinates,
    } if batch.plot else None

    product_info = {
        "id": batch.product.id,
        "name": batch.product.name,
        "unit": batch.product.unit,
    } if batch.product else None

    org_info = {
        "id": batch.current_org.id,
        "name": batch.current_org.name,
        "code": batch.current_org.code,
    } if batch.current_org else None

    return BatchSummaryResponse(
        batch=batch,
        plot=plot_info,
        product=product_info,
        current_org=org_info,
        direct_parents=direct_parents,
        direct_children=direct_children,
        has_pending_handover=has_pending,
        pending_handover_id=pending_id,
        can_split=can_split,
        can_merge=can_merge,
        can_handover=can_handover,
        can_consume=can_consume,
    )


@router.get(
    "/{batch_id}/trace-forward",
    response_model=TraceForwardResponse,
    status_code=status.HTTP_200_OK,
    summary="Truy xuôi nguồn gốc phả hệ BFS (S-26, S-27)",
    description=(
        "Truy xuôi từ một lô nông sản đến toàn bộ các thế hệ hậu duệ qua các tầng tách và gộp.\n\n"
        "- Thuật toán BFS lặp không đệ quy.\n"
        "- Phát hiện chu trình (Cycle detection) ném HTTP 400 (S-26 AC 2).\n"
        "- Hiển thị tổ chức đang giữ, địa điểm và khối lượng còn lại (S-27).\n"
        "- Lô đã tiêu thụ (CONSUMED) hiển thị trạng thái và khối lượng còn lại = 0 (S-27 AC 2).\n"
        "- Phân quyền: Cán bộ kiểm tra (Inspector) xem toàn bộ liên tổ chức. "
        "Người dùng tổ chức không thấy thông tin nội bộ của tổ chức khác."
    ),
)
def get_batch_trace_forward(
    batch_id: int = Path(..., ge=1, description="ID lô nông sản gốc cần truy xuất xuôi."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TraceForwardResponse:
    """Truy xuôi phả hệ hậu duệ bằng thuật toán BFS lặp (S-26, S-27)."""
    batch = db.get(Batch, batch_id)
    if not batch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy lô nông sản.",
        )

    if not can_view_batch(db, current_user.organization_id, batch_id, user_role=current_user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền truy xuất thông tin nguồn gốc của lô nông sản này.",
        )

    result = trace_forward(db, batch_id, use_cache=True)

    # Phân quyền với từng lô hậu duệ (S-27, S-23):
    # Inspector và System Admin xem đầy đủ.
    # Tổ chức thường không được đọc thông tin nội bộ (location, owner, plot) của tổ chức khác nếu không có quyền.
    is_privileged = (current_user.role in (ROLE_INSPECTOR, "system_admin", "admin"))

    masked_descendants: dict[int, list[dict[str, Any]]] = {}
    for lvl, nodes in result["descendants_by_level"].items():
        masked_nodes = []
        for node in nodes:
            node_copy = dict(node)
            desc_id = node_copy["batch_id"]
            if not is_privileged:
                can_see = can_view_batch(db, current_user.organization_id, desc_id, user_role=current_user.role)
                if not can_see:
                    node_copy["location"] = "[Bảo mật]"
                    node_copy["owner"] = None
                    node_copy["plot_name"] = None
                    node_copy["farm_name"] = None
                    node_copy["is_masked"] = True
            masked_nodes.append(node_copy)
        masked_descendants[lvl] = masked_nodes

    masked_terminals: list[dict[str, Any]] = []
    for t_node in result["terminal_batches"]:
        t_copy = dict(t_node)
        desc_id = t_copy["batch_id"]
        if not is_privileged:
            can_see = can_view_batch(db, current_user.organization_id, desc_id, user_role=current_user.role)
            if not can_see:
                t_copy["location"] = "[Bảo mật]"
        masked_terminals.append(t_copy)

    return TraceForwardResponse(
        target_batch=result["target_batch"],
        descendants_by_level=masked_descendants,
        terminal_batches=masked_terminals,
        total_descendants=result["total_descendants"],
    )


@router.post(
    "/{batch_id}/consume",
    response_model=BatchConsumeResponse,
    status_code=status.HTTP_200_OK,
    summary="Ghi nhận lô hàng đã bán hết cho người tiêu dùng (S-29)",
    description=(
        "Nhà phân phối (Distributor) hoặc quản trị tổ chức ghi nhận lô hàng tại cửa hàng/siêu thị "
        "đã bán hết cho người tiêu dùng.\n\n"
        "- Khối lượng còn lại chuyển về 0.\n"
        "- Trạng thái chuyển thành 'CONSUMED'.\n"
        "- Ghi một sự kiện 'CONSUMED' vào chuỗi Hash-Chain.\n"
        "- Chặn mọi thao tác bàn giao, tách, gộp, sửa sau khi đã tiêu thụ (bất biến, không hoàn tác)."
    ),
)
def consume_batch(
    payload: BatchConsumeRequest | None = None,
    batch_id: int = Path(..., ge=1, description="ID lô nông sản đã bán hết."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BatchConsumeResponse:
    """Ghi nhận lô nông sản đã tiêu thụ (S-29)."""
    prepare_physical_write(db)
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy lô nông sản có id={batch_id}.",
        )

    # 1. Kiểm tra tổ chức đang giữ lô
    if current_user.organization_id is None or batch.current_org_id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Lô nông sản không thuộc tổ chức của bạn.",
        )

    # 2. Kiểm tra vai trò: Distributor hoặc Org Admin (theo ma trận BATCH_CONSUME)
    if not check_action_permission(current_user, "BATCH_CONSUME"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vai trò của bạn không có quyền ghi nhận tiêu thụ lô hàng.",
        )

    ensure_not_recalled(db, batch.id)

    # 3. Kiểm tra trạng thái hiện tại
    if batch.status == "CONSUMED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Lô {batch.code} đã ở trạng thái đã tiêu thụ (CONSUMED) trước đó.",
        )

    if batch.status not in ("ACTIVE", "SPLIT"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Không thể tiêu thụ lô nông sản có trạng thái '{batch.status}'.",
        )

    # 4. Kiểm tra đang chờ bàn giao
    if batch.pending_handover is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Không thể tiêu thụ lô nông sản đang có yêu cầu bàn giao chờ xác nhận.",
        )

    prev_qty = batch.remaining_quantity
    note_text = (payload.notes.strip() if (payload and payload.notes) else "") or "Lô hàng đã bán hết cho người tiêu dùng"

    # 5. Ghi sự kiện append-only hash chain
    event_payload = {
        "action": "CONSUMED",
        "batch_code": batch.code,
        "previous_remaining_quantity": str(prev_qty),
        "remaining_quantity": "0.00",
        "notes": note_text,
    }
    event = record_event(
        db=db,
        batch_id=batch.id,
        event_type="CONSUMED",
        payload=event_payload,
        org_id=batch.current_org_id,
        user_id=current_user.id,
        event_data=f"Lô {batch.code} đã bán hết cho người tiêu dùng (CONSUMED)",
        notes=note_text,
    )

    # 6. Cập nhật trạng thái và khối lượng
    batch.status = "CONSUMED"
    batch.remaining_quantity = Decimal("0.00")
    batch.quantity = 0.0

    # 7. Ghi audit log
    record_action(db, current_user, ACTION_UPDATE, ENTITY_BATCH, batch.id)

    db.commit()
    db.refresh(batch)
    db.refresh(event)

    # 8. Xóa cache truy xuất
    clear_trace_cache(batch.id)

    return BatchConsumeResponse(
        batch=batch,
        event=event,
        message="Ghi nhận lô nông sản đã tiêu thụ thành công.",
    )
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel

# Các import tuỳ thuộc theo cấu trúc dự án thực tế của nhóm bạn:
from app.database import get_db
from app.dependencies import get_current_active_user
from app.models.user import User
from app.services.recall import check_batch_quarantine_guard  # Guard S-38

class BatchConsumeRequest(BaseModel):
    notes: Optional[str] = None

@router.post("/{id}/consume", response_model=dict)
def consume_batch(
    id: int, 
    payload: Optional[BatchConsumeRequest] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    S-29: Tiêu thụ Nông sản (CONSUMED)
    - Kiểm tra Guard phong tỏa thu hồi (S-38) trước khi xử lý.
    - Cập nhật remaining_quantity = 0, status = 'CONSUMED'.
    - Ghi nhận sự kiện EVENT_CONSUMED vào chuỗi băm và khóa vĩnh viễn mọi thao tác.
    """
    # 1. Kiểm tra Guard phong tỏa thu hồi (S-38) - Sẽ trả về HTTP 409 Conflict nếu lô đang bị phong tỏa
    check_batch_quarantine_guard(db, id)

    # 2. Truy vấn tìm kiếm lô hàng trong Database (điều chỉnh tên model cho khớp với code của nhóm)
    # batch = db.query(BatchModel).filter(BatchModel.id == id).first()
    # if not batch:
    #     raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy lô hàng")

    # 3. Kiểm tra phân quyền RBAC (Chỉ distributor hoặc org_admin thuộc tổ chức nắm giữ lô)
    # if current_user.role not in ["distributor", "org_admin"] or current_user.organization_id != batch.organization_id:
    #     raise HTTPException(
    #         status_code=status.HTTP_403_FORBIDDEN, 
    #         detail="Bạn không có quyền tiêu thụ lô hàng này"
    #     )

    # 4. Kiểm tra trạng thái lô tránh bị CONSUMED 2 lần
    # if batch.status == 'CONSUMED':
    #     raise HTTPException(
    #         status_code=status.HTTP_400_BAD_REQUEST, 
    #         detail="Lô hàng đã được tiêu thụ trước đó"
    #     )

    # 5. Cập nhật dữ liệu
    # batch.remaining_quantity = 0
    # batch.status = 'CONSUMED'
    
    # 6. Ghi sự kiện EVENT_CONSUMED vào chuỗi băm (Append-only hash chain)
    # append_hash_chain_event(db, batch, event_type="EVENT_CONSUMED", user=current_user)

    # db.commit()
    # db.refresh(batch)

    # return {
    #     "message": "Tiêu thụ lô hàng thành công",
    #     "batch_id": batch.id,
    #     "status": batch.status,
    #     "remaining_quantity": batch.remaining_quantity,
    #     "event": "EVENT_CONSUMED"
    # }
    pass