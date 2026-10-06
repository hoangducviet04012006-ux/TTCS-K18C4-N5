"""Router quản lý lô nông sản (Batch).

Quan hệ: ``Farm 1 ---- N Batch``.

Cung cấp **đầy đủ CRUD** (hoàn thiện ở Sprint 5):

- ``POST   /batches``            : tạo lô nông sản (kiểm tra ``farm_id`` tồn tại).
- ``GET    /batches``            : lấy danh sách lô.
- ``GET    /batches/{batch_id}`` : xem chi tiết một lô.
- ``PUT    /batches/{batch_id}`` : cập nhật lô (có thể đổi sang vùng trồng khác).
- ``DELETE /batches/{batch_id}`` : xoá lô (chỉ admin).

**Phân quyền (Sprint 4):** ``POST``/``PUT`` dùng dependency ``require_farmer``
-> đăng nhập bằng role ``farmer`` hoặc ``admin`` (401 nếu chưa đăng nhập,
403 nếu sai vai trò); ``DELETE`` dùng ``require_admin`` -> chỉ admin. Hai endpoint
``GET`` giữ nguyên như trước (không yêu cầu đăng nhập) vì phục vụ tra cứu nguồn
gốc công khai.

**Lịch sử thao tác (Sprint 7):** mỗi lần ``POST``/``PUT``/``DELETE`` thành công,
router ghi thêm 1 dòng vào bảng ``audit_logs`` (``entity=batch``) thông qua
``record_action()`` - xem ``app/audit.py`` và endpoint ``GET /audit-logs``.
Log nằm trong cùng transaction với thao tác nên thao tác thất bại
(404/403/500) không để lại log.
"""

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.batch_tree import (
    build_batch_tree_response,
    get_batch_ancestors,
    get_batch_with_direct_relations,
)
from app.audit import record_action
from app.events import record_batch_event
from app.database import get_db
from app.models import (
    ACTION_CREATE,
    ACTION_DELETE,
    ACTION_UPDATE,
    ENTITY_BATCH,
    Batch,
    Farm,
    User,
)
from app.schemas import (
    BatchAncestorsResponse,
    BatchCreate,
    BatchDetailResponse,
    BatchResponse,
    BatchSummaryResponse,
    BatchTreeDetailResponse,
    BatchUpdate,
    DeleteResponse,
)
from app.security import require_admin, require_farmer

router = APIRouter(
    prefix="/batches",
    tags=["Batches"],
)


@router.post(
    "",
    response_model=BatchResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Tạo lô nông sản",
    description=(
        "Tạo một lô nông sản thuộc về một vùng trồng. "
        "Nếu `farm_id` không tồn tại, API trả về `404 Not Found`.\n\n"
        "**Phân quyền:** đăng nhập với role `farmer` hoặc `admin` (yêu cầu header "
        "`Authorization: Basic ...`)."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Chưa đăng nhập.",
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "Vai trò không được phép.",
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "Vùng trồng (farm_id) không tồn tại.",
        },
    },
)
def create_batch(
    payload: BatchCreate,
    current_user: User = Depends(require_farmer),
    db: Session = Depends(get_db),
) -> Batch:
    """Tạo lô nông sản mới.

    Args:
        payload: Dữ liệu lô đã được Pydantic validate.
        current_user: Tài khoản đã đăng nhập (farmer hoặc admin) - cũng là người
            được ghi vào lịch sử thao tác.
        db: Session SQLAlchemy từ dependency ``get_db``.

    Returns:
        Batch: Bản ghi lô vừa tạo (HTTP 201).

    Raises:
        HTTPException: 401/403 nếu chưa đăng nhập hoặc sai vai trò;
            404 nếu ``farm_id`` không tồn tại;
            500 nếu ghi database thất bại (đã rollback).
    """
    # Bước 1: kiểm tra toàn vẹn tham chiếu - vùng trồng phải tồn tại.
    farm = db.get(Farm, payload.farm_id)
    if farm is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy vùng trồng có id={payload.farm_id}.",
        )

    if current_user.organization_id is not None and farm.organization_id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền tạo lô nông sản cho vùng trồng của tổ chức khác.",
        )

    # Bước 2: lưu lô nông sản.
    batch = Batch(**payload.model_dump(), current_org_id=farm.organization_id)
    db.add(batch)

    try:
        # `flush()` để database sinh `id` cho lô - audit log cần ID thật.
        db.flush()
        # Sprint 7: ghi lịch sử "ai đã tạo lô nông sản nào" (chưa commit vội).
        record_action(db, current_user, ACTION_CREATE, ENTITY_BATCH, batch.id)
        # S-11 & S-12: Tự động ghi event khởi tạo lô vào batch_events (append-only hash chain)
        record_batch_event(
            db=db,
            batch_id=batch.id,
            event_type="BATCH_CREATED",
            event_data=f"Khởi tạo lô nông sản: {batch.product_name}",
            user_id=current_user.id,
        )
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể lưu lô nông sản vào cơ sở dữ liệu.",
        ) from exc

    db.refresh(batch)
    return batch


