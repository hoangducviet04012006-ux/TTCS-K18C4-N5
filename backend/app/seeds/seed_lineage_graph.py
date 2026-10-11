"""Script khởi tạo đồ thị phả hệ mẫu 3 tầng, tối thiểu 12 lô và 3 tổ chức (T-52, T-53).

Cấu trúc đồ thị:
- 3 Tổ chức:
  1. Hợp tác xã Nông sản An Toàn Đồng Tháp (HTX-DT, id=1)
  2. Hợp tác xã Nông nghiệp Sạch Tiền Giang (HTX-TG, id=2)
  3. Công ty CP Xuất nhập khẩu Nông sản Miền Tây (DN-XNK, id=3)
- Tầng 0 (Gốc): 3 lô thu hoạch B-ROOT-01, B-ROOT-02, B-ROOT-03
- Tầng 1 (Tách): 6 lô B-SPLIT-01A, B-SPLIT-01B, B-SPLIT-02A, B-SPLIT-02B, B-SPLIT-03A, B-SPLIT-03B
- Tầng 2 (Gộp): 3 lô B-MERGE-01, B-MERGE-02, B-MERGE-03
- Tầng 3 (Tách & Bàn giao): B-FINAL-01 (chuyển sang Org 2), B-FINAL-02 (chuyển sang Org 3)
Tổng cộng: 14 lô qua 3 tổ chức, đầy đủ quan hệ BatchRelation và chuỗi Hash-Chain.
Script idempotent: có thể chạy lại nhiều lần mà không nhân đôi dữ liệu.
"""

import os
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.hash_chain import record_event
from app.models import (
    EVENT_EXPORT_MERGE,
    EVENT_GENESIS_SPLIT,
    EVENT_HANDOVER_ACCEPT,
    EVENT_HANDOVER_INIT,
    EVENT_HARVEST,
    EVENT_MERGE,
    EVENT_SPLIT,
    HANDOVER_ACCEPTED,
    RELATION_MERGE,
    RELATION_SPLIT,
    ROLE_FARMER,
    Batch,
    BatchRelation,
    Farm,
    Handover,
    Organization,
    Plot,
    Product,
    ProductUnit,
    User,
)
from app.security import hash_password


