"""Repeatable, non-destructive demo generated through existing business operations.

PowerShell: $env:DEMO_PASSWORD='a local secret'; python -m app.seeds.seed_demo
"""
import os
import secrets
from pathlib import Path
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal, init_db
from app.hash_chain import EVENT_TIME, verify_batch_chain
from app.models import Batch, BatchRelation, Farm, Handover, Organization, Product, User
from app.routers.batches import create_batch, merge_batches, split_batch
from app.routers.handovers import accept_handover, create_handover, reject_handover
from app.schemas import BatchCreate, BatchMergeRequest, BatchSplitRequest, HandoverCreate, HandoverRejectRequest
from app.security import hash_password

PREFIX = "DEMO26"


def _seed_identities(db, password):
    orgs, actors = [], []
    for suffix, name, role in [("farm", "Hợp tác xã canh tác", "farmer"),
                               ("packing", "Trung tâm đóng gói", "processor"),
                               ("distribution", "Doanh nghiệp phân phối", "distributor"),
                               ("admin", "Quản trị hệ thống", "system_admin")]:
        code = f"{PREFIX}-{suffix}"
        org = db.scalar(select(Organization).where(Organization.code == code))
        if org is None:
            org = Organization(code=code, name=f"[DEMO26] {name}", description="Demo dataset v1; not real records")
            db.add(org)
            db.flush()
        elif org.description != "Demo dataset v1; not real records":
            raise RuntimeError(f"Trùng mã tổ chức {code}; không ghi đè dữ liệu.")
        username = f"demo_{suffix}"
        user = db.scalar(select(User).where(User.username == username))
        if user is None:
            user = User(username=username, email=f"{username}@demo.local", organization_id=org.id,
                        role=role, password=hash_password(password))
            db.add(user)
            db.flush()
        elif user.organization_id != org.id:
            raise RuntimeError(f"Trùng tài khoản {username}; không ghi đè.")
        orgs.append(org)
        actors.append(user)
    product = db.scalar(select(Product).where(Product.name == "[DEMO26] Xoài cát Chu"))
    if product is None:
        product = Product(name="[DEMO26] Xoài cát Chu", unit="kg")
        db.add(product)
        db.flush()
    elif product.unit != "kg":
        raise RuntimeError("Sản phẩm demo bị thay đổi; không ghi đè.")
    for name, unit in [("[DEMO26] Gạo ST25", "tấn"), ("[DEMO26] Thanh long", "thùng")]:
        if db.scalar(select(Product.id).where(Product.name == name)) is None:
            db.add(Product(name=name, unit=unit))
    db.commit()

    return orgs, actors, product


def _seed_roots(db, orgs, actors, product, base):
    roots = {}
    # Unique farm per scenario is the persistent marker. Never replace a batch
    # if a user has subsequently changed its holder or quantity during a demo.
    scenarios = ["held", "pending", "overdue", "accepted", "rejected", "lineage", "packing-held", "distribution-held"]
    for index, scenario in enumerate(scenarios):
        # Quy tắc RBAC: Chỉ vai trò farmer (actors[0]) được thu hoạch tại nông trại của tổ chức nông trại
        name = f"[{PREFIX}] {scenario}"
        farm = db.scalar(select(Farm).where(Farm.name == name, Farm.organization_id == actors[0].organization_id))
        if farm is None:
            farm = Farm(name=name, location="Đồng bằng sông Cửu Long", area=2 + index / 10,
                        owner=orgs[0].name, organization_id=actors[0].organization_id,
                        coordinates="10.45, 105.63")
            db.add(farm)
            db.commit()
        root = db.scalar(select(Batch).where(Batch.farm_id == farm.id).order_by(Batch.id))
        if root is None:
            EVENT_TIME.set(base + timedelta(hours=index))
            root = create_batch(BatchCreate(farm_id=farm.id, product_id=product.id,
                                initial_quantity=1000, harvest_date=base.date()), actors[0], db)
        roots[scenario] = root.id

    return roots


def _seed_handovers(db, orgs, actors, roots, base):
    for index, scenario in enumerate(["pending", "overdue", "accepted", "rejected", "packing-held", "distribution-held"]):
        root_id = roots[scenario]
        existing = db.scalar(select(Handover).where(Handover.batch_id == root_id))
        if existing is None:
            target_org = orgs[2] if scenario == "distribution-held" else orgs[1]
            target_actor = actors[2] if scenario == "distribution-held" else actors[1]
            moment = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=6)
                      if scenario == "pending" else base + timedelta(days=2, hours=index))
            EVENT_TIME.set(moment)
            payload = HandoverCreate(to_org_id=target_org.id, note=f"[DEMO26] {scenario}")
            handover = create_handover(payload, root_id, actors[0], db)
            if scenario in {"accepted", "rejected", "packing-held", "distribution-held"}:
                EVENT_TIME.set(base + timedelta(days=3, hours=index))
                if scenario == "rejected":
                    payload = HandoverRejectRequest(reject_reason="Chất lượng chưa đạt thỏa thuận demo.")
                    reject_handover(payload, handover.id, target_actor, db)
                else:
                    accept_handover(handover.id, target_actor, db)


