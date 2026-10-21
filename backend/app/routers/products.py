"""Router quản lý danh mục Sản phẩm & Đơn vị tính (T-16, T-17).

- GET  /products: Mọi tổ chức / người dùng đều có thể xem danh mục dùng chung.
- POST /products: Chỉ vai trò ADMIN mới được tạo. Farmer gọi vào trả về HTTP 403 Forbidden.
- Kiểm tra trùng tên sản phẩm: trả về HTTP 400 kèm thông báo chi tiết.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.audit import record_action
from app.models import Product, User
from app.schemas import ProductCreate, ProductResponse
from app.security import require_admin, get_current_user
from app.schemas_trips import ProductTemperaturePolicy
from app.trip_models import ProductTemperatureSetting
from app.services.rbac import check_action_permission

router = APIRouter(
    prefix="/products",
    tags=["Products"],
)


@router.get(
    "",
    response_model=list[ProductResponse],
    status_code=status.HTTP_200_OK,
    summary="Lấy danh mục sản phẩm (T-17)",
    description="Cho phép mọi tổ chức xem danh mục sản phẩm dùng chung toàn hệ thống.",
)
def list_products(db: Session = Depends(get_db)) -> list[Product]:
    """Lấy danh sách tất cả sản phẩm dùng chung toàn hệ thống."""
    return list(db.scalars(select(Product).order_by(Product.id.asc())).all())


@router.post(
    "",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Tạo sản phẩm mới (T-17 - Chỉ Admin)",
    description=(
        "Chỉ Quản trị viên (`ADMIN`) mới được phép tạo sản phẩm mới. "
        "Tài khoản nông dân/vùng trồng gọi vào sẽ bị từ chối với HTTP 403 Forbidden. "
        "Kiểm tra trùng tên sản phẩm trả về HTTP 400."
    ),
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "Tên sản phẩm bị trùng lặp.",
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "Chỉ Quản trị viên (ADMIN) mới có quyền tạo sản phẩm.",
        },
    },
)
def create_product(
    payload: ProductCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Product:
    """Tạo sản phẩm mới dùng chung toàn hệ thống."""
    check_action_permission(current_user, "PRODUCT_CREATE")
    clean_name = payload.name.strip()

    # Kiểm tra trùng tên sản phẩm (không phân biệt hoa/thường)
    existing = db.scalar(
        select(Product).where(Product.name.ilike(clean_name))
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Sản phẩm với tên '{clean_name}' đã tồn tại trong hệ thống.",
        )

    product = Product(
        name=clean_name,
        unit=payload.unit,
    )
    db.add(product)
    db.flush()
    record_action(db, current_user, "create", "product", product.id)
    db.commit()
    db.refresh(product)
    return product


@router.get("/{product_id}/temperature-policy")
def get_temperature_policy(product_id: int, user: User = Depends(get_current_user),
                           db: Session = Depends(get_db)):
    if db.get(Product, product_id) is None:
        raise HTTPException(404, "Không tìm thấy sản phẩm")
    policy = db.get(ProductTemperatureSetting, product_id)
    return {"product_id": product_id, "configured": policy is not None,
            "policy": ProductTemperaturePolicy.model_validate(policy).model_dump() if policy else None,
            "message": "Đã cấu hình" if policy else "Chưa cấu hình — Không thể đánh giá"}


@router.put("/{product_id}/temperature-policy")
def update_temperature_policy(product_id: int, payload: ProductTemperaturePolicy,
                              user: User = Depends(require_admin), db: Session = Depends(get_db)):
    check_action_permission(user, "PRODUCT_CREATE")
    if db.get(Product, product_id) is None:
        raise HTTPException(404, "Không tìm thấy sản phẩm")
    policy = db.get(ProductTemperatureSetting, product_id)
    if policy is None:
        policy = ProductTemperatureSetting(product_id=product_id, **payload.model_dump())
        db.add(policy)
    else:
        for key, value in payload.model_dump().items():
            setattr(policy, key, value)
    record_action(db, user, "update", "product", product_id, operation="TEMPERATURE_POLICY")
    db.commit()
    return {"product_id": product_id, "configured": True, "policy": payload.model_dump()}
