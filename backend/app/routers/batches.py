"""Router quản lý lô nông sản (Batch).

Quan hệ: ``Farm 1 ---- N Batch``.

Cung cấp 3 endpoint:
- ``POST /batches``            : tạo lô nông sản (kiểm tra ``farm_id`` tồn tại).
- ``GET  /batches``            : lấy danh sách lô.
- ``GET  /batches/{batch_id}`` : xem chi tiết một lô.
"""

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Batch, Farm
from app.schemas import BatchCreate, BatchResponse

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
        "Nếu `farm_id` không tồn tại, API trả về `404 Not Found`."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "Vùng trồng (farm_id) không tồn tại.",
        },
    },
)
def create_batch(payload: BatchCreate, db: Session = Depends(get_db)) -> Batch:
    """Tạo lô nông sản mới.

    Args:
        payload: Dữ liệu lô đã được Pydantic validate.
        db: Session SQLAlchemy từ dependency ``get_db``.

    Returns:
        Batch: Bản ghi lô vừa tạo (HTTP 201).

    Raises:
        HTTPException: 404 nếu ``farm_id`` không tồn tại;
            500 nếu ghi database thất bại (đã rollback).
    """
    # Bước 1: kiểm tra toàn vẹn tham chiếu - vùng trồng phải tồn tại.
    farm = db.get(Farm, payload.farm_id)
    if farm is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy vùng trồng có id={payload.farm_id}.",
        )

    # Bước 2: lưu lô nông sản.
    batch = Batch(**payload.model_dump())
    db.add(batch)

    try:
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
    db: Session = Depends(get_db),
) -> Batch:
    """Lấy chi tiết một lô nông sản theo ``id``.

    Args:
        batch_id: ID của lô cần tìm.
        db: Session SQLAlchemy từ dependency ``get_db``.

    Returns:
        Batch: Bản ghi lô tương ứng (HTTP 200).

    Raises:
        HTTPException: 404 nếu không tìm thấy lô.
    """
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy lô nông sản có id={batch_id}.",
        )
    return batch
