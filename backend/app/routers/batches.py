"""Router quáº£n lÃ½ lÃ´ nÃ´ng sáº£n (Batch).

Quan há»‡: ``Farm 1 ---- N Batch``.

Cung cáº¥p **Ä‘áº§y Ä‘á»§ CRUD** (hoÃ n thiá»‡n á»Ÿ Sprint 5):

- ``POST   /batches``            : táº¡o lÃ´ nÃ´ng sáº£n (kiá»ƒm tra ``farm_id`` tá»“n táº¡i).
- ``GET    /batches``            : láº¥y danh sÃ¡ch lÃ´.
- ``GET    /batches/{batch_id}`` : xem chi tiáº¿t má»™t lÃ´.
- ``PUT    /batches/{batch_id}`` : cáº­p nháº­t lÃ´ (cÃ³ thá»ƒ Ä‘á»•i sang vÃ¹ng trá»“ng khÃ¡c).
- ``DELETE /batches/{batch_id}`` : xoÃ¡ lÃ´ (chá»‰ admin).

**PhÃ¢n quyá»n (Sprint 4):** ``POST``/``PUT`` dÃ¹ng dependency ``require_farmer``
-> Ä‘Äƒng nháº­p báº±ng role ``farmer`` hoáº·c ``admin`` (401 náº¿u chÆ°a Ä‘Äƒng nháº­p,
403 náº¿u sai vai trÃ²); ``DELETE`` dÃ¹ng ``require_admin`` -> chá»‰ admin. Hai endpoint
``GET`` giá»¯ nguyÃªn nhÆ° trÆ°á»›c (khÃ´ng yÃªu cáº§u Ä‘Äƒng nháº­p) vÃ¬ phá»¥c vá»¥ tra cá»©u nguá»“n
gá»‘c cÃ´ng khai.

**Lá»‹ch sá»­ thao tÃ¡c (Sprint 7):** má»—i láº§n ``POST``/``PUT``/``DELETE`` thÃ nh cÃ´ng,
router ghi thÃªm 1 dÃ²ng vÃ o báº£ng ``audit_logs`` (``entity=batch``) thÃ´ng qua
``record_action()`` - xem ``app/audit.py`` vÃ  endpoint ``GET /audit-logs``.
Log náº±m trong cÃ¹ng transaction vá»›i thao tÃ¡c nÃªn thao tÃ¡c tháº¥t báº¡i
(404/403/500) khÃ´ng Ä‘á»ƒ láº¡i log.
"""

import secrets

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
    Product,
    Unit,
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

READABLE_BATCH_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_unique_batch_code(db: Session) -> str:
    """Sinh mã lô gồm 8 ký tự IN HOA, dễ đọc và không trùng database."""
    for _ in range(20):
        code = "".join(
            secrets.choice(READABLE_BATCH_CODE_ALPHABET)
            for _ in range(8)
        )

        exists = db.scalar(
            select(Batch.id).where(Batch.batch_code == code)
        )

        if exists is None:
            return code

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Không thể sinh mã lô duy nhất. Vui lòng thử lại.",
    )

router = APIRouter(
    prefix="/batches",
    tags=["Batches"],
)


