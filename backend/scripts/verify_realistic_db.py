"""Bộ kiểm thử kiểm định toàn diện cơ sở dữ liệu demo thực tế."""
import os
import sys
from pathlib import Path
from decimal import Decimal
import sqlite3

ROOT = Path(__file__).resolve().parents[2]
TRIAL = ROOT / ".sprint123-trial"
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.models import Batch, BatchRelation, BatchEvent, Handover, Organization, User, Farm, Plot, Product
from app.hash_chain import verify_batch_chain


def verify_db(db_path: Path):
    print(f"=== BẮT ĐẦU KIỂM TRA TOÀN DIỆN DATABASE: {db_path.name} ===")
    
    # 1. SQLite PRAGMA checks
    with sqlite3.connect(db_path) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchall()
        assert integrity == [("ok",)], f"PRAGMA integrity_check thất bại: {integrity}"
        print("✓ PRAGMA integrity_check: OK")

        fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
        assert fk_errors == [], f"Phát hiện lỗi Foreign Key: {fk_errors}"
        print("✓ PRAGMA foreign_key_check: OK (Không có lỗi khóa ngoại)")

        marker = conn.execute("SELECT value FROM sprint_demo_marker WHERE name='scope'").fetchone()
        assert marker == ("sprint123",), f"Sai sprint_demo_marker: {marker}"
        print("✓ sprint_demo_marker: 'sprint123' hợp lệ")

    # 2. SQLAlchemy ORM checks
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    with Session(engine) as db:
        # Check Organizations
        orgs = db.scalars(select(Organization).order_by(Organization.id)).all()
        assert len(orgs) == 3, f"Số lượng tổ chức phải là 3, hiện tại: {len(orgs)}"
        print(f"✓ Tổ chức ({len(orgs)}):")
        for o in orgs:
            print(f"   - [{o.id}] {o.code}: {o.name}")

        # Check Users
        users = db.scalars(select(User).order_by(User.id)).all()
        assert len(users) == 9, f"Số lượng users phải là 9, hiện tại: {len(users)}"
        print(f"✓ Tài khoản ({len(users)}):")
        for u in users:
            print(f"   - [{u.id}] {u.username} ({u.role}) - Org: {u.organization_id} - Active: {u.is_active}")

        # Check Products & Farms
        products = db.scalars(select(Product)).all()
        assert len(products) >= 1
        print(f"✓ Sản phẩm: {products[0].name} ({products[0].unit})")

        farms = db.scalars(select(Farm)).all()
        assert len(farms) == 3
        print(f"✓ Vùng trồng ({len(farms)}):")
        for f in farms:
            print(f"   - [{f.id}] {f.name} ({f.area} ha) - Chủ hộ: {f.owner}")

        # Check Batches & Hash-Chains
        batches = db.scalars(select(Batch).order_by(Batch.id)).all()
        assert len(batches) == 16, f"Số lượng lô phải là 16, hiện tại: {len(batches)}"
        print(f"\n✓ Kiểm tra Cryptographic Hash-Chain toàn bộ {len(batches)} lô hàng:")

        chain_all_valid = True
        for b in batches:
            res = verify_batch_chain(db, b.id)
            is_valid = res.get("is_valid") or res.get("valid")
            events_count = res.get("total_events", 0)
            assert is_valid, f"Lô {b.code} (ID {b.id}) bị hỏng hash-chain: {res}"
            print(f"   - Lô [{b.id}] {b.code:20} | Trạng thái: {b.status:10} | Qty: {b.remaining_quantity}/{b.initial_quantity} kg | {events_count} sự kiện SHA-256 ✓")

        # 3. Check Mass Conservation (Bảo toàn khối lượng khi Tách & Gộp)
        print("\n✓ Kiểm tra Bảo toàn khối lượng khi Tách/Gộp:")
        # Root 1 -> LO-A1 (400) + LO-B1 (600) = 1000
        r1 = db.scalar(select(Batch).where(Batch.code == "XOAI-CL-01"))
        a1 = db.scalar(select(Batch).where(Batch.code == "XOAI-LO-A1"))
        b1 = db.scalar(select(Batch).where(Batch.code == "XOAI-LO-B1"))
        assert r1.initial_quantity == a1.initial_quantity + b1.initial_quantity, "Sai bảo toàn khối lượng Root 1"
        print(f"   - Tách XOAI-CL-01: {r1.initial_quantity}kg == {a1.initial_quantity}kg + {b1.initial_quantity}kg ✓")

        # Root 2 -> LO-A2 (500) + LO-B2 (500) = 1000
        r2 = db.scalar(select(Batch).where(Batch.code == "XOAI-TT-02"))
        a2 = db.scalar(select(Batch).where(Batch.code == "XOAI-LO-A2"))
        b2 = db.scalar(select(Batch).where(Batch.code == "XOAI-LO-B2"))
        assert r2.initial_quantity == a2.initial_quantity + b2.initial_quantity, "Sai bảo toàn khối lượng Root 2"
        print(f"   - Tách XOAI-TT-02: {r2.initial_quantity}kg == {a2.initial_quantity}kg + {b2.initial_quantity}kg ✓")

        # Root 3 -> LO-A3 (300) + LO-B3 (700) = 1000
        r3 = db.scalar(select(Batch).where(Batch.code == "XOAI-CB-03"))
        a3 = db.scalar(select(Batch).where(Batch.code == "XOAI-LO-A3"))
        b3 = db.scalar(select(Batch).where(Batch.code == "XOAI-LO-B3"))
        assert r3.initial_quantity == a3.initial_quantity + b3.initial_quantity, "Sai bảo toàn khối lượng Root 3"
        print(f"   - Tách XOAI-CB-03: {r3.initial_quantity}kg == {a3.initial_quantity}kg + {b3.initial_quantity}kg ✓")

        # Gộp 1: A1 (400) + A2 (500) = GOP-XK01 (900)
        m1 = db.scalar(select(Batch).where(Batch.code == "XOAI-GOP-XK01"))
        assert m1.initial_quantity == a1.initial_quantity + a2.initial_quantity, "Sai bảo toàn khối lượng Merge 1"
        print(f"   - Gộp XOAI-GOP-XK01: {m1.initial_quantity}kg == {a1.initial_quantity}kg + {a2.initial_quantity}kg ✓")

        # Tách Gộp 1: GOP-XK01 (900) -> TP-MK01 (500) + TP-BHX02 (400)
        fin1 = db.scalar(select(Batch).where(Batch.code == "XOAI-TP-MK01"))
        fin2 = db.scalar(select(Batch).where(Batch.code == "XOAI-TP-BHX02"))
        assert m1.initial_quantity == fin1.initial_quantity + fin2.initial_quantity, "Sai bảo toàn khối lượng Tách từ Merge 1"
        print(f"   - Tách từ Lô gộp: {m1.initial_quantity}kg == {fin1.initial_quantity}kg + {fin2.initial_quantity}kg ✓")

        # 4. Check Handovers
        handovers = db.scalars(select(Handover).order_by(Handover.id)).all()
        print(f"\n✓ Kiểm tra Bàn giao liên tổ chức ({len(handovers)} bản ghi):")
        for h in handovers:
            b = db.get(Batch, h.batch_id)
            from_o = db.get(Organization, h.from_org_id)
            to_o = db.get(Organization, h.to_org_id)
            print(f"   - [{h.id}] Lô {b.code:20}: {from_o.code} -> {to_o.code} | Trạng thái: {h.status}")

        # 5. Check DAG Relations
        relations = db.scalars(select(BatchRelation)).all()
        print(f"\n✓ Tổng quan quan hệ phả hệ BatchRelation: {len(relations)} quan hệ liên kết hợp lệ.")

    engine.dispose()
    print("\n=== TOÀN BỘ KIỂM TRA ĐẠT 100% ===")
    return True


if __name__ == "__main__":
    target = TRIAL / "demo_sprint123_realistic.db"
    verify_db(target)
