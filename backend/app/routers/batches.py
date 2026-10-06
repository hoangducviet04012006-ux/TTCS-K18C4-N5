from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.audit import record_action
from app.database import generate_unique_batch_code, get_db
from app.models import (
    ACTION_CREATE,
    ACTION_DELETE,
    ACTION_UPDATE,
    ENTITY_BATCH,
    Batch,
    Farm,
    User,
)
from app.schemas import BatchCreate, BatchResponse, BatchUpdate, DeleteResponse
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
        "Mã lô (`batch_code`) được hệ thống tự động sinh ngẫu nhiên/tuần tự an toàn. "
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
        status.HTTP_422_UNPROCESSABLE_ENTITY: {
            "description": "Dữ liệu thu hoạch không hợp lệ.",
        },
    },
)
def create_batch(
    payload: BatchCreate,
    current_user: User = Depends(require_farmer),
    db: Session = Depends(get_db),
) -> Batch:
    """Tạo lô nông sản mới với mã lô sinh tự động.

    Args:
        payload: Dữ liệu lô đã được Pydantic validate.
        current_user: Tài khoản đã đăng nhập (farmer hoặc admin).
        db: Session SQLAlchemy từ dependency ``get_db``.

    Returns:
        Batch: Bản ghi lô vừa tạo kèm mã lô tự sinh (HTTP 201).

    Raises:
        HTTPException: 401/403 nếu chưa đăng nhập hoặc sai vai trò;
            404 nếu ``farm_id`` không tồn tại;
            422 nếu dữ liệu thu hoạch sai quy tắc;
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

    # Bước 2: Tự động sinh mã lô độc nhất (LOT-YYYYMMDD-XXXXXX)
    code = generate_unique_batch_code(db, payload.harvest_date)

    # Bỏ qua batch_code nếu client gửi lên
    batch_data = payload.model_dump(exclude={"batch_code"})
    batch = Batch(**batch_data, batch_code=code)
    db.add(batch)

    try:
        # `flush()` để database sinh `id` cho lô - audit log cần ID thật.
        db.flush()
        # Sprint 7: ghi lịch sử "ai đã tạo lô nông sản nào" (chưa commit vội).
        record_action(db, current_user, ACTION_CREATE, ENTITY_BATCH, batch.id)
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
    summary="Lấy danh sách lô nông sản của tổ chức",
    description=(
        "Trả về các lô nông sản thuộc quyền quản lý của tổ chức người dùng. "
        "Hỗ trợ tìm kiếm gần đúng theo mã lô (`?code=`), phân trang (`?limit=`, `?offset=`)."
    ),
)
def list_batches(
    code: str | None = Query(default=None, description="Tìm theo mã lô (gần đúng, không phân biệt hoa thường)."),
    limit: int | None = Query(default=None, ge=1, le=500, description="Số lượng lô tối đa trả về."),
    offset: int | None = Query(default=0, ge=0, description="Vị trí bắt đầu truy vấn."),
    current_user: User = Depends(require_farmer),
    db: Session = Depends(get_db),
) -> list[Batch]:
    """Lấy danh sách lô nông sản thuộc tổ chức hiện tại của người dùng.

    Ghi chú kiến trúc: lọc lô theo `organization_id` của thửa đất xuất xứ (khái niệm
    tổ chức đang giữ / sở hữu hiện tại), chuẩn bị để kết nối với luồng bàn giao lô ở Sprint sau.

    Args:
        code: Từ khoá tìm kiếm mã lô (gần đúng).
        limit: Số bản ghi tối đa.
        offset: Vị trí bắt đầu.
        current_user: Tài khoản đã đăng nhập.
        db: Session SQLAlchemy.

    Returns:
        list[Batch]: Danh sách lô nông sản của tổ chức.
    """
    query = select(Batch).join(Farm, Batch.farm_id == Farm.id)

    # Cô lập tổ chức: chỉ xem lô thuộc tổ chức của mình
    if current_user.organization_id is not None:
        query = query.where(Farm.organization_id == current_user.organization_id)

    # Tìm kiếm theo mã lô (không phân biệt hoa thường)
    if code is not None and code.strip():
        search_pattern = f"%{code.strip().lower()}%"
        query = query.where(func.lower(Batch.batch_code).like(search_pattern))

    query = query.order_by(Batch.id.asc())

    if offset:
        query = query.offset(offset)
    if limit:
        query = query.limit(limit)

    return list(db.scalars(query).all())


@router.get(
    "/{batch_id}",
    response_model=BatchResponse,
    status_code=status.HTTP_200_OK,
    summary="Xem chi tiết một lô nông sản",
    description="Trả về thông tin chi tiết của lô theo `id`. Trả `404` nếu không tồn tại.",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "Không tìm thấy lô nông sản.",
        },
    },
)
def get_batch(
    batch_id: int = Path(..., ge=1, description="ID lô nông sản cần xem."),
    current_user: User = Depends(require_farmer),
    db: Session = Depends(get_db),
) -> Batch:
    """Lấy chi tiết một lô nông sản theo ``id``.

    Args:
        batch_id: ID của lô cần tìm.
        current_user: Tài khoản đã đăng nhập.
        db: Session SQLAlchemy từ dependency ``get_db``.

    Returns:
        Batch: Bản ghi lô tương ứng (HTTP 200).

    Raises:
        HTTPException: 404 nếu không tìm thấy lô; 403 nếu thuộc tổ chức khác.
    """
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy lô nông sản có id={batch_id}.",
        )

    current_farm = db.get(Farm, batch.farm_id)
    if current_farm and current_user.organization_id is not None and current_farm.organization_id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền xem lô nông sản của tổ chức khác.",
        )

    return batch


@router.put(
    "/{batch_id}",
    response_model=BatchResponse,
    status_code=status.HTTP_200_OK,
    summary="Cập nhật lô nông sản",
    description=(
        "Cập nhật (thay thế) thông tin lô theo `id`. Client gửi đầy đủ các trường "
        "như khi tạo mới; `farm_id` mới cũng phải tồn tại. Mã lô (`batch_code`) không được phép sửa.\n\n"
        "**Phân quyền:** đăng nhập với role `farmer` hoặc `admin`."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Chưa đăng nhập."},
        status.HTTP_403_FORBIDDEN: {"description": "Vai trò không được phép."},
        status.HTTP_404_NOT_FOUND: {
            "description": "Không tìm thấy lô nông sản hoặc vùng trồng (farm_id).",
        },
        status.HTTP_422_UNPROCESSABLE_ENTITY: {
            "description": "Dữ liệu thu hoạch không hợp lệ.",
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

    Mã lô (batch_code) được giữ nguyên tuyệt đối, không cho phép client sửa hay ghi đè.

    Args:
        payload: Dữ liệu mới đã được Pydantic validate.
        batch_id: ID lô cần sửa.
        current_user: Tài khoản đã đăng nhập (farmer hoặc admin).
        db: Session SQLAlchemy từ dependency ``get_db``.

    Returns:
        Batch: Bản ghi lô sau khi cập nhật (HTTP 200).

    Raises:
        HTTPException: 401/403 nếu chưa đăng nhập hoặc sai vai trò;
            404 nếu không tìm thấy lô hoặc ``farm_id`` mới;
            422 nếu dữ liệu thu hoạch không hợp lệ;
            500 nếu ghi database thất bại (đã rollback).
    """
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy lô nông sản có id={batch_id}.",
        )

    current_farm = db.get(Farm, batch.farm_id)
    if current_farm and current_user.organization_id is not None and current_farm.organization_id != current_user.organization_id:
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

    # Cập nhật các trường, KHÔNG ĐỔI batch_code
    update_data = payload.model_dump(exclude={"batch_code"})
    for field, value in update_data.items():
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
    if current_farm and current_user.organization_id is not None and current_farm.organization_id != current_user.organization_id:
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