@router.post(
    "",
    response_model=BatchResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Táº¡o lÃ´ nÃ´ng sáº£n",
    description=(
        "Táº¡o má»™t lÃ´ nÃ´ng sáº£n thuá»™c vá» má»™t vÃ¹ng trá»“ng. "
        "Náº¿u `farm_id` khÃ´ng tá»“n táº¡i, API tráº£ vá» `404 Not Found`.\n\n"
        "**PhÃ¢n quyá»n:** Ä‘Äƒng nháº­p vá»›i role `farmer` hoáº·c `admin` (yÃªu cáº§u header "
        "`Authorization: Basic ...`)."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "ChÆ°a Ä‘Äƒng nháº­p.",
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "Vai trÃ² khÃ´ng Ä‘Æ°á»£c phÃ©p.",
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "VÃ¹ng trá»“ng (farm_id) khÃ´ng tá»“n táº¡i.",
        },
    },
)
def create_batch(
    payload: BatchCreate,
    current_user: User = Depends(require_farmer),
    db: Session = Depends(get_db),
) -> Batch:
    """Táº¡o lÃ´ nÃ´ng sáº£n má»›i.

    Args:
        payload: Dá»¯ liá»‡u lÃ´ Ä‘Ã£ Ä‘Æ°á»£c Pydantic validate.
        current_user: TÃ i khoáº£n Ä‘Ã£ Ä‘Äƒng nháº­p (farmer hoáº·c admin) - cÅ©ng lÃ  ngÆ°á»i
            Ä‘Æ°á»£c ghi vÃ o lá»‹ch sá»­ thao tÃ¡c.
        db: Session SQLAlchemy tá»« dependency ``get_db``.

    Returns:
        Batch: Báº£n ghi lÃ´ vá»«a táº¡o (HTTP 201).

    Raises:
        HTTPException: 401/403 náº¿u chÆ°a Ä‘Äƒng nháº­p hoáº·c sai vai trÃ²;
            404 náº¿u ``farm_id`` khÃ´ng tá»“n táº¡i;
            500 náº¿u ghi database tháº¥t báº¡i (Ä‘Ã£ rollback).
    """
    # BÆ°á»›c 1: kiá»ƒm tra toÃ n váº¹n tham chiáº¿u - vÃ¹ng trá»“ng pháº£i tá»“n táº¡i.
    farm = db.get(Farm, payload.farm_id)
    if farm is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"KhÃ´ng tÃ¬m tháº¥y vÃ¹ng trá»“ng cÃ³ id={payload.farm_id}.",
        )

    if current_user.organization_id is not None and farm.organization_id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Báº¡n khÃ´ng cÃ³ quyá»n táº¡o lÃ´ nÃ´ng sáº£n cho vÃ¹ng trá»“ng cá»§a tá»• chá»©c khÃ¡c.",
        )

    # BÆ°á»›c 2: lÆ°u lÃ´ nÃ´ng sáº£n.
    batch = Batch(**payload.model_dump(), current_org_id=farm.organization_id)
    db.add(batch)

    try:
        # `flush()` Ä‘á»ƒ database sinh `id` cho lÃ´ - audit log cáº§n ID tháº­t.
        db.flush()
        # Sprint 7: ghi lá»‹ch sá»­ "ai Ä‘Ã£ táº¡o lÃ´ nÃ´ng sáº£n nÃ o" (chÆ°a commit vá»™i).
        record_action(db, current_user, ACTION_CREATE, ENTITY_BATCH, batch.id)
        # S-11 & S-12: Tá»± Ä‘á»™ng ghi event khá»Ÿi táº¡o lÃ´ vÃ o batch_events (append-only hash chain)
        record_batch_event(
            db=db,
            batch_id=batch.id,
            event_type="BATCH_CREATED",
            event_data=f"Khá»Ÿi táº¡o lÃ´ nÃ´ng sáº£n: {batch.product_name}",
            user_id=current_user.id,
        )
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="KhÃ´ng thá»ƒ lÆ°u lÃ´ nÃ´ng sáº£n vÃ o cÆ¡ sá»Ÿ dá»¯ liá»‡u.",
        ) from exc

    db.refresh(batch)
    return batch


@router.get(
    "",
    response_model=list[BatchResponse],
    status_code=status.HTTP_200_OK,
    summary="Láº¥y danh sÃ¡ch lÃ´ nÃ´ng sáº£n",
    description="Tráº£ vá» toÃ n bá»™ lÃ´ nÃ´ng sáº£n, sáº¯p xáº¿p theo `id` tÄƒng dáº§n.",
)
def list_batches(db: Session = Depends(get_db)) -> list[Batch]:
    """Láº¥y danh sÃ¡ch lÃ´ nÃ´ng sáº£n.

    Args:
        db: Session SQLAlchemy tá»« dependency ``get_db``.

    Returns:
        list[Batch]: Danh sÃ¡ch lÃ´ (rá»—ng náº¿u chÆ°a cÃ³ dá»¯ liá»‡u).
    """
    return list(db.scalars(select(Batch).order_by(Batch.id)).all())


