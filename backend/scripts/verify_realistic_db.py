"""Bộ kiểm thử kiểm định toàn diện cơ sở dữ liệu demo chuẩn thực tế (Miền Bắc)."""
import os
import sys
from pathlib import Path
from decimal import Decimal
import sqlite3
import json

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
from app.security import verify_password


def verify_db(db_path: Path):
    print(f"=== BẮT ĐẦU KIỂM TRA TOÀN DIỆN DATABASE MIỀN BẮC: {db_path.name} ===")
    
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
        expected_org_codes = {1: "HTX-TC", 2: "LOG-HN", 3: "NPP-BN"}
        for o in orgs:
            assert o.code == expected_org_codes[o.id], f"Sai code tổ chức {o.id}: {o.code} != {expected_org_codes[o.id]}"
        print(f"✓ Tổ chức miền Bắc ({len(orgs)}):")
        for o in orgs:
            print(f"   - [{o.id}] {o.code}: {o.name}")

        # Check Users & 8 demo accounts authentication
        users = db.scalars(select(User).order_by(User.id)).all()
        assert len(users) == 9, f"Số lượng users phải là 9, hiện tại: {len(users)}"
        print(f"✓ Tài khoản ({len(users)}):")
        for u in users:
            print(f"   - [{u.id}] {u.username} ({u.role}) - Org: {u.organization_id} - Active: {u.is_active}")

        cred_file = TRIAL / "credentials.local"
        creds = json.loads(cred_file.read_text(encoding="utf-8")) if cred_file.exists() else {}

        print("\n✓ Kiểm tra xác thực 8 tài khoản demo với credentials.local:")
        demo_accounts = [
            ("s123_admin", "admin", "system_admin", 1),
            ("s123_farm", "farm", "farmer", 1),
            ("s123_packing", "packing", "processor", 1),
            ("s123_receiver", "receiver", "processor", 2),
            ("s123_transport", "transport", "transporter", 2),
            ("s123_distribution", "distribution", "distributor", 3),
            ("s123_inspector", "inspector", "inspector", None),
            ("s123_org_admin", "org_admin", "org_admin", 1),
        ]
        for uname, ckey, exp_role, exp_org in demo_accounts:
            user = db.scalar(select(User).where(User.username == uname))
            assert user is not None, f"Không tìm thấy user {uname}"
            assert user.role == exp_role, f"Sai role cho {uname}: {user.role} != {exp_role}"
            assert user.organization_id == exp_org, f"Sai org cho {uname}: {user.organization_id} != {exp_org}"
            raw_pwd = creds.get(ckey, "123456")
            assert verify_password(raw_pwd, user.password), f"Đăng nhập thất bại cho {uname} với mật khẩu trong credentials.local"
            print(f"   - Đăng nhập {uname:18} | Role: {user.role:14} | Org: {str(user.organization_id):4} | Mật khẩu: OK ✓")

        # Check Products & Farms
        products = db.scalars(select(Product)).all()
        assert len(products) >= 1
        p_main = products[0]
        assert "Tân Cương" in p_main.name, f"Tên sản phẩm chính không phải Tân Cương: {p_main.name}"
        print(f"\n✓ Sản phẩm chính: {p_main.name} ({p_main.unit})")
        if len(products) > 1:
            print(f"✓ Sản phẩm bổ sung: {products[1].name} ({products[1].unit})")

        farms = db.scalars(select(Farm)).all()
        assert len(farms) == 3
        print(f"\n✓ Vùng trồng Thái Nguyên ({len(farms)}):")
        for f in farms:
            assert f.organization_id == 1, f"Farm {f.id} phải thuộc Org 1"
            print(f"   - [{f.id}] {f.name} ({f.area} ha) - Tọa độ: {f.coordinates} - Chủ hộ: {f.owner}")

        # Check Batches & Hash-Chains
        batches = db.scalars(select(Batch).order_by(Batch.id)).all()
        assert len(batches) == 16, f"Số lượng lô phải là 16, hiện tại: {len(batches)}"
        print(f"\n✓ Kiểm tra Cryptographic Hash-Chain toàn bộ {len(batches)} lô hàng miền Bắc:")

        for b in batches:
            res = verify_batch_chain(db, b.id)
            is_valid = res.get("is_valid") or res.get("valid")
            events_count = res.get("total_events", 0)
            assert is_valid, f"Lô {b.code} (ID {b.id}) bị hỏng hash-chain: {res}"
            print(f"   - Lô [{b.id:2}] {b.code:20} | Status: {b.status:10} | Qty: {float(b.remaining_quantity):6.1f}/{float(b.initial_quantity):6.1f} kg | {events_count} sự kiện SHA-256 ✓")

        # 3. Check Mass Conservation (Bảo toàn khối lượng khi Tách & Gộp)
        print("\n✓ Kiểm tra Bảo toàn khối lượng khi Tách/Gộp:")
        r1 = db.scalar(select(Batch).where(Batch.code == "CHE-TC-01"))
        a1 = db.scalar(select(Batch).where(Batch.code == "CHE-LO-A1"))
        b1 = db.scalar(select(Batch).where(Batch.code == "CHE-LO-B1"))
        assert r1.initial_quantity == a1.initial_quantity + b1.initial_quantity, "Sai bảo toàn khối lượng Root 1"
        print(f"   - Tách CHE-TC-01: {r1.initial_quantity}kg == {a1.initial_quantity}kg + {b1.initial_quantity}kg ✓")

        r2 = db.scalar(select(Batch).where(Batch.code == "CHE-PT-02"))
        a2 = db.scalar(select(Batch).where(Batch.code == "CHE-LO-A2"))
        b2 = db.scalar(select(Batch).where(Batch.code == "CHE-LO-B2"))
        assert r2.initial_quantity == a2.initial_quantity + b2.initial_quantity, "Sai bảo toàn khối lượng Root 2"
        print(f"   - Tách CHE-PT-02: {r2.initial_quantity}kg == {a2.initial_quantity}kg + {b2.initial_quantity}kg ✓")

        r3 = db.scalar(select(Batch).where(Batch.code == "CHE-PX-03"))
        a3 = db.scalar(select(Batch).where(Batch.code == "CHE-LO-A3"))
        b3 = db.scalar(select(Batch).where(Batch.code == "CHE-LO-B3"))
        assert r3.initial_quantity == a3.initial_quantity + b3.initial_quantity, "Sai bảo toàn khối lượng Root 3"
        print(f"   - Tách CHE-PX-03: {r3.initial_quantity}kg == {a3.initial_quantity}kg + {b3.initial_quantity}kg ✓")

        m1 = db.scalar(select(Batch).where(Batch.code == "CHE-GOP-HN01"))
        assert m1.initial_quantity == a1.initial_quantity + a2.initial_quantity, "Sai bảo toàn khối lượng Merge 1"
        print(f"   - Gộp CHE-GOP-HN01: {m1.initial_quantity}kg == {a1.initial_quantity}kg + {a2.initial_quantity}kg ✓")

        fin1 = db.scalar(select(Batch).where(Batch.code == "CHE-TP-HN01"))
        fin2 = db.scalar(select(Batch).where(Batch.code == "CHE-TP-BN02"))
        assert m1.initial_quantity == fin1.initial_quantity + fin2.initial_quantity, "Sai bảo toàn khối lượng Tách từ Merge 1"
        print(f"   - Tách từ Lô gộp CHE-GOP-HN01: {m1.initial_quantity}kg == {fin1.initial_quantity}kg + {fin2.initial_quantity}kg ✓")

        m2 = db.scalar(select(Batch).where(Batch.code == "CHE-GOP-ND02"))
        assert m2.initial_quantity == b1.initial_quantity + a3.initial_quantity, "Sai bảo toàn khối lượng Merge 2"
        print(f"   - Gộp CHE-GOP-ND02: {m2.initial_quantity}kg == {b1.initial_quantity}kg + {a3.initial_quantity}kg ✓")

        m3 = db.scalar(select(Batch).where(Batch.code == "CHE-GOP-CB03"))
        assert m3.initial_quantity == b2.initial_quantity + b3.initial_quantity, "Sai bảo toàn khối lượng Merge 3"
        print(f"   - Gộp CHE-GOP-CB03: {m3.initial_quantity}kg == {b2.initial_quantity}kg + {b3.initial_quantity}kg ✓")

        # 4. Check Handovers (Bàn giao liên tổ chức)
        handovers = db.scalars(select(Handover).order_by(Handover.id)).all()
        print(f"\n✓ Kiểm tra Bàn giao liên tổ chức ({len(handovers)} bản ghi):")
        for h in handovers:
            b = db.get(Batch, h.batch_id)
            from_o = db.get(Organization, h.from_org_id)
            to_o = db.get(Organization, h.to_org_id)
            print(f"   - [{h.id}] Lô {b.code:20}: {from_o.code} -> {to_o.code} | Trạng thái: {h.status}")

        # Check Farmer -> Org 2 -> Org 3 demo flow readiness
        assert any(h.from_org_id == 1 and h.to_org_id == 2 and h.status == "PENDING" for h in handovers), "Thiếu lô PENDING Org 1 -> Org 2"
        assert any(h.from_org_id == 1 and h.to_org_id == 2 and h.status == "ACCEPTED" for h in handovers), "Thiếu lô ACCEPTED Org 1 -> Org 2"
        assert any(h.from_org_id == 1 and h.to_org_id == 3 and h.status == "ACCEPTED" for h in handovers), "Thiếu lô ACCEPTED Org 1 -> Org 3"
        print("✓ Chuỗi demo Farmer (Org 1) -> Chế biến/Logistics (Org 2) -> Phân phối (Org 3) sẵn sàng đầy đủ các trạng thái!")

        # 5. Check DAG Relations
        relations = db.scalars(select(BatchRelation)).all()
        print(f"\n✓ Quan hệ phả hệ BatchRelation: {len(relations)} quan hệ liên kết hợp lệ.")

    engine.dispose()
    print("\n=== TOÀN BỘ KIỂM TRA DATABASE MIỀN BẮC ĐẠT 100% ===")
    return True


if __name__ == "__main__":
    target = TRIAL / "demo_sprint123_north.db"
    verify_db(target)