def seed_lineage_graph(db: Session | None = None) -> dict[str, int]:  # noqa: C901
    """Khởi tạo toàn bộ đồ thị phả hệ 3 tầng."""
    if os.getenv("TTCS_ENV", "local").lower() not in ("local", "development", "test"):
        raise RuntimeError("Demo seed is disabled outside local environments.")
    password = os.environ.get("DEMO_PASSWORD")
    if not password:
        raise RuntimeError("Set DEMO_PASSWORD before running the legacy seed.")
    should_close = False
    if db is None:
        db = SessionLocal()
        should_close = True

    try:
        # 1. Khởi tạo 3 tổ chức
        org_dt = db.scalar(select(Organization).where(Organization.code == "HTX-DT"))
        if org_dt is None:
            org_dt = Organization(
                name="Hợp tác xã Nông sản An Toàn Đồng Tháp",
                code="HTX-DT",
                description="HTX chuyên canh tác xoài xuất khẩu Cao Lãnh",
            )
            db.add(org_dt)
            db.flush()

        org_tg = db.scalar(select(Organization).where(Organization.code == "HTX-TG"))
        if org_tg is None:
            org_tg = Organization(
                name="Hợp tác xã Nông nghiệp Sạch Tiền Giang",
                code="HTX-TG",
                description="HTX sầu riêng và trái cây Tiền Giang",
            )
            db.add(org_tg)
            db.flush()

        org_xnk = db.scalar(select(Organization).where(Organization.code == "DN-XNK"))
        if org_xnk is None:
            org_xnk = Organization(
                name="Công ty CP Xuất nhập khẩu Nông sản Miền Tây",
                code="DN-XNK",
                description="Doanh nghiệp phân phối & xuất nhập khẩu nông sản",
            )
            db.add(org_xnk)
            db.flush()

        # Tài khoản người dùng đại diện cho Org 3 (S-04: kèm email hợp lệ)
        distributor = db.scalar(select(User).where(User.username == "distributor"))
        if distributor is None:
            db.add(
                User(
                    username="distributor",
                    email="distributor@gmail.com",
                    password=hash_password(password),
                    role=ROLE_FARMER,
                    organization_id=org_xnk.id,
                )
            )
            db.flush()
        elif not distributor.email:
            distributor.email = "distributor@gmail.com"

        admin_user = db.scalar(select(User).where(User.username == "admin"))
        user_id = admin_user.id if admin_user else 1

        # 2. Sản phẩm dùng chung
        product = db.scalar(select(Product).where(Product.name == "Xoài cát Chu"))
        if product is None:
            product = Product(name="Xoài cát Chu", unit=ProductUnit.KG.value)
            db.add(product)
            db.flush()

        # 3. Ba thửa đất thuộc HTX-DT
        farms_data = [
            ("Vườn xoài Cao Lãnh 1", "Xã Mỹ Xương, TP. Cao Lãnh, Đồng Tháp", 3.5, "Nguyễn Văn An", "10.4532, 105.6321"),
            ("Vườn xoài Cao Lãnh 2", "Xã Tịnh Thới, TP. Cao Lãnh, Đồng Tháp", 2.8, "Trần Thị Bình", "10.4612, 105.6415"),
            ("Vườn xoài Cái Bè", "Xã Hòa Hưng, Cái Bè, Tiền Giang", 4.0, "Lê Văn Cường", "10.3541, 105.8821"),
        ]
        plots: list[Plot] = []
        for name, loc, area, owner, coords in farms_data:
            farm = db.scalar(select(Farm).where(Farm.name == name))
            if farm is None:
                farm = Farm(
                    name=name,
                    location=loc,
                    area=area,
                    owner=owner,
                    coordinates=coords,
                    organization_id=org_dt.id,
                )
                db.add(farm)
                db.flush()

            plot = db.scalar(select(Plot).where(Plot.name == name))
            if plot is None:
                plot = Plot(
                    id=farm.id,
                    name=name,
                    location=loc,
                    area=area,
                    owner=owner,
                    coordinates=coords,
                    organization_id=org_dt.id,
                )
                db.add(plot)
                db.flush()
            plots.append(plot)

        # Helper tạo hoặc lấy Batch theo code
        batch_map: dict[str, Batch] = {}

        def get_or_create_batch(
            code: str,
            plot_id: int,
            init_qty: Decimal,
            rem_qty: Decimal,
            harvest_dt: date,
            org_id: int,
            b_status: str = "ACTIVE",
        ) -> Batch:
            b = db.scalar(select(Batch).where(Batch.code == code))
            if b is None:
                b = Batch(
                    code=code,
                    plot_id=plot_id,
                    farm_id=plot_id,
                    product_id=product.id,
                    product_name=product.name,
                    harvest_date=harvest_dt,
                    initial_quantity=init_qty,
                    remaining_quantity=rem_qty,
                    quantity=float(rem_qty),
                    current_org_id=org_id,
                    status=b_status,
                )
                db.add(b)
                db.flush()
            else:
                b.remaining_quantity = rem_qty
                b.quantity = float(rem_qty)
                b.status = b_status
                b.current_org_id = org_id
                db.flush()
            batch_map[code] = b
            return b

        def ensure_relation(p_id: int, c_id: int, qty: Decimal, r_type: str) -> None:
            rel = db.scalar(
                select(BatchRelation).where(
                    BatchRelation.parent_batch_id == p_id,
                    BatchRelation.child_batch_id == c_id,
                )
            )
            if rel is None:
                db.add(
                    BatchRelation(
                        parent_batch_id=p_id,
                        child_batch_id=c_id,
                        transferred_quantity=qty,
                        relation_type=r_type,
                    )
                )
                db.flush()

        # ======================================================================
        # TẦNG 0: 3 Lô thu hoạch gốc (B-ROOT-01, B-ROOT-02, B-ROOT-03)
        # ======================================================================
        b_root1 = get_or_create_batch(
            "B-ROOT-01", plots[0].id, Decimal("1000.00"), Decimal("0.00"), date(2026, 9, 1), org_dt.id, "SPLIT"
        )
        b_root2 = get_or_create_batch(
            "B-ROOT-02", plots[1].id, Decimal("1000.00"), Decimal("0.00"), date(2026, 9, 2), org_dt.id, "SPLIT"
        )
        b_root3 = get_or_create_batch(
            "B-ROOT-03", plots[2].id, Decimal("1000.00"), Decimal("0.00"), date(2026, 9, 3), org_dt.id, "SPLIT"
        )

        for r_batch in [b_root1, b_root2, b_root3]:
            if not r_batch.events:
                record_event(
                    db=db,
                    batch_id=r_batch.id,
                    event_type=EVENT_HARVEST,
                    payload={
                        "batch_code": r_batch.code,
                        "harvest_date": str(r_batch.harvest_date),
                        "quantity": float(r_batch.initial_quantity),
                    },
                    org_id=org_dt.id,
                    user_id=user_id,
                )

        # ======================================================================
        # TẦNG 1: 6 Lô tách (B1 -> 1A, 1B; B2 -> 2A, 2B; B3 -> 3A, 3B)
        # ======================================================================
        b_s1a = get_or_create_batch(
            "B-SPLIT-01A", plots[0].id, Decimal("400.00"), Decimal("0.00"), date(2026, 9, 1), org_dt.id, "MERGED"
        )
        b_s1b = get_or_create_batch(
            "B-SPLIT-01B", plots[0].id, Decimal("600.00"), Decimal("0.00"), date(2026, 9, 1), org_dt.id, "MERGED"
        )
        ensure_relation(b_root1.id, b_s1a.id, Decimal("400.00"), RELATION_SPLIT)
        ensure_relation(b_root1.id, b_s1b.id, Decimal("600.00"), RELATION_SPLIT)

        b_s2a = get_or_create_batch(
            "B-SPLIT-02A", plots[1].id, Decimal("500.00"), Decimal("0.00"), date(2026, 9, 2), org_dt.id, "MERGED"
        )
        b_s2b = get_or_create_batch(
            "B-SPLIT-02B", plots[1].id, Decimal("500.00"), Decimal("0.00"), date(2026, 9, 2), org_dt.id, "MERGED"
        )
        ensure_relation(b_root2.id, b_s2a.id, Decimal("500.00"), RELATION_SPLIT)
        ensure_relation(b_root2.id, b_s2b.id, Decimal("500.00"), RELATION_SPLIT)

        b_s3a = get_or_create_batch(
            "B-SPLIT-03A", plots[2].id, Decimal("300.00"), Decimal("0.00"), date(2026, 9, 3), org_dt.id, "MERGED"
        )
        b_s3b = get_or_create_batch(
            "B-SPLIT-03B", plots[2].id, Decimal("700.00"), Decimal("0.00"), date(2026, 9, 3), org_dt.id, "MERGED"
        )
        ensure_relation(b_root3.id, b_s3a.id, Decimal("300.00"), RELATION_SPLIT)
        ensure_relation(b_root3.id, b_s3b.id, Decimal("700.00"), RELATION_SPLIT)

        for p_batch, children in [(b_root1, [b_s1a, b_s1b]), (b_root2, [b_s2a, b_s2b]), (b_root3, [b_s3a, b_s3b])]:
            has_split = any(e.event_type == EVENT_SPLIT for e in p_batch.events)
            if not has_split:
                record_event(
                    db=db,
                    batch_id=p_batch.id,
                    event_type=EVENT_SPLIT,
                    payload={
                        "child_batch_codes": [c.code for c in children],
                        "total_split_quantity": float(p_batch.initial_quantity),
                    },
                    org_id=org_dt.id,
                    user_id=user_id,
                )
            for c in children:
                if not c.events:
                    record_event(
                        db=db,
                        batch_id=c.id,
                        event_type=EVENT_GENESIS_SPLIT,
                        payload={
                            "parent_batch_code": p_batch.code,
                            "parent_batch_id": p_batch.id,
                            "quantity": float(c.initial_quantity),
                        },
                        org_id=org_dt.id,
                        user_id=user_id,
                    )

        # ======================================================================
        # TẦNG 2: 3 Lô gộp (M1: 1A+2A -> 900kg; M2: 1B+3A -> 900kg; M3: 2B+3B -> 1200kg)
        # ======================================================================
        b_m1 = get_or_create_batch(
            "B-MERGE-01", plots[0].id, Decimal("900.00"), Decimal("0.00"), date(2026, 9, 4), org_dt.id, "SPLIT"
        )
        ensure_relation(b_s1a.id, b_m1.id, Decimal("400.00"), RELATION_MERGE)
        ensure_relation(b_s2a.id, b_m1.id, Decimal("500.00"), RELATION_MERGE)

        b_m2 = get_or_create_batch(
            "B-MERGE-02", plots[0].id, Decimal("900.00"), Decimal("900.00"), date(2026, 9, 4), org_dt.id, "ACTIVE"
        )
        ensure_relation(b_s1b.id, b_m2.id, Decimal("600.00"), RELATION_MERGE)
        ensure_relation(b_s3a.id, b_m2.id, Decimal("300.00"), RELATION_MERGE)

        b_m3 = get_or_create_batch(
            "B-MERGE-03", plots[1].id, Decimal("1200.00"), Decimal("1200.00"), date(2026, 9, 4), org_dt.id, "ACTIVE"
        )
        ensure_relation(b_s2b.id, b_m3.id, Decimal("500.00"), RELATION_MERGE)
        ensure_relation(b_s3b.id, b_m3.id, Decimal("700.00"), RELATION_MERGE)

        for m_batch, parents_info in [
            (b_m1, [(b_s1a, 400.0), (b_s2a, 500.0)]),
            (b_m2, [(b_s1b, 600.0), (b_s3a, 300.0)]),
            (b_m3, [(b_s2b, 500.0), (b_s3b, 700.0)]),
        ]:
            for p, q in parents_info:
                has_export = any(e.event_type == EVENT_EXPORT_MERGE for e in p.events)
                if not has_export:
                    record_event(
                        db=db,
                        batch_id=p.id,
                        event_type=EVENT_EXPORT_MERGE,
                        payload={"merged_batch_code": m_batch.code, "quantity_taken": q},
                        org_id=org_dt.id,
                        user_id=user_id,
                    )
            has_merge = any(e.event_type == EVENT_MERGE for e in m_batch.events)
            if not has_merge:
                record_event(
                    db=db,
                    batch_id=m_batch.id,
                    event_type=EVENT_MERGE,
                    payload={
                        "parent_batches": [{"code": p[0].code, "quantity": p[1]} for p in parents_info],
                        "total_quantity": float(m_batch.initial_quantity),
                    },
                    org_id=org_dt.id,
                    user_id=user_id,
                )

        # ======================================================================
        # TẦNG 3: Tách B-MERGE-01 -> B-FINAL-01 (500kg) & B-FINAL-02 (400kg)
        # Bàn giao B-FINAL-01 cho HTX-TG (Org 2), B-FINAL-02 cho DN-XNK (Org 3)
        # ======================================================================
        b_fin1 = get_or_create_batch(
            "B-FINAL-01", plots[0].id, Decimal("500.00"), Decimal("500.00"), date(2026, 9, 5), org_tg.id, "ACTIVE"
        )
        b_fin2 = get_or_create_batch(
            "B-FINAL-02", plots[0].id, Decimal("400.00"), Decimal("400.00"), date(2026, 9, 5), org_xnk.id, "ACTIVE"
        )
        ensure_relation(b_m1.id, b_fin1.id, Decimal("500.00"), RELATION_SPLIT)
        ensure_relation(b_m1.id, b_fin2.id, Decimal("400.00"), RELATION_SPLIT)

        has_split_m1 = any(e.event_type == EVENT_SPLIT for e in b_m1.events)
        if not has_split_m1:
            record_event(
                db=db,
                batch_id=b_m1.id,
                event_type=EVENT_SPLIT,
                payload={"child_batch_codes": [b_fin1.code, b_fin2.code], "total_split_quantity": 900.0},
                org_id=org_dt.id,
                user_id=user_id,
            )

        for fin in [b_fin1, b_fin2]:
            has_genesis = any(e.event_type == EVENT_GENESIS_SPLIT for e in fin.events)
            if not has_genesis:
                record_event(
                    db=db,
                    batch_id=fin.id,
                    event_type=EVENT_GENESIS_SPLIT,
                    payload={
                        "parent_batch_code": b_m1.code,
                        "parent_batch_id": b_m1.id,
                        "quantity": float(fin.initial_quantity),
                    },
                    org_id=org_dt.id,
                    user_id=user_id,
                )

        # Bàn giao B-FINAL-01 sang Org 2
        h1 = db.scalar(select(Handover).where(Handover.batch_id == b_fin1.id))
        if h1 is None:
            h1 = Handover(
                batch_id=b_fin1.id,
                from_org_id=org_dt.id,
                to_org_id=org_tg.id,
                status=HANDOVER_ACCEPTED,
            )
            db.add(h1)
            db.flush()
            record_event(
                db=db,
                batch_id=b_fin1.id,
                event_type=EVENT_HANDOVER_INIT,
                payload={"from_org": org_dt.code, "to_org": org_tg.code},
                org_id=org_dt.id,
                user_id=user_id,
            )
            record_event(
                db=db,
                batch_id=b_fin1.id,
                event_type=EVENT_HANDOVER_ACCEPT,
                payload={"from_org": org_dt.code, "to_org": org_tg.code, "message": "Tiếp nhận thành công"},
                org_id=org_tg.id,
                user_id=user_id,
            )

        # Bàn giao B-FINAL-02 sang Org 3
        h2 = db.scalar(select(Handover).where(Handover.batch_id == b_fin2.id))
        if h2 is None:
            h2 = Handover(
                batch_id=b_fin2.id,
                from_org_id=org_dt.id,
                to_org_id=org_xnk.id,
                status=HANDOVER_ACCEPTED,
            )
            db.add(h2)
            db.flush()
            record_event(
                db=db,
                batch_id=b_fin2.id,
                event_type=EVENT_HANDOVER_INIT,
                payload={"from_org": org_dt.code, "to_org": org_xnk.code},
                org_id=org_dt.id,
                user_id=user_id,
            )
            record_event(
                db=db,
                batch_id=b_fin2.id,
                event_type=EVENT_HANDOVER_ACCEPT,
                payload={"from_org": org_dt.code, "to_org": org_xnk.code, "message": "Tiếp nhận thành công"},
                org_id=org_xnk.id,
                user_id=user_id,
            )

        db.commit()

        return {code: b.id for code, b in batch_map.items()}
    finally:
        if should_close:
            db.close()


if __name__ == "__main__":
    result = seed_lineage_graph()
    print(f"Đã khởi tạo thành công đồ thị phả hệ với {len(result)} lô nông sản:")
    for code, b_id in result.items():
        print(f"  - {code}: id={b_id}")