@router.get(
    "/{batch_id}",
    response_model=BatchDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Xem chi tiáº¿t má»™t lÃ´ nÃ´ng sáº£n",
    description=(
        "Tráº£ vá» thÃ´ng tin chi tiáº¿t cá»§a lÃ´ theo `id` (kÃ¨m lÃ´ máº¹ vÃ  danh sÃ¡ch lÃ´ con trá»±c tiáº¿p). "
        "Tráº£ `404` náº¿u khÃ´ng tá»“n táº¡i."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "KhÃ´ng tÃ¬m tháº¥y lÃ´ nÃ´ng sáº£n.",
        },
    },
)
def get_batch(
    batch_id: int = Path(..., ge=1, description="ID lÃ´ nÃ´ng sáº£n cáº§n xem."),
    db: Session = Depends(get_db),
) -> BatchDetailResponse:
    """Láº¥y chi tiáº¿t má»™t lÃ´ nÃ´ng sáº£n theo ``id`` (phá»¥c vá»¥ S-25).

    Args:
        batch_id: ID cá»§a lÃ´ cáº§n tÃ¬m.
        db: Session SQLAlchemy tá»« dependency ``get_db``.

    Returns:
        BatchDetailResponse: Chi tiáº¿t lÃ´ nÃ´ng sáº£n bao gá»“m lÃ´ máº¹ vÃ  cÃ¡c lÃ´ con trá»±c tiáº¿p.

    Raises:
        HTTPException: 404 náº¿u khÃ´ng tÃ¬m tháº¥y lÃ´.
    """
    batch = get_batch_with_direct_relations(db, batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"KhÃ´ng tÃ¬m tháº¥y lÃ´ nÃ´ng sáº£n cÃ³ id={batch_id}.",
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
    summary="[T-58] Truy váº¥n tá»•ng há»£p chi tiáº¿t lÃ´ kÃ¨m lÃ´ máº¹ vÃ  lÃ´ con trá»±c tiáº¿p",
    description=(
        "API nháº­n `batch_id` vÃ  tráº£ vá» thÃ´ng tin chi tiáº¿t cá»§a lÃ´, kÃ¨m duy nháº¥t lÃ´ máº¹ trá»±c tiáº¿p "
        "(parent = null náº¿u khÃ´ng cÃ³) vÃ  danh sÃ¡ch cÃ¡c lÃ´ con trá»±c tiáº¿p (children = [] náº¿u khÃ´ng cÃ³). "
        "KhÃ´ng láº¥y toÃ n bá»™ tá»• tiÃªn/háº­u duá»‡ vÃ  tá»‘i Æ°u SQL trÃ¡nh N+1 query."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "KhÃ´ng tÃ¬m tháº¥y lÃ´ nÃ´ng sáº£n.",
        },
    },
)
def get_batch_tree(
    batch_id: int = Path(..., ge=1, description="ID lÃ´ nÃ´ng sáº£n cáº§n xem cÃ¢y quan há»‡."),
    db: Session = Depends(get_db),
) -> dict:
    """Truy váº¥n tá»•ng há»£p chi tiáº¿t lÃ´ kÃ¨m lÃ´ máº¹ vÃ  cÃ¡c lÃ´ con trá»±c tiáº¿p (T-58).

    Args:
        batch_id: ID cá»§a lÃ´ cáº§n xem.
        db: Session SQLAlchemy tá»« dependency ``get_db``.

    Returns:
        dict: Cáº¥u trÃºc JSON chuáº©n T-58 gá»“m 3 khá»‘i {batch, parent, children}.

    Raises:
        HTTPException: 404 náº¿u khÃ´ng tÃ¬m tháº¥y lÃ´.
    """
    batch = get_batch_with_direct_relations(db, batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"KhÃ´ng tÃ¬m tháº¥y lÃ´ nÃ´ng sáº£n cÃ³ id={batch_id}.",
        )

    return build_batch_tree_response(batch)


