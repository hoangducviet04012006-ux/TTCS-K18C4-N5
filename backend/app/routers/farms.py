"""Router quản lý vùng trồng / thửa đất (Farm) - Sprint 1.

Cung cấp đầy đủ CRUD có kiểm soát cách ly theo tổ chức (organization_id):
- POST /farms           : tạo thửa đất mới (gán vào organization_id của user).
- GET /farms            : danh sách thửa đất (chỉ lấy của tổ chức hiện tại).
- GET /farms/{farm_id}  : chi tiết thửa đất (chặn 403 nếu thuộc tổ chức khác).
- PUT /farms/{farm_id}  : cập nhật thông tin thửa đất (chặn 403 nếu thuộc tổ chức khác).
- DELETE /farms/{farm_id}: xoá thửa đất (chỉ admin, chặn 403 nếu thuộc tổ chức khác).
"""

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.audit import record_action
from app.database import get_db
from app.models import (
    ACTION_CREATE,
    ACTION_DELETE,
    ACTION_UPDATE,
    ENTITY_FARM,
    Farm,
    User,
)
from app.schemas import DeleteResponse, FarmCreate, FarmResponse, FarmUpdate
from app.security import require_admin, require_farmer

router = APIRouter(
    prefix="/farms",
    tags=["Farms"],
)


@router.post(
    "",
    response_model=FarmResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Tạo vùng trồng / thửa đất mới",
    description=(
        "Lưu một thửa đất mới vào database, tự động gán theo `organization_id` của tài khoản hiện tại.\n\n"
        "**Phân quyền:** đăng nhập với role `farmer` hoặc `admin`."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Chưa đăng nhập."},
        status.HTTP_403_FORBIDDEN: {"description": "Vai trò hoặc tổ chức không hợp lệ."},
    },
)
def create_farm(
    payload: FarmCreate,
    current_user: User = Depends(require_farmer),
    db: Session = Depends(get_db),
) -> Farm:
    """Tạo thửa đất mới thuộc tổ chức hiện tại."""
    org_id = current_user.organization_id
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tài khoản chưa được liên kết với tổ chức nào.",
        )

    farm = Farm(**payload.model_dump(), organization_id=org_id)
    db.add(farm)

    try:
        db.flush()
        record_action(db, current_user, ACTION_CREATE, ENTITY_FARM, farm.id)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể lưu vùng trồng vào cơ sở dữ liệu.",
        ) from exc

    db.refresh(farm)
    return farm


@router.get(
    "",
    response_model=list[FarmResponse],
    status_code=status.HTTP_200_OK,
    summary="Lấy danh sách vùng trồng",
    description=(
        "Trả về danh sách vùng trồng thuộc tổ chức của tài khoản hiện tại.\n\n"
        "**Phân quyền:** đăng nhập với role `farmer` hoặc `admin`."
    ),
)
def list_farms(
    current_user: User = Depends(require_farmer),
    db: Session = Depends(get_db),
) -> list[Farm]:
    """Lấy danh sách vùng trồng (cách ly theo tổ chức)."""
    query = select(Farm).order_by(Farm.id)
    if current_user.organization_id is not None:
        query = query.where(Farm.organization_id == current_user.organization_id)
    return list(db.scalars(query).all())


@router.get(
    "/{farm_id}",
    response_model=FarmResponse,
    status_code=status.HTTP_200_OK,
    summary="Chi tiết vùng trồng",
    description="Xem chi tiết một vùng trồng. Trả về 403 nếu vùng trồng thuộc tổ chức khác.",
)
def get_farm(
    farm_id: int = Path(..., ge=1, description="ID vùng trồng."),
    current_user: User = Depends(require_farmer),
    db: Session = Depends(get_db),
) -> Farm:
    """Lấy chi tiết thửa đất (kiểm tra cách ly tổ chức)."""
    farm = db.get(Farm, farm_id)
    if farm is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy vùng trồng có id={farm_id}.",
        )

    if current_user.organization_id is not None and farm.organization_id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền truy cập dữ liệu của tổ chức khác.",
        )

    return farm


@router.put(
    "/{farm_id}",
    response_model=FarmResponse,
    status_code=status.HTTP_200_OK,
    summary="Cập nhật vùng trồng",
    description="Cập nhật thông tin thửa đất. Trả 403 nếu thửa đất thuộc tổ chức khác.",
)
def update_farm(
    payload: FarmUpdate,
    farm_id: int = Path(..., ge=1, description="ID vùng trồng cần sửa."),
    current_user: User = Depends(require_farmer),
    db: Session = Depends(get_db),
) -> Farm:
    """Cập nhật thông tin vùng trồng theo id."""
    farm = db.get(Farm, farm_id)
    if farm is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy vùng trồng có id={farm_id}.",
        )

    if current_user.organization_id is not None and farm.organization_id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền truy cập dữ liệu của tổ chức khác.",
        )

    for field, value in payload.model_dump().items():
        setattr(farm, field, value)

    try:
        record_action(db, current_user, ACTION_UPDATE, ENTITY_FARM, farm_id)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể cập nhật vùng trồng trong cơ sở dữ liệu.",
        ) from exc

    db.refresh(farm)
    return farm


@router.delete(
    "/{farm_id}",
    response_model=DeleteResponse,
    status_code=status.HTTP_200_OK,
    summary="Xoá vùng trồng (chỉ admin của tổ chức)",
    description="Xoá vùng trồng và các lô nông sản kèm theo. Trả 403 nếu vùng trồng thuộc tổ chức khác.",
)
def delete_farm(
    farm_id: int = Path(..., ge=1, description="ID vùng trồng cần xoá."),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> DeleteResponse:
    """Xoá một vùng trồng cùng các lô con của nó."""
    farm = db.get(Farm, farm_id)
    if farm is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy vùng trồng có id={farm_id}.",
        )

    if current_user.organization_id is not None and farm.organization_id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền truy cập dữ liệu của tổ chức khác.",
        )

    deleted_batches = len(farm.batches)
    db.delete(farm)
    try:
        record_action(db, current_user, ACTION_DELETE, ENTITY_FARM, farm_id)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể xoá vùng trồng khỏi cơ sở dữ liệu.",
        ) from exc

    return DeleteResponse(
        message=f"Đã xoá vùng trồng #{farm_id} và {deleted_batches} lô nông sản thuộc vùng đó.",
        deleted_id=farm_id,
        deleted_batches=deleted_batches,
    )
