from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record_action
from app.database import get_db
from app.models import (
    ACTION_CREATE,
    ACTION_DELETE,
    ACTION_UPDATE,
    ENTITY_PRODUCT,
    ENTITY_UNIT,
    Batch,
    Product,
    Unit,
    User,
)
from app.schemas import (
    DeleteResponse,
    ProductCreate,
    ProductResponse,
    ProductUpdate,
    UnitCreate,
    UnitResponse,
    UnitUpdate,
)
from app.security import require_admin, require_farmer


router = APIRouter(tags=["catalogs"])


# ============================================================
# PRODUCT - DANH MỤC SẢN PHẨM
# ============================================================

@router.get(
    "/products",
    response_model=list[ProductResponse],
)
def list_products(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_farmer),
):
    """Danh sách sản phẩm thuộc tổ chức hiện tại."""
    products = db.scalars(
        select(Product)
        .where(Product.organization_id == current_user.organization_id)
        .order_by(Product.name)
    ).all()

    return products


@router.post(
    "/products",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_product(
    payload: ProductCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Tạo sản phẩm mới."""
    existing = db.scalar(
        select(Product).where(
            Product.organization_id == current_user.organization_id,
            Product.code == payload.code,
        )
    )

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Mã sản phẩm đã tồn tại.",
        )

    product = Product(
        organization_id=current_user.organization_id,
        name=payload.name,
        code=payload.code,
        active=payload.active,
    )

    db.add(product)
    db.flush()

    record_action(
        db,
        current_user,
        ACTION_CREATE,
        ENTITY_PRODUCT,
        product.id,
    )

    db.commit()
    db.refresh(product)

    return product


@router.put(
    "/products/{product_id}",
    response_model=ProductResponse,
)
def update_product(
    product_id: int,
    payload: ProductUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Cập nhật sản phẩm."""
    product = db.scalar(
        select(Product).where(
            Product.id == product_id,
            Product.organization_id == current_user.organization_id,
        )
    )

    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy sản phẩm.",
        )

    duplicate = db.scalar(
        select(Product).where(
            Product.organization_id == current_user.organization_id,
            Product.code == payload.code,
            Product.id != product_id,
        )
    )

    if duplicate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Mã sản phẩm đã tồn tại.",
        )

    product.name = payload.name
    product.code = payload.code
    product.active = payload.active

    record_action(
        db,
        current_user,
        ACTION_UPDATE,
        ENTITY_PRODUCT,
        product.id,
    )

    db.commit()
    db.refresh(product)

    return product


@router.delete(
    "/products/{product_id}",
    response_model=DeleteResponse,
)
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Xóa sản phẩm nếu chưa được sử dụng bởi lô."""
    product = db.scalar(
        select(Product).where(
            Product.id == product_id,
            Product.organization_id == current_user.organization_id,
        )
    )

    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy sản phẩm.",
        )

    used = db.scalar(
        select(Batch.id)
        .where(Batch.product_id == product_id)
        .limit(1)
    )

    if used is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Không thể xóa sản phẩm vì sản phẩm đã được sử dụng trong lô.",
        )

    db.delete(product)

    record_action(
        db,
        current_user,
        ACTION_DELETE,
        ENTITY_PRODUCT,
        product.id,
    )

    db.commit()

    return DeleteResponse(
        message=f"Đã xóa sản phẩm #{product_id}.",
        deleted_id=product_id,
        deleted_batches=None,
    )


# ============================================================
# UNIT - DANH MỤC ĐƠN VỊ TÍNH
# ============================================================

@router.get(
    "/units",
    response_model=list[UnitResponse],
)
def list_units(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_farmer),
):
    """Danh sách đơn vị tính thuộc tổ chức hiện tại."""
    units = db.scalars(
        select(Unit)
        .where(Unit.organization_id == current_user.organization_id)
        .order_by(Unit.name)
    ).all()

    return units


@router.post(
    "/units",
    response_model=UnitResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_unit(
    payload: UnitCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Tạo đơn vị tính mới."""
    existing = db.scalar(
        select(Unit).where(
            Unit.organization_id == current_user.organization_id,
            Unit.symbol == payload.symbol,
        )
    )

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ký hiệu đơn vị tính đã tồn tại.",
        )

    unit = Unit(
        organization_id=current_user.organization_id,
        name=payload.name,
        symbol=payload.symbol,
        active=payload.active,
    )

    db.add(unit)
    db.flush()

    record_action(
        db,
        current_user,
        ACTION_CREATE,
        ENTITY_UNIT,
        unit.id,
    )

    db.commit()
    db.refresh(unit)

    return unit


@router.put(
    "/units/{unit_id}",
    response_model=UnitResponse,
)
def update_unit(
    unit_id: int,
    payload: UnitUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Cập nhật đơn vị tính."""
    unit = db.scalar(
        select(Unit).where(
            Unit.id == unit_id,
            Unit.organization_id == current_user.organization_id,
        )
    )

    if unit is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy đơn vị tính.",
        )

    duplicate = db.scalar(
        select(Unit).where(
            Unit.organization_id == current_user.organization_id,
            Unit.symbol == payload.symbol,
            Unit.id != unit_id,
        )
    )

    if duplicate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ký hiệu đơn vị tính đã tồn tại.",
        )

    unit.name = payload.name
    unit.symbol = payload.symbol
    unit.active = payload.active

    record_action(
        db,
        current_user,
        ACTION_UPDATE,
        ENTITY_UNIT,
        unit.id,
    )

    db.commit()
    db.refresh(unit)

    return unit


@router.delete(
    "/units/{unit_id}",
    response_model=DeleteResponse,
)
def delete_unit(
    unit_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Xóa đơn vị tính nếu chưa được sử dụng bởi lô."""
    unit = db.scalar(
        select(Unit).where(
            Unit.id == unit_id,
            Unit.organization_id == current_user.organization_id,
        )
    )

    if unit is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy đơn vị tính.",
        )

    used = db.scalar(
        select(Batch.id)
        .where(Batch.unit_id == unit_id)
        .limit(1)
    )

    if used is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Không thể xóa đơn vị tính vì đơn vị đã được sử dụng trong lô.",
        )

    db.delete(unit)

    record_action(
        db,
        current_user,
        ACTION_DELETE,
        ENTITY_UNIT,
        unit.id,
    )

    db.commit()

    return DeleteResponse(
        message=f"Đã xóa đơn vị tính #{unit_id}.",
        deleted_id=unit_id,
        deleted_batches=None,
    )