@router.get(
    "/{batch_id}/ancestors",
    response_model=BatchAncestorsResponse,
    status_code=status.HTTP_200_OK,
    summary="[T-59] Láº¥y danh sÃ¡ch cÃ¡c lÃ´ tá»• tiÃªn cá»§a má»™t lÃ´ nÃ´ng sáº£n",
    description=(
        "API truy váº¿t ngÆ°á»£c tá»« `parent_id` cá»§a lÃ´ hiá»‡n táº¡i lÃªn cÃ¡c tháº¿ há»‡ trÆ°á»›c "
        "(Máº¹ -> BÃ  -> Cá»‘ -> LÃ´ gá»‘c). Tráº£ `404` náº¿u lÃ´ khÃ´ng tá»“n táº¡i."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "KhÃ´ng tÃ¬m tháº¥y lÃ´ nÃ´ng sáº£n.",
        },
    },
)
def get_batch_ancestors_route(
    batch_id: int = Path(..., ge=1, description="ID lÃ´ nÃ´ng sáº£n cáº§n truy váº¿t tá»• tiÃªn."),
    db: Session = Depends(get_db),
) -> dict:
    """Láº¥y danh sÃ¡ch tá»• tiÃªn cá»§a má»™t lÃ´ nÃ´ng sáº£n theo quan há»‡ database (T-59).

    Args:
        batch_id: ID cá»§a lÃ´ cáº§n xem danh sÃ¡ch tá»• tiÃªn.
        db: Session SQLAlchemy tá»« dependency ``get_db``.

    Returns:
        dict: Cáº¥u trÃºc JSON chá»©a batch_id vÃ  danh sÃ¡ch ancestors.

    Raises:
        HTTPException: 404 náº¿u khÃ´ng tÃ¬m tháº¥y lÃ´.
    """
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"KhÃ´ng tÃ¬m tháº¥y lÃ´ nÃ´ng sáº£n cÃ³ id={batch_id}.",
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
    summary="Cáº­p nháº­t lÃ´ nÃ´ng sáº£n",
    description=(
        "Cáº­p nháº­t (thay tháº¿) thÃ´ng tin lÃ´ theo `id`. Client gá»­i Ä‘áº§y Ä‘á»§ cÃ¡c trÆ°á»ng "
        "nhÆ° khi táº¡o má»›i; `farm_id` má»›i cÅ©ng pháº£i tá»“n táº¡i. Tráº£ `404` náº¿u lÃ´ "
        "**hoáº·c** vÃ¹ng trá»“ng khÃ´ng tá»“n táº¡i.\n\n"
        "**PhÃ¢n quyá»n:** Ä‘Äƒng nháº­p vá»›i role `farmer` hoáº·c `admin`."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "ChÆ°a Ä‘Äƒng nháº­p."},
        status.HTTP_403_FORBIDDEN: {"description": "Vai trÃ² khÃ´ng Ä‘Æ°á»£c phÃ©p."},
        status.HTTP_404_NOT_FOUND: {
            "description": "KhÃ´ng tÃ¬m tháº¥y lÃ´ nÃ´ng sáº£n hoáº·c vÃ¹ng trá»“ng (farm_id).",
        },
    },
)
def update_batch(
    payload: BatchUpdate,
    batch_id: int = Path(..., ge=1, description="ID lÃ´ nÃ´ng sáº£n cáº§n sá»­a."),
    current_user: User = Depends(require_farmer),
    db: Session = Depends(get_db),
) -> Batch:
    """Cáº­p nháº­t thÃ´ng tin lÃ´ nÃ´ng sáº£n theo ``id``.

    Args:
        payload: Dá»¯ liá»‡u má»›i Ä‘Ã£ Ä‘Æ°á»£c Pydantic validate (Ä‘á»§ 4 trÆ°á»ng).
        batch_id: ID lÃ´ cáº§n sá»­a.
        current_user: TÃ i khoáº£n Ä‘Ã£ Ä‘Äƒng nháº­p (farmer hoáº·c admin) - cÅ©ng lÃ  ngÆ°á»i
            Ä‘Æ°á»£c ghi vÃ o lá»‹ch sá»­ thao tÃ¡c.
        db: Session SQLAlchemy tá»« dependency ``get_db``.

    Returns:
        Batch: Báº£n ghi lÃ´ sau khi cáº­p nháº­t (HTTP 200).

    Raises:
        HTTPException: 401/403 náº¿u chÆ°a Ä‘Äƒng nháº­p hoáº·c sai vai trÃ²;
            404 náº¿u khÃ´ng tÃ¬m tháº¥y lÃ´ hoáº·c ``farm_id`` má»›i;
            500 náº¿u ghi database tháº¥t báº¡i (Ä‘Ã£ rollback).
    """
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"KhÃ´ng tÃ¬m tháº¥y lÃ´ nÃ´ng sáº£n cÃ³ id={batch_id}.",
        )

    current_farm = db.get(Farm, batch.farm_id)
    if (
        current_farm
        and current_user.organization_id is not None
        and current_farm.organization_id != current_user.organization_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Báº¡n khÃ´ng cÃ³ quyá»n sá»­a lÃ´ nÃ´ng sáº£n cá»§a tá»• chá»©c khÃ¡c.",
        )

    # Kiá»ƒm tra láº¡i toÃ n váº¹n tham chiáº¿u: vÃ¹ng trá»“ng (má»›i) pháº£i tá»“n táº¡i.
    farm = db.get(Farm, payload.farm_id)
    if farm is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"KhÃ´ng tÃ¬m tháº¥y vÃ¹ng trá»“ng cÃ³ id={payload.farm_id}.",
        )

    if current_user.organization_id is not None and farm.organization_id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Báº¡n khÃ´ng cÃ³ quyá»n chuyá»ƒn lÃ´ nÃ´ng sáº£n sang vÃ¹ng trá»“ng cá»§a tá»• chá»©c khÃ¡c.",
        )

    for field, value in payload.model_dump().items():
        setattr(batch, field, value)

    try:
        # Sprint 7: ghi lá»‹ch sá»­ "ai Ä‘Ã£ sá»­a lÃ´ nÃ´ng sáº£n nÃ o" trong cÃ¹ng transaction.
        record_action(db, current_user, ACTION_UPDATE, ENTITY_BATCH, batch_id)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="KhÃ´ng thá»ƒ cáº­p nháº­t lÃ´ nÃ´ng sáº£n trong cÆ¡ sá»Ÿ dá»¯ liá»‡u.",
        ) from exc

    db.refresh(batch)
    return batch