@router.get(
    "",
    response_model=list[BatchResponse],
    status_code=status.HTTP_200_OK,
    summary="Lấy danh sách lô nông sản",
    description="Trả về toàn bộ lô nông sản, sắp xếp theo `id` tăng dần.",
)
def list_batches(db: Session = Depends(get_db)) -> list[Batch]:
    """Lấy danh sách lô nông sản.

    Args:
        db: Session SQLAlchemy từ dependency ``get_db``.

    Returns:
        list[Batch]: Danh sách lô (rỗng nếu chưa có dữ liệu).
    """
    return list(db.scalars(select(Batch).order_by(Batch.id)).all())


@router.get(
    "/{batch_id}",
    response_model=BatchDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Xem chi tiết một lô nông sản",
    description=(
        "Trả về thông tin chi tiết của lô theo `id` (kèm lô mẹ và danh sách lô con trực tiếp). "
        "Trả `404` nếu không tồn tại."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "Không tìm thấy lô nông sản.",
        },
    },
)
def get_batch(
    batch_id: int = Path(..., ge=1, description="ID lô nông sản cần xem."),
    db: Session = Depends(get_db),
) -> BatchDetailResponse:
    """Lấy chi tiết một lô nông sản theo ``id`` (phục vụ S-25).

    Args:
        batch_id: ID của lô cần tìm.
        db: Session SQLAlchemy từ dependency ``get_db``.

    Returns:
        BatchDetailResponse: Chi tiết lô nông sản bao gồm lô mẹ và các lô con trực tiếp.

    Raises:
        HTTPException: 404 nếu không tìm thấy lô.
    """
    batch = get_batch_with_direct_relations(db, batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy lô nông sản có id={batch_id}.",
        )

    parent_summary = None
    if batch.parent:
        parent_summary = BatchSummaryResponse(
            id=batch.parent.id,
            product_name=batch.parent.product_name,
            quantity=batch.parent.quantity,
            remaining_quantity=batch.parent.remaining_qty,
            unit=batch.parent.batch_unit,
            status=batch.parent.batch_status,
            current_org_name=batch.parent.current_org_name,
        )

    children_summary = [
        BatchSummaryResponse(
            id=child.id,
            product_name=child.product_name,
            quantity=child.quantity,
            remaining_quantity=child.remaining_qty,
            unit=child.batch_unit,
            status=child.batch_status,
            current_org_name=child.current_org_name,
        )
        for child in batch.children
    ]

    return BatchDetailResponse(
        id=batch.id,
        farm_id=batch.farm_id,
        farm_name=batch.farm.name if batch.farm else None,
        farm_location=batch.farm.location if batch.farm else None,
        product_name=batch.product_name,
        initial_quantity=batch.quantity,
        remaining_quantity=batch.remaining_qty,
        unit=batch.batch_unit,
        harvest_date=batch.harvest_date,
        status=batch.batch_status,
        current_org_id=batch.holder_org_id,
        current_org_name=batch.current_org_name,
        parent_id=batch.parent_id,
        parent=parent_summary,
        children=children_summary,
    )


