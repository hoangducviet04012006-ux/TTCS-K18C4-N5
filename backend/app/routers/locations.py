"""S-30: org-scoped stores, stock allocation and internal location transfer."""

from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Batch, BatchRelation, User, ACTION_CREATE, ACTION_UPDATE, ENTITY_BATCH
from app.location_models import Location
from app.schemas import BatchResponse
from app.schemas_locations import LocationCreate, LocationUpdate, LocationOut, TransferLocation, StoreAllocation
from app.security import get_current_user
from app.services.rbac import check_action_permission
from app.services.locations import require_schema, begin_write, set_location, hydrate, location_map
from app.services.recall import ensure_not_recalled
from app.hash_chain import record_event
from app.audit import record_action
from app.services.traceability import clear_trace_cache

router = APIRouter(tags=["Locations"])


def manager(user):
    check_action_permission(user, "LOCATION_MANAGE")
    if user.organization_id is None:
        raise HTTPException(403, "Tài khoản chưa có tổ chức.")


def own_location(db, user, location_id, active=False):
    place = db.get(Location, location_id)
    if place is None:
        raise HTTPException(404, "Không tìm thấy địa điểm.")
    if place.organization_id != user.organization_id:
        raise HTTPException(403, "Địa điểm không thuộc tổ chức của bạn.")
    if active and not place.is_active:
        raise HTTPException(409, "Địa điểm đã ngừng hoạt động.")
    return place


def physical_batch(db, user, batch_id):
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(404, "Không tìm thấy lô.")
    if batch.current_org_id != user.organization_id:
        raise HTTPException(403, "Lô không thuộc tổ chức đang giữ của bạn.")
    ensure_not_recalled(db, batch.id)
    if batch.status not in ("ACTIVE", "SPLIT") or batch.remaining_quantity is None or batch.remaining_quantity <= 0:
        raise HTTPException(409, "Lô không còn lượng khả dụng hoặc trạng thái không cho phép.")
    if batch.pending_handover is not None:
        raise HTTPException(409, "Lô đang chờ bàn giao.")
    return batch