@router.delete(
    "/{batch_id}",
    response_model=DeleteResponse,
    status_code=status.HTTP_200_OK,
    summary="XoÃ¡ lÃ´ nÃ´ng sáº£n (chá»‰ admin)",
    description=(
        "XoÃ¡ má»™t lÃ´ nÃ´ng sáº£n theo `id`.\n\n"
        "**PhÃ¢n quyá»n:** chá»‰ `role = admin` Ä‘Æ°á»£c xoÃ¡ (dÃ¹ng `require_admin`). "
        "Farmer gá»i sáº½ nháº­n `403 Forbidden` - giao diá»‡n cÅ©ng áº©n nÃºt XoÃ¡ vá»›i farmer.\n\n"
        "**Lá»‹ch sá»­ thao tÃ¡c:** ghi 1 dÃ²ng log cho lÃ´ vá»«a xoÃ¡ "
        "(`action=delete`, `entity=batch`)."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "ChÆ°a Ä‘Äƒng nháº­p."},
        status.HTTP_403_FORBIDDEN: {"description": "ÄÃ£ Ä‘Äƒng nháº­p nhÆ°ng khÃ´ng pháº£i admin."},
        status.HTTP_404_NOT_FOUND: {"description": "KhÃ´ng tÃ¬m tháº¥y lÃ´ nÃ´ng sáº£n."},
    },
)
def delete_batch(
    batch_id: int = Path(..., ge=1, description="ID lÃ´ nÃ´ng sáº£n cáº§n xoÃ¡."),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> DeleteResponse:
    """XoÃ¡ má»™t lÃ´ nÃ´ng sáº£n (chá»‰ admin).

    Args:
        batch_id: ID lÃ´ cáº§n xoÃ¡.
        current_user: TÃ i khoáº£n admin Ä‘Ã£ Ä‘Æ°á»£c ``require_admin`` kiá»ƒm tra quyá»n -
            cÅ©ng lÃ  ngÆ°á»i Ä‘Æ°á»£c ghi vÃ o lá»‹ch sá»­ thao tÃ¡c.
        db: Session SQLAlchemy tá»« dependency ``get_db``.

    Returns:
        DeleteResponse: ThÃ´ng bÃ¡o káº¿t quáº£ xoÃ¡ (HTTP 200).

    Raises:
        HTTPException: 401 náº¿u chÆ°a Ä‘Äƒng nháº­p; 403 náº¿u khÃ´ng pháº£i admin;
            404 náº¿u khÃ´ng tÃ¬m tháº¥y lÃ´;
            500 náº¿u xoÃ¡ trong database tháº¥t báº¡i (Ä‘Ã£ rollback).
    """
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"KhÃ´ng tÃ¬m tháº¥y lÃ´ nÃ´ng sáº£n cÃ³ id={batch_id}.",
        )

    current_farm = db.get(Farm, batch.farm_id)
    if (
        current_farm
        and current_user.organization_id is not None
        and current_farm.organization_id != current_user.organization_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Báº¡n khÃ´ng cÃ³ quyá»n xoÃ¡ lÃ´ nÃ´ng sáº£n cá»§a tá»• chá»©c khÃ¡c.",
        )

    # LÆ°u láº¡i tÃªn sáº£n pháº©m Ä‘á»ƒ viáº¿t thÃ´ng bÃ¡o (sau khi xoÃ¡ khÃ´ng Ä‘á»c Ä‘Æ°á»£c ná»¯a).
    product_name = batch.product_name

    db.delete(batch)
    try:
        # Sprint 7: ghi lá»‹ch sá»­ "ai Ä‘Ã£ xoÃ¡ lÃ´ nÃ´ng sáº£n nÃ o" trong cÃ¹ng transaction.
        record_action(db, current_user, ACTION_DELETE, ENTITY_BATCH, batch_id)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="KhÃ´ng thá»ƒ xoÃ¡ lÃ´ nÃ´ng sáº£n khá»i cÆ¡ sá»Ÿ dá»¯ liá»‡u.",
        ) from exc

    return DeleteResponse(
        message=f"ÄÃ£ xoÃ¡ lÃ´ nÃ´ng sáº£n #{batch_id} ({product_name}).",
        deleted_id=batch_id,
        # XoÃ¡ lÃ´ khÃ´ng kÃ©o theo báº£n ghi nÃ o khÃ¡c -> null.
        deleted_batches=None,
    )