@router.get(
    "/{batch_id}/tree",
    response_model=BatchTreeDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="[T-58] Truy vấn tổng hợp chi tiết lô kèm lô mẹ và lô con trực tiếp",
    description=(
        "API nhận `batch_id` và trả về thông tin chi tiết của lô, kèm duy nhất lô mẹ trực tiếp "
        "(parent = null nếu không có) và danh sách các lô con trực tiếp (children = [] nếu không có). "
        "Không lấy toàn bộ tổ tiên/hậu duệ và tối ưu SQL tránh N+1 query."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "Không tìm thấy lô nông sản.",
        },
    },
)
def get_batch_tree(
    batch_id: int = Path(..., ge=1, description="ID lô nông sản cần xem cây quan hệ."),
    db: Session = Depends(get_db),
) -> dict:
    """Truy vấn tổng hợp chi tiết lô kèm lô mẹ và các lô con trực tiếp (T-58).

    Args:
        batch_id: ID của lô cần xem.
        db: Session SQLAlchemy từ dependency ``get_db``.

    Returns:
        dict: Cấu trúc JSON chuẩn T-58 gồm 3 khối {batch, parent, children}.

    Raises:
        HTTPException: 404 nếu không tìm thấy lô.
    """
    batch = get_batch_with_direct_relations(db, batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy lô nông sản có id={batch_id}.",
        )

    return build_batch_tree_response(batch)


@router.get(
    "/{batch_id}/ancestors",
    response_model=BatchAncestorsResponse,
    status_code=status.HTTP_200_OK,
    summary="[T-59] Lấy danh sách các lô tổ tiên của một lô nông sản",
    description=(
        "API truy vết ngược từ `parent_id` của lô hiện tại lên các thế hệ trước "
        "(Mẹ -> Bà -> Cố -> Lô gốc). Trả `404` nếu lô không tồn tại."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "Không tìm thấy lô nông sản.",
        },
    },
)
def get_batch_ancestors_route(
    batch_id: int = Path(..., ge=1, description="ID lô nông sản cần truy vết tổ tiên."),
    db: Session = Depends(get_db),
) -> dict:
    """Lấy danh sách tổ tiên của một lô nông sản theo quan hệ database (T-59).

    Args:
        batch_id: ID của lô cần xem danh sách tổ tiên.
        db: Session SQLAlchemy từ dependency ``get_db``.

    Returns:
        dict: Cấu trúc JSON chứa batch_id và danh sách ancestors.

    Raises:
        HTTPException: 404 nếu không tìm thấy lô.
    """
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy lô nông sản có id={batch_id}.",
        )

    ancestors = get_batch_ancestors(db, batch_id)
    return {
        "batch_id": batch_id,
        "ancestors": ancestors,
    }


@router.put(
    "/{batch_id}",
    response_model=BatchResponse,
    status_code=status.HTTP_200_OK,
    summary="Cập nhật lô nông sản",
    description=(
        "Cập nhật (thay thế) thông tin lô theo `id`. Client gửi đầy đủ các trường "
        "như khi tạo mới; `farm_id` mới cũng phải tồn tại. Trả `404` nếu lô "
        "**hoặc** vùng trồng không tồn tại.\n\n"
        "**Phân quyền:** đăng nhập với role `farmer` hoặc `admin`."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Chưa đăng nhập."},
        status.HTTP_403_FORBIDDEN: {"description": "Vai trò không được phép."},
        status.HTTP_404_NOT_FOUND: {
            "description": "Không tìm thấy lô nông sản hoặc vùng trồng (farm_id).",
        },
    },
)
def update_batch(
    payload: BatchUpdate,
    batch_id: int = Path(..., ge=1, description="ID lô nông sản cần sửa."),
    current_user: User = Depends(require_farmer),
    db: Session = Depends(get_db),
) -> Batch:
    """Cập nhật thông tin lô nông sản theo ``id``.

    Args:
        payload: Dữ liệu mới đã được Pydantic validate (đủ 4 trường).
        batch_id: ID lô cần sửa.
        current_user: Tài khoản đã đăng nhập (farmer hoặc admin) - cũng là người
            được ghi vào lịch sử thao tác.
        db: Session SQLAlchemy từ dependency ``get_db``.

    Returns:
        Batch: Bản ghi lô sau khi cập nhật (HTTP 200).

    Raises:
        HTTPException: 401/403 nếu chưa đăng nhập hoặc sai vai trò;
            404 nếu không tìm thấy lô hoặc ``farm_id`` mới;
            500 nếu ghi database thất bại (đã rollback).
    """
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy lô nông sản có id={batch_id}.",
        )

    current_farm = db.get(Farm, batch.farm_id)
    if (
        current_farm
        and current_user.organization_id is not None
        and current_farm.organization_id != current_user.organization_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền sửa lô nông sản của tổ chức khác.",
        )

    # Kiểm tra lại toàn vẹn tham chiếu: vùng trồng (mới) phải tồn tại.
    farm = db.get(Farm, payload.farm_id)
    if farm is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy vùng trồng có id={payload.farm_id}.",
        )

    if current_user.organization_id is not None and farm.organization_id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền chuyển lô nông sản sang vùng trồng của tổ chức khác.",
        )

    for field, value in payload.model_dump().items():
        setattr(batch, field, value)

    try:
        # Sprint 7: ghi lịch sử "ai đã sửa lô nông sản nào" trong cùng transaction.
        record_action(db, current_user, ACTION_UPDATE, ENTITY_BATCH, batch_id)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể cập nhật lô nông sản trong cơ sở dữ liệu.",
        ) from exc

    db.refresh(batch)
    return batch