@router.get("/phase-c/capabilities")
def capabilities(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.locations import probe_schema

    return {
        "locations_ready": probe_schema(db),
        "location_manage": check_action_permission(user, "LOCATION_MANAGE", raise_exception=False)
        and user.organization_id is not None,
        "product_import": check_action_permission(user, "PRODUCT_CREATE", raise_exception=False),
        "plot_import": check_action_permission(user, "FARM_MANAGE", raise_exception=False)
        and user.organization_id is not None,
    }


@router.get("/organizations/locations", response_model=list[LocationOut])
def list_locations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    manager(user)
    require_schema(db)
    return list(db.scalars(select(Location).where(Location.organization_id == user.organization_id).order_by(Location.id)))


@router.post("/organizations/locations", response_model=LocationOut, status_code=201)
def create_location(payload: LocationCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    manager(user)
    begin_write(db)
    place = Location(**payload.model_dump(), organization_id=user.organization_id)
    place.code = place.code.upper()
    db.add(place)
    try:
        db.flush()
        record_action(db, user, ACTION_CREATE, "location", place.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Mã địa điểm đã tồn tại trong tổ chức.")
    db.refresh(place)
    return place


@router.patch("/organizations/locations/{location_id}", response_model=LocationOut)
def update_location(
    location_id: int, payload: LocationUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    manager(user)
    begin_write(db)
    place = own_location(db, user, location_id)
    changes = payload.model_dump(exclude_unset=True)
    if any(value is None for value in changes.values()):
        raise HTTPException(422, "Trường cập nhật không được null.")
    if changes.get("is_active") is False and db.scalar(
        text("SELECT count(*) FROM batches WHERE location_id=:id AND remaining_quantity>0"), {"id": location_id}
    ):
        raise HTTPException(409, "Địa điểm còn lô tồn kho, chưa thể ngừng hoạt động.")
    for key, value in changes.items():
        setattr(place, key, value)
    record_action(db, user, ACTION_UPDATE, "location", place.id)
    db.commit()
    db.refresh(place)
    clear_trace_cache()
    return place


@router.post("/batches/{batch_id}/transfer-location", response_model=BatchResponse)
def transfer_location(
    batch_id: int, payload: TransferLocation, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    manager(user)
    check_action_permission(user, "BATCH_UPDATE")
    begin_write(db)
    batch = physical_batch(db, user, batch_id)
    place = own_location(db, user, payload.location_id, active=True)
    before = location_map(db, [batch.id]).get(batch.id, {}).get("id")
    if before == place.id:
        return hydrate(db, [batch])[0]
    set_location(db, batch.id, place.id)
    record_event(
        db=db,
        batch_id=batch.id,
        event_type="INTERNAL_TRANSFER",
        payload={
            "from_location_id": before,
            "location_id": place.id,
            "location_code": place.code,
            "location_name": place.name,
            "address": place.address,
        },
        org_id=user.organization_id,
        user_id=user.id,
    )
    record_action(db, user, ACTION_UPDATE, ENTITY_BATCH, batch.id,
                  operation="transfer_location", location=location_map(db, [batch.id]).get(batch.id))
    db.commit()
    clear_trace_cache()
    return hydrate(db, [batch])[0]


@router.post("/batches/{batch_id}/allocate-stores")
def allocate_stores(
    batch_id: int, payload: StoreAllocation, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    manager(user)
    check_action_permission(user, "SPLIT")
    begin_write(db)
    parent = physical_batch(db, user, batch_id)
    places = [own_location(db, user, item.location_id, active=True) for item in payload.items]
    total = sum((item.quantity for item in payload.items), Decimal("0"))
    if total != parent.remaining_quantity:
        raise HTTPException(422, "Tổng lượng phân bổ phải bằng toàn bộ khối lượng còn lại.")
    children = []
    for item, place in zip(payload.items, places):
        child = Batch(
            plot_id=parent.plot_id,
            farm_id=parent.farm_id,
            product_id=parent.product_id,
            product_name=parent.product_name,
            harvest_date=parent.harvest_date,
            initial_quantity=item.quantity,
            remaining_quantity=item.quantity,
            current_org_id=parent.current_org_id,
            status="ACTIVE",
        )
        db.add(child)
        db.flush()
        set_location(db, child.id, place.id)
        db.add(
            BatchRelation(
                parent_batch_id=parent.id, child_batch_id=child.id, transferred_quantity=item.quantity, relation_type="SPLIT"
            )
        )
        record_event(
            db=db,
            batch_id=child.id,
            event_type="GENESIS_SPLIT",
            payload={
                "parent_batch_id": parent.id,
                "parent_batch_code": parent.code,
                "quantity": str(item.quantity),
                "location_id": place.id,
                "location_code": place.code,
            },
            org_id=user.organization_id,
            user_id=user.id,
        )
        record_action(db, user, ACTION_CREATE, ENTITY_BATCH, child.id,
                      operation="allocate_store", batch_ids=[parent.id, child.id],
                      location=location_map(db, [child.id]).get(child.id))
        children.append(child)
    parent.remaining_quantity = Decimal("0")
    parent.quantity = 0.0
    parent.status = "SPLIT"
    db.flush()  # persist lifecycle state before record_event's synchronizing lock UPDATE
    record_event(
        db=db,
        batch_id=parent.id,
        event_type="SPLIT",
        payload={
            "child_batch_codes": [c.code for c in children],
            "child_quantities": [str(i.quantity) for i in payload.items],
            "total_split_quantity": str(total),
            "store_location_ids": [p.id for p in places],
        },
        org_id=user.organization_id,
        user_id=user.id,
    )
    record_action(db, user, ACTION_UPDATE, ENTITY_BATCH, parent.id, operation="allocate_store")
    db.commit()
    clear_trace_cache()
    hydrate(db, [parent, *children])
    return {
        "parent_batch": BatchResponse.model_validate(parent),
        "child_batches": [BatchResponse.model_validate(c) for c in children],
        "message": "Đã phân bổ toàn bộ lượng còn lại cho các cửa hàng.",
    }
