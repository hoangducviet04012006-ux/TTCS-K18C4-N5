"""Router quản lý vùng trồng (Farm) - module đầu tiên của Sprint 2.

Cung cấp 2 endpoint:
- ``POST /farms`` : tạo vùng trồng mới.
- ``GET  /farms`` : lấy danh sách vùng trồng.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Farm
from app.schemas import FarmCreate, FarmResponse

router = APIRouter(
    prefix="/farms",
    tags=["Farms"],
)


@router.post(
    "",
    response_model=FarmResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Tạo vùng trồng mới",
    description="Lưu một vùng trồng mới vào database và trả về bản ghi vừa tạo (kèm `id`).",
)
def create_farm(payload: FarmCreate, db: Session = Depends(get_db)) -> Farm:
    """Tạo vùng trồng mới.

    Args:
        payload: Dữ liệu vùng trồng đã được Pydantic validate.
        db: Session SQLAlchemy được cấp và tự đóng bởi dependency ``get_db``.

    Returns:
        Farm: Bản ghi vùng trồng vừa tạo (HTTP 201).

    Raises:
        HTTPException: 500 nếu ghi database thất bại (đã rollback).
    """
    # `model_dump()` chuyển Pydantic model -> dict để map thẳng vào ORM model.
    farm = Farm(**payload.model_dump())
    db.add(farm)

    try:
        db.commit()
    except SQLAlchemyError as exc:
        # Rollback để session không ở trạng thái lỗi cho các request sau.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể lưu vùng trồng vào cơ sở dữ liệu.",
        ) from exc

    # Đọc lại bản ghi để lấy `id` do database sinh ra.
    db.refresh(farm)
    return farm


@router.get(
    "",
    response_model=list[FarmResponse],
    status_code=status.HTTP_200_OK,
    summary="Lấy danh sách vùng trồng",
    description="Trả về toàn bộ vùng trồng, sắp xếp theo `id` tăng dần.",
)
def list_farms(db: Session = Depends(get_db)) -> list[Farm]:
    """Lấy danh sách vùng trồng.

    Args:
        db: Session SQLAlchemy từ dependency ``get_db``.

    Returns:
        list[Farm]: Danh sách vùng trồng (rỗng nếu chưa có dữ liệu).
    """
    # SQLAlchemy 2.0 style: `select()` + `db.scalars()` -> trả về ORM objects.
    return list(db.scalars(select(Farm).order_by(Farm.id)).all())