@router.delete(
    "/{batch_id}",
    response_model=DeleteResponse,
    status_code=status.HTTP_200_OK,
    summary="Xoá lô nông sản (chỉ admin)",
    description=(
        "Xoá một lô nông sản theo `id`.\n\n"
        "**Phân quyền:** chỉ `role = admin` được xoá (dùng `require_admin`). "
        "Farmer gọi sẽ nhận `403 Forbidden` - giao diện cũng ẩn nút Xoá với farmer.\n\n"
        "**Lịch sử thao tác:** ghi 1 dòng log cho lô vừa xoá "
        "(`action=delete`, `entity=batch`)."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Chưa đăng nhập."},
        status.HTTP_403_FORBIDDEN: {"description": "Đã đăng nhập nhưng không phải admin."},
        status.HTTP_404_NOT_FOUND: {"description": "Không tìm thấy lô nông sản."},
    },
)
def delete_batch(
    batch_id: int = Path(..., ge=1, description="ID lô nông sản cần xoá."),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> DeleteResponse:
    """Xoá một lô nông sản (chỉ admin).

    Args:
        batch_id: ID lô cần xoá.
        current_user: Tài khoản admin đã được ``require_admin`` kiểm tra quyền -
            cũng là người được ghi vào lịch sử thao tác.
        db: Session SQLAlchemy từ dependency ``get_db``.

    Returns:
        DeleteResponse: Thông báo kết quả xoá (HTTP 200).

    Raises:
        HTTPException: 401 nếu chưa đăng nhập; 403 nếu không phải admin;
            404 nếu không tìm thấy lô;
            500 nếu xoá trong database thất bại (đã rollback).
    """
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy lô nông sản có id={batch_id}.",
        )

    current_farm = db.get(Farm, batch.farm_id)
    if (
        current_farm
        and current_user.organization_id is not None
        and current_farm.organization_id != current_user.organization_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền xoá lô nông sản của tổ chức khác.",
        )

    # Lưu lại tên sản phẩm để viết thông báo (sau khi xoá không đọc được nữa).
    product_name = batch.product_name

    db.delete(batch)
    try:
        # Sprint 7: ghi lịch sử "ai đã xoá lô nông sản nào" trong cùng transaction.
        record_action(db, current_user, ACTION_DELETE, ENTITY_BATCH, batch_id)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể xoá lô nông sản khỏi cơ sở dữ liệu.",
        ) from exc

    return DeleteResponse(
        message=f"Đã xoá lô nông sản #{batch_id} ({product_name}).",
        deleted_id=batch_id,
        # Xoá lô không kéo theo bản ghi nào khác -> null.
        deleted_batches=None,
    )