def _seed_lineage(db, orgs, actors, roots, product, base):
    root_id = roots["lineage"]
    children = list(db.scalars(select(BatchRelation).where(
        BatchRelation.parent_batch_id == root_id, BatchRelation.relation_type == "SPLIT")).all())
    if not children:
        EVENT_TIME.set(base + timedelta(days=4))
        split_batch(BatchSplitRequest(child_quantities=[300, 400]), str(root_id), actors[0], db)
        children = list(db.scalars(select(BatchRelation).where(
            BatchRelation.parent_batch_id == root_id, BatchRelation.relation_type == "SPLIT")).all())
    children.sort(key=lambda r: r.child_batch_id)
    merged_rel = db.scalar(select(BatchRelation).where(
        BatchRelation.parent_batch_id == children[0].child_batch_id, BatchRelation.relation_type == "MERGE"))
    if merged_rel is None:
        # Bàn giao 2 lô con từ Farm (actors[0]) sang Trung tâm đóng gói / Processor (actors[1]) để gộp
        for r in children[:2]:
            c_batch = db.get(Batch, r.child_batch_id)
            if c_batch.current_org_id != orgs[1].id:
                EVENT_TIME.set(base + timedelta(days=4, hours=2))
                h = create_handover(HandoverCreate(to_org_id=orgs[1].id, note="Bàn giao sơ chế gộp lô"), r.child_batch_id, actors[0], db)
                EVENT_TIME.set(base + timedelta(days=4, hours=3))
                accept_handover(h.id, actors[1], db)

        EVENT_TIME.set(base + timedelta(days=5))
        result = merge_batches(BatchMergeRequest(product_id=product.id, items=[
            {"parent_batch_id": r.child_batch_id, "quantity": 200} for r in children[:2]]), actors[1], db)
        merged_id = result.merged_batch.id
    else:
        merged_id = merged_rel.child_batch_id

    # Bàn giao từ Trung tâm đóng gói (actors[1]) sang Doanh nghiệp phân phối (actors[2])
    existing = db.scalar(select(Handover).where(
        Handover.batch_id == merged_id, Handover.from_org_id == orgs[1].id))
    if existing is None:
        EVENT_TIME.set(base + timedelta(days=7, hours=1))
        payload = HandoverCreate(to_org_id=orgs[2].id, note="Truy xuất demo qua nhiều tổ chức")
        h = create_handover(payload, merged_id, actors[1], db)
        EVENT_TIME.set(base + timedelta(days=7, hours=2))
        accept_handover(h.id, actors[2], db)

    return merged_id


def _validate_demo(db, actors, roots, merged_id):
    from app.services.overdue_job import check_overdue_handovers
    check_overdue_handovers(db)
    db.expire_all()
    batch_ids = list(db.scalars(select(Batch.id).join(Farm, Batch.farm_id == Farm.id)
                                .where(Farm.name.like("[DEMO26]%"))).all())
    for batch_id in batch_ids:
        if not verify_batch_chain(db, batch_id)["is_valid"]:
            raise RuntimeError(f"Chuỗi hash demo không hợp lệ: {batch_id}")
    return {"dataset": PREFIX, "batches": len(batch_ids), "roots": roots, "trace_batch_id": merged_id,
            "accounts": [u.email for u in actors]}


def seed_demo(db: Session, password: str) -> dict:
    if os.getenv("TTCS_ENV", "local").lower() not in {"local", "development", "test"}:
        raise RuntimeError("Chỉ cho phép seed demo trong local/development/test.")
    if len(password) < 12:
        raise ValueError("DEMO_PASSWORD cần ít nhất 12 ký tự.")
    orgs, actors, product = _seed_identities(db, password)
    base = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=10)
    token = EVENT_TIME.set(base)
    try:
        roots = _seed_roots(db, orgs, actors, product, base)
        _seed_handovers(db, orgs, actors, roots, base)
        merged_id = _seed_lineage(db, orgs, actors, roots, product, base)
        return _validate_demo(db, actors, roots, merged_id)
    finally:
        EVENT_TIME.reset(token)


def main() -> None:
    if os.getenv("TTCS_ENV", "local").lower() not in {"local", "development", "test"}:
        raise SystemExit("Không seed demo ngoài local/development/test.")
    password = os.environ.get("DEMO_PASSWORD", "")
    if not password:
        password_file = Path(__file__).resolve().parents[2] / ".demo-password.local"
        if password_file.exists():
            password = password_file.read_text(encoding="utf-8").strip()
        else:
            password = secrets.token_urlsafe(24)
            fd = os.open(password_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(password)
        print(f"Mật khẩu local nằm trong {password_file}; không đưa tệp này lên Git.")
    if len(password) < 12:
        raise SystemExit("DEMO_PASSWORD cần ít nhất 12 ký tự.")
    init_db()
    with SessionLocal() as db:
        print(seed_demo(db, password))


if __name__ == "__main__":
    main()
