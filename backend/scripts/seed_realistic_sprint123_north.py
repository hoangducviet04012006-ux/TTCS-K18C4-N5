"""Tạo cơ sở dữ liệu demo chuẩn miền Bắc cho AgriTrace Sprint 1-3.

Kịch bản xuyên suốt:
- Sản phẩm chính: Chè búp tươi Tân Cương (đơn vị: kg, chuẩn VietGAP)
- Sản phẩm bổ sung: Rau an toàn Gia Lâm (đơn vị: kg)
- 3 Tổ chức miền Bắc:
  1. HTX Nông nghiệp Tân Cương – Thái Nguyên (HTX-TC) - Nông dân, sơ chế, quản trị viên HTX
  2. Công ty Chế biến & Logistics Hà Nội (LOG-HN) - Tiếp nhận chế biến sâu, vận tải chuỗi lạnh
  3. Trung tâm Phân phối Nông sản Bắc Ninh (NPP-BN) - Phân phối, bán lẻ, tiêu thụ nông sản
- 3 Vùng trồng/thửa đất tại Thái Nguyên với địa danh và chủ nông hộ thực tế:
  1. Đồi Chè Tân Cương 1 (Xã Tân Cương, TP. Thái Nguyên)
  2. Đồi Chè Phúc Trìu (Xã Phúc Trìu, TP. Thái Nguyên)
  3. Đồi Chè Phúc Xuân (Xã Phúc Xuân, TP. Thái Nguyên)
- Chuỗi cung ứng phả hệ mẫu hoàn chỉnh:
  Thu hoạch gốc -> Phân loại phẩm cấp (Tách) -> Đóng gói tiêu chuẩn (Gộp) -> Bàn giao vận chuyển & phân phối
- Bổ sung 1 lô bàn giao đang chờ duyệt (PENDING) để demo tiếp nhận bàn giao.
- Bổ sung 1 lô đã bán lẻ hết (CONSUMED) để minh họa trọn vẹn vòng đời chuỗi cung ứng.
- Toàn bộ chuỗi Hash-Chain SHA-256 được tính toán và lưu trữ tuần tự qua record_event().
"""
import os
import sys
from pathlib import Path
from datetime import date, datetime, timezone
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
from app.database import Base, create_event_immutability_triggers
from app.models import (
    Organization,
    User,
    Farm,
    Plot,
    Product,
    ProductUnit,
    Batch,
    BatchRelation,
    Handover,
    EVENT_HARVEST,
    EVENT_SPLIT,
    EVENT_GENESIS_SPLIT,
    EVENT_MERGE,
    EVENT_EXPORT_MERGE,
    EVENT_HANDOVER_INIT,
    EVENT_HANDOVER_ACCEPT,
    EVENT_CONSUMED,
    RELATION_SPLIT,
    RELATION_MERGE,
    HANDOVER_PENDING,
    HANDOVER_ACCEPTED,
    ROLE_FARMER,
    ROLE_PROCESSOR,
    ROLE_TRANSPORTER,
    ROLE_DISTRIBUTOR,
    ROLE_INSPECTOR,
    ROLE_ORG_ADMIN,
    ROLE_SYSTEM_ADMIN,
)
from app.hash_chain import record_event, verify_batch_chain
from app.security import hash_password


def build_north_db(target_path: Path):
    target_path = Path(target_path).resolve()
    if target_path.exists():
        target_path.unlink()

    # 1. Đọc mật khẩu từ credentials.local hoặc db backup để bảo toàn 100% tài khoản và mật khẩu
    cred_file = TRIAL / "credentials.local"
    if cred_file.exists():
        creds = json.loads(cred_file.read_text(encoding="utf-8"))
    else:
        raise RuntimeError("Không tìm thấy credentials.local! Cần bảo toàn mật khẩu hiện hữu.")

    backup_db = TRIAL / "demo_sprint123_backup_original.db"
    existing_hashes = {}
    if backup_db.exists():
        with sqlite3.connect(backup_db) as conn:
            for row in conn.execute("SELECT username, password, email FROM users").fetchall():
                existing_hashes[row[0]] = (row[1], row[2])

    # 2. Khởi tạo engine SQLite trên file đích miền Bắc
    os.environ["DATABASE_URL"] = "sqlite:///" + target_path.as_posix()
    os.environ["TTCS_ENV"] = "test"
    engine = create_engine(f"sqlite:///{target_path.as_posix()}")

    # Tạo schema chuẩn
    Base.metadata.create_all(engine, tables=[t for t in Base.metadata.sorted_tables if not t.info.get("recall_trial")])

    with Session(engine) as db:
        # 3. Tạo 3 Tổ chức miền Bắc
        org_tc = Organization(
            id=1,
            name="HTX Nông nghiệp Tân Cương – Thái Nguyên",
            code="HTX-TC",
            description="HTX chuyên canh tác & sơ chế đóng gói chè búp tươi Tân Cương đạt chuẩn VietGAP tại Thái Nguyên",
        )
        org_hn = Organization(
            id=2,
            name="Công ty Chế biến & Logistics Hà Nội",
            code="LOG-HN",
            description="Doanh nghiệp chế biến sâu, bảo quản lạnh và vận tải nông sản chuyên dụng",
        )
        org_bn = Organization(
            id=3,
            name="Trung tâm Phân phối Nông sản Bắc Ninh",
            code="NPP-BN",
            description="Trung tâm phân phối bán lẻ và cung ứng nông sản tiêu chuẩn cao",
        )
        db.add_all([org_tc, org_hn, org_bn])
        db.flush()

        # 4. Tạo Users (Bảo toàn 100% 8 tài khoản demo và mật khẩu)
        users_def = [
            ("distributor", ROLE_FARMER, 3, "distributor@gmail.com", False),
            ("s123_admin", ROLE_SYSTEM_ADMIN, 1, "s123_admin@demo.local", True),
            ("s123_farm", ROLE_FARMER, 1, "s123_farm@demo.local", True),
            ("s123_packing", ROLE_PROCESSOR, 1, "s123_packing@demo.local", True),
            ("s123_receiver", ROLE_PROCESSOR, 2, "s123_receiver@demo.local", True),
            ("s123_transport", ROLE_TRANSPORTER, 2, "s123_transport@demo.local", True),
            ("s123_distribution", ROLE_DISTRIBUTOR, 3, "s123_distribution@demo.local", True),
            ("s123_inspector", ROLE_INSPECTOR, None, "s123_inspector@demo.local", True),
            ("s123_org_admin", ROLE_ORG_ADMIN, 1, "s123_org_admin@demo.local", True),
        ]

        for username, role, org_id, email, active in users_def:
            if username in existing_hashes:
                pwd_hash = existing_hashes[username][0]
            else:
                short_name = username.replace("s123_", "")
                raw_pwd = creds.get(short_name, "123456")
                pwd_hash = hash_password(raw_pwd)

            user = User(
                username=username,
                email=email,
                password=pwd_hash,
                role=role,
                organization_id=org_id,
                is_active=active,
            )
            db.add(user)
        db.flush()

        admin_user = db.scalar(select(User).where(User.username == "s123_admin"))
        actor_id = admin_user.id if admin_user else 2

        # 5. Sản phẩm miền Bắc
        product_che = Product(
            id=1,
            name="Chè búp tươi Tân Cương",
            unit=ProductUnit.KG.value,
        )
        product_rau = Product(
            id=2,
            name="Rau an toàn Gia Lâm",
            unit=ProductUnit.KG.value,
        )
        db.add_all([product_che, product_rau])
        db.flush()

        # 6. Ba vùng trồng/thửa đất tại Thái Nguyên
        farms_data = [
            (1, "Đồi Chè Tân Cương 1", "Xã Tân Cương, TP. Thái Nguyên, Tỉnh Thái Nguyên", 4.5, "Nguyễn Văn An", "21.5583, 105.7725", org_tc.id),
            (2, "Đồi Chè Phúc Trìu", "Xã Phúc Trìu, TP. Thái Nguyên, Tỉnh Thái Nguyên", 3.8, "Trần Thị Bình", "21.5712, 105.7481", org_tc.id),
            (3, "Đồi Chè Phúc Xuân", "Xã Phúc Xuân, TP. Thái Nguyên, Tỉnh Thái Nguyên", 5.2, "Lê Văn Cường", "21.5945, 105.7234", org_tc.id),
        ]
        plots = []
        for p_id, name, loc, area, owner, coords, o_id in farms_data:
            farm = Farm(id=p_id, name=name, location=loc, area=area, owner=owner, coordinates=coords, organization_id=o_id)
            plot = Plot(id=p_id, name=name, location=loc, area=area, owner=owner, coordinates=coords, organization_id=o_id)
            db.add(farm)
            db.add(plot)
            plots.append(plot)
        db.flush()

        # Helper tạo Batch
        def make_batch(code, plot_id, init_qty, rem_qty, h_date, org_id, status="ACTIVE"):
            b = Batch(
                code=code,
                plot_id=plot_id,
                farm_id=plot_id,
                product_id=product_che.id,
                product_name=product_che.name,
                harvest_date=h_date,
                initial_quantity=Decimal(str(init_qty)),
                remaining_quantity=Decimal(str(rem_qty)),
                quantity=float(rem_qty),
                current_org_id=org_id,
                status=status,
            )
            db.add(b)
            db.flush()
            return b

        def link_relation(p_id, c_id, qty, r_type):
            rel = BatchRelation(
                parent_batch_id=p_id,
                child_batch_id=c_id,
                transferred_quantity=Decimal(str(qty)),
                relation_type=r_type,
            )
            db.add(rel)
            db.flush()

        # ======================================================================
        # TẦNG 0: 3 Lô thu hoạch gốc
        # ======================================================================
        b_root1 = make_batch("CHE-TC-01", plots[0].id, 1000.0, 0.0, date(2026, 9, 1), org_tc.id, "SPLIT")
        record_event(
            db=db,
            batch_id=b_root1.id,
            event_type=EVENT_HARVEST,
            payload={
                "batch_code": b_root1.code,
                "product_name": product_che.name,
                "harvest_date": "2026-09-01",
                "initial_quantity": 1000.0,
                "quantity": 1000.0,
                "unit": "kg",
                "description": "Thu hoạch 1.000 kg chè búp tươi Tân Cương đạt chuẩn VietGAP tại Đồi Chè Tân Cương 1",
            },
            org_id=org_tc.id,
            user_id=actor_id,
        )

        b_root2 = make_batch("CHE-PT-02", plots[1].id, 1000.0, 0.0, date(2026, 9, 2), org_tc.id, "SPLIT")
        record_event(
            db=db,
            batch_id=b_root2.id,
            event_type=EVENT_HARVEST,
            payload={
                "batch_code": b_root2.code,
                "product_name": product_che.name,
                "harvest_date": "2026-09-02",
                "initial_quantity": 1000.0,
                "quantity": 1000.0,
                "unit": "kg",
                "description": "Thu hoạch 1.000 kg chè búp tươi tại Đồi Chè Phúc Trìu",
            },
            org_id=org_tc.id,
            user_id=actor_id,
        )

        b_root3 = make_batch("CHE-PX-03", plots[2].id, 1000.0, 0.0, date(2026, 9, 3), org_tc.id, "SPLIT")
        record_event(
            db=db,
            batch_id=b_root3.id,
            event_type=EVENT_HARVEST,
            payload={
                "batch_code": b_root3.code,
                "product_name": product_che.name,
                "harvest_date": "2026-09-03",
                "initial_quantity": 1000.0,
                "quantity": 1000.0,
                "unit": "kg",
                "description": "Thu hoạch 1.000 kg chè búp tươi tại Đồi Chè Phúc Xuân",
            },
            org_id=org_tc.id,
            user_id=actor_id,
        )

        # ======================================================================
        # TẦNG 1: 6 Lô sau phân loại phẩm cấp (Tách)
        # ======================================================================
        b_s1a = make_batch("CHE-LO-A1", plots[0].id, 400.0, 0.0, date(2026, 9, 1), org_tc.id, "MERGED")
        b_s1b = make_batch("CHE-LO-B1", plots[0].id, 600.0, 0.0, date(2026, 9, 1), org_tc.id, "MERGED")
        link_relation(b_root1.id, b_s1a.id, 400.0, RELATION_SPLIT)
        link_relation(b_root1.id, b_s1b.id, 600.0, RELATION_SPLIT)
        record_event(
            db=db,
            batch_id=b_root1.id,
            event_type=EVENT_SPLIT,
            payload={
                "child_batch_codes": [b_s1a.code, b_s1b.code],
                "child_quantities": [400.0, 600.0],
                "total_split_quantity": 1000.0,
                "unit": "kg",
                "description": "Sơ chế phân loại phẩm cấp: 400 kg Chè búp nõn loại 1 và 600 kg Chè búp loại 2",
            },
            org_id=org_tc.id,
            user_id=actor_id,
        )
        record_event(
            db=db,
            batch_id=b_s1a.id,
            event_type=EVENT_GENESIS_SPLIT,
            payload={"parent_batch_code": b_root1.code, "parent_batch_id": b_root1.id, "quantity": 400.0, "unit": "kg", "description": "Lô được tạo từ thao tác tách lô CHE-TC-01 (Chè búp nõn loại 1)"},
            org_id=org_tc.id,
            user_id=actor_id,
        )
        record_event(
            db=db,
            batch_id=b_s1b.id,
            event_type=EVENT_GENESIS_SPLIT,
            payload={"parent_batch_code": b_root1.code, "parent_batch_id": b_root1.id, "quantity": 600.0, "unit": "kg", "description": "Lô được tạo từ thao tác tách lô CHE-TC-01 (Chè búp loại 2)"},
            org_id=org_tc.id,
            user_id=actor_id,
        )

        b_s2a = make_batch("CHE-LO-A2", plots[1].id, 500.0, 0.0, date(2026, 9, 2), org_tc.id, "MERGED")
        b_s2b = make_batch("CHE-LO-B2", plots[1].id, 500.0, 0.0, date(2026, 9, 2), org_tc.id, "MERGED")
        link_relation(b_root2.id, b_s2a.id, 500.0, RELATION_SPLIT)
        link_relation(b_root2.id, b_s2b.id, 500.0, RELATION_SPLIT)
        record_event(
            db=db,
            batch_id=b_root2.id,
            event_type=EVENT_SPLIT,
            payload={
                "child_batch_codes": [b_s2a.code, b_s2b.code],
                "child_quantities": [500.0, 500.0],
                "total_split_quantity": 1000.0,
                "unit": "kg",
                "description": "Phân loại kiểm định: 500 kg Chè búp nõn loại 1 và 500 kg Chè búp loại 2",
            },
            org_id=org_tc.id,
            user_id=actor_id,
        )
        record_event(
            db=db,
            batch_id=b_s2a.id,
            event_type=EVENT_GENESIS_SPLIT,
            payload={"parent_batch_code": b_root2.code, "parent_batch_id": b_root2.id, "quantity": 500.0, "unit": "kg", "description": "Lô được tạo từ thao tác tách lô CHE-PT-02 (Chè búp nõn loại 1)"},
            org_id=org_tc.id,
            user_id=actor_id,
        )
        record_event(
            db=db,
            batch_id=b_s2b.id,
            event_type=EVENT_GENESIS_SPLIT,
            payload={"parent_batch_code": b_root2.code, "parent_batch_id": b_root2.id, "quantity": 500.0, "unit": "kg", "description": "Lô được tạo từ thao tác tách lô CHE-PT-02 (Chè búp loại 2)"},
            org_id=org_tc.id,
            user_id=actor_id,
        )

        b_s3a = make_batch("CHE-LO-A3", plots[2].id, 300.0, 0.0, date(2026, 9, 3), org_tc.id, "MERGED")
        b_s3b = make_batch("CHE-LO-B3", plots[2].id, 700.0, 0.0, date(2026, 9, 3), org_tc.id, "MERGED")
        link_relation(b_root3.id, b_s3a.id, 300.0, RELATION_SPLIT)
        link_relation(b_root3.id, b_s3b.id, 700.0, RELATION_SPLIT)
        record_event(
            db=db,
            batch_id=b_root3.id,
            event_type=EVENT_SPLIT,
            payload={
                "child_batch_codes": [b_s3a.code, b_s3b.code],
                "child_quantities": [300.0, 700.0],
                "total_split_quantity": 1000.0,
                "unit": "kg",
                "description": "Phân loại sơ bộ: 300 kg Chè búp nõn loại 1 và 700 kg Chè búp loại 2 chế biến",
            },
            org_id=org_tc.id,
            user_id=actor_id,
        )
        record_event(
            db=db,
            batch_id=b_s3a.id,
            event_type=EVENT_GENESIS_SPLIT,
            payload={"parent_batch_code": b_root3.code, "parent_batch_id": b_root3.id, "quantity": 300.0, "unit": "kg", "description": "Lô được tạo từ thao tác tách lô CHE-PX-03 (Chè búp nõn loại 1)"},
            org_id=org_tc.id,
            user_id=actor_id,
        )
        record_event(
            db=db,
            batch_id=b_s3b.id,
            event_type=EVENT_GENESIS_SPLIT,
            payload={"parent_batch_code": b_root3.code, "parent_batch_id": b_root3.id, "quantity": 700.0, "unit": "kg", "description": "Lô được tạo từ thao tác tách lô CHE-PX-03 (Chè búp loại 2 chế biến)"},
            org_id=org_tc.id,
            user_id=actor_id,
        )

        # ======================================================================
        # TẦNG 2: 3 Lô gộp theo tiêu chuẩn đóng gói & chế biến
        # ======================================================================
        # Lô gộp 1: A1 (400kg) + A2 (500kg) = 900kg -> Chuẩn chế biến cao cấp / chuyển giao
        b_m1 = make_batch("CHE-GOP-HN01", plots[0].id, 900.0, 0.0, date(2026, 9, 4), org_tc.id, "SPLIT")
        link_relation(b_s1a.id, b_m1.id, 400.0, RELATION_MERGE)
        link_relation(b_s2a.id, b_m1.id, 500.0, RELATION_MERGE)
        record_event(
            db=db,
            batch_id=b_s1a.id,
            event_type=EVENT_EXPORT_MERGE,
            payload={"merged_batch_code": b_m1.code, "quantity_taken": 400.0, "unit": "kg", "description": "Xuất 400 kg sang lô gộp chế biến cao cấp CHE-GOP-HN01"},
            org_id=org_tc.id,
            user_id=actor_id,
        )
        record_event(
            db=db,
            batch_id=b_s2a.id,
            event_type=EVENT_EXPORT_MERGE,
            payload={"merged_batch_code": b_m1.code, "quantity_taken": 500.0, "unit": "kg", "description": "Xuất 500 kg sang lô gộp chế biến cao cấp CHE-GOP-HN01"},
            org_id=org_tc.id,
            user_id=actor_id,
        )
        record_event(
            db=db,
            batch_id=b_m1.id,
            event_type=EVENT_MERGE,
            payload={
                "parent_batches": [{"code": b_s1a.code, "quantity": 400.0}, {"code": b_s2a.code, "quantity": 500.0}],
                "total_quantity": 900.0,
                "unit": "kg",
                "description": "Gộp 400 kg từ CHE-LO-A1 và 500 kg từ CHE-LO-A2 tạo lô chè nõn đồng nhất phẩm cấp",
            },
            org_id=org_tc.id,
            user_id=actor_id,
        )

        # Lô gộp 2: B1 (600kg) + A3 (300kg) = 900kg -> Phân phối nội địa (ACTIVE tại Org 1)
        b_m2 = make_batch("CHE-GOP-ND02", plots[0].id, 900.0, 900.0, date(2026, 9, 4), org_tc.id, "ACTIVE")
        link_relation(b_s1b.id, b_m2.id, 600.0, RELATION_MERGE)
        link_relation(b_s3a.id, b_m2.id, 300.0, RELATION_MERGE)
        record_event(
            db=db,
            batch_id=b_s1b.id,
            event_type=EVENT_EXPORT_MERGE,
            payload={"merged_batch_code": b_m2.code, "quantity_taken": 600.0, "unit": "kg", "description": "Xuất 600 kg sang lô gộp nội địa CHE-GOP-ND02"},
            org_id=org_tc.id,
            user_id=actor_id,
        )
        record_event(
            db=db,
            batch_id=b_s3a.id,
            event_type=EVENT_EXPORT_MERGE,
            payload={"merged_batch_code": b_m2.code, "quantity_taken": 300.0, "unit": "kg", "description": "Xuất 300 kg sang lô gộp nội địa CHE-GOP-ND02"},
            org_id=org_tc.id,
            user_id=actor_id,
        )
        record_event(
            db=db,
            batch_id=b_m2.id,
            event_type=EVENT_MERGE,
            payload={
                "parent_batches": [{"code": b_s1b.code, "quantity": 600.0}, {"code": b_s3a.code, "quantity": 300.0}],
                "total_quantity": 900.0,
                "unit": "kg",
                "description": "Gộp 600 kg từ CHE-LO-B1 và 300 kg từ CHE-LO-A3 lưu kho phân phối thị trường nội địa",
            },
            org_id=org_tc.id,
            user_id=actor_id,
        )

        # Lô gộp 3: B2 (500kg) + B3 (700kg) = 1200kg -> Chế biến chuyên sâu (ACTIVE tại Org 1)
        b_m3 = make_batch("CHE-GOP-CB03", plots[1].id, 1200.0, 1200.0, date(2026, 9, 4), org_tc.id, "ACTIVE")
        link_relation(b_s2b.id, b_m3.id, 500.0, RELATION_MERGE)
        link_relation(b_s3b.id, b_m3.id, 700.0, RELATION_MERGE)
        record_event(
            db=db,
            batch_id=b_s2b.id,
            event_type=EVENT_EXPORT_MERGE,
            payload={"merged_batch_code": b_m3.code, "quantity_taken": 500.0, "unit": "kg", "description": "Xuất 500 kg sang lô gộp xưởng chế biến CHE-GOP-CB03"},
            org_id=org_tc.id,
            user_id=actor_id,
        )
        record_event(
            db=db,
            batch_id=b_s3b.id,
            event_type=EVENT_EXPORT_MERGE,
            payload={"merged_batch_code": b_m3.code, "quantity_taken": 700.0, "unit": "kg", "description": "Xuất 700 kg sang lô gộp xưởng chế biến CHE-GOP-CB03"},
            org_id=org_tc.id,
            user_id=actor_id,
        )
        record_event(
            db=db,
            batch_id=b_m3.id,
            event_type=EVENT_MERGE,
            payload={
                "parent_batches": [{"code": b_s2b.code, "quantity": 500.0}, {"code": b_s3b.code, "quantity": 700.0}],
                "total_quantity": 1200.0,
                "unit": "kg",
                "description": "Gộp 500 kg từ CHE-LO-B2 và 700 kg từ CHE-LO-B3 chuẩn bị cung ứng xưởng chế biến trà túi lọc & trà ướp hương",
            },
            org_id=org_tc.id,
            user_id=actor_id,
        )

        # ======================================================================
        # TẦNG 3: Tách lô gộp CHE-GOP-HN01 -> 2 lô thành phẩm bàn giao
        # ======================================================================
        # Thành phẩm 1: 500 kg bàn giao cho Org 2 (LOG-HN)
        b_fin1 = make_batch("CHE-TP-HN01", plots[0].id, 500.0, 500.0, date(2026, 9, 5), org_hn.id, "ACTIVE")
        # Thành phẩm 2: 400 kg bàn giao cho Org 3 (NPP-BN)
        b_fin2 = make_batch("CHE-TP-BN02", plots[0].id, 400.0, 400.0, date(2026, 9, 5), org_bn.id, "ACTIVE")
        link_relation(b_m1.id, b_fin1.id, 500.0, RELATION_SPLIT)
        link_relation(b_m1.id, b_fin2.id, 400.0, RELATION_SPLIT)

        record_event(
            db=db,
            batch_id=b_m1.id,
            event_type=EVENT_SPLIT,
            payload={
                "child_batch_codes": [b_fin1.code, b_fin2.code],
                "child_quantities": [500.0, 400.0],
                "total_split_quantity": 900.0,
                "unit": "kg",
                "description": "Tách đóng thùng bảo quản tiêu chuẩn: 500 kg giao Công ty Chế biến & Logistics Hà Nội và 400 kg giao TT Phân phối Nông sản Bắc Ninh",
            },
            org_id=org_tc.id,
            user_id=actor_id,
        )

        record_event(
            db=db,
            batch_id=b_fin1.id,
            event_type=EVENT_GENESIS_SPLIT,
            payload={"parent_batch_code": b_m1.code, "parent_batch_id": b_m1.id, "quantity": 500.0, "unit": "kg", "description": "Lô được tạo từ thao tác tách lô gộp CHE-GOP-HN01 (500 kg chuyển giao chế biến sâu)"},
            org_id=org_tc.id,
            user_id=actor_id,
        )

        record_event(
            db=db,
            batch_id=b_fin2.id,
            event_type=EVENT_GENESIS_SPLIT,
            payload={"parent_batch_code": b_m1.code, "parent_batch_id": b_m1.id, "quantity": 400.0, "unit": "kg", "description": "Lô được tạo từ thao tác tách lô gộp CHE-GOP-HN01 (400 kg phân phối bán lẻ Bắc Ninh)"},
            org_id=org_tc.id,
            user_id=actor_id,
        )

        # Bàn giao b_fin1 sang Org 2 (LOG-HN)
        h1 = Handover(
            batch_id=b_fin1.id,
            from_org_id=org_tc.id,
            to_org_id=org_hn.id,
            status=HANDOVER_ACCEPTED,
        )
        db.add(h1)
        db.flush()
        record_event(
            db=db,
            batch_id=b_fin1.id,
            event_type=EVENT_HANDOVER_INIT,
            payload={"from_org": org_tc.code, "to_org": org_hn.code, "description": "Yêu cầu bàn giao sang Công ty Chế biến & Logistics Hà Nội để chế biến sâu & đóng gói chân không"},
            org_id=org_tc.id,
            user_id=actor_id,
        )
        record_event(
            db=db,
            batch_id=b_fin1.id,
            event_type=EVENT_HANDOVER_ACCEPT,
            payload={"from_org": org_tc.code, "to_org": org_hn.code, "message": "Đã tiếp nhận lô hàng tại kho logistics Gia Lâm - Hà Nội, đạt chuẩn bảo quản", "description": "Đã tiếp nhận bàn giao thành công"},
            org_id=org_hn.id,
            user_id=actor_id,
        )

        # Bàn giao b_fin2 sang Org 3 (NPP-BN)
        h2 = Handover(
            batch_id=b_fin2.id,
            from_org_id=org_tc.id,
            to_org_id=org_bn.id,
            status=HANDOVER_ACCEPTED,
        )
        db.add(h2)
        db.flush()
        record_event(
            db=db,
            batch_id=b_fin2.id,
            event_type=EVENT_HANDOVER_INIT,
            payload={"from_org": org_tc.code, "to_org": org_bn.code, "description": "Yêu cầu bàn giao trực tiếp đến Trung tâm Phân phối Nông sản Bắc Ninh"},
            org_id=org_tc.id,
            user_id=actor_id,
        )
        record_event(
            db=db,
            batch_id=b_fin2.id,
            event_type=EVENT_HANDOVER_ACCEPT,
            payload={"from_org": org_tc.code, "to_org": org_bn.code, "message": "Đã tiếp nhận nhập kho tổng Bắc Ninh và chuẩn bị đưa ra hệ thống phân phối", "description": "Đã tiếp nhận bàn giao thành công"},
            org_id=org_bn.id,
            user_id=actor_id,
        )

        # ======================================================================
        # BỔ SUNG THỰC TẾ: LÔ CHỜ DUYỆT BÀN GIAO (PENDING) ĐỂ DEMO THAO TÁC TIẾP NHẬN
        # ======================================================================
        b_pending = make_batch("CHE-CHO-TIEP-NHAN", plots[0].id, 250.0, 250.0, date(2026, 10, 8), org_tc.id, "ACTIVE")
        record_event(
            db=db,
            batch_id=b_pending.id,
            event_type=EVENT_HARVEST,
            payload={
                "batch_code": b_pending.code,
                "product_name": product_che.name,
                "harvest_date": "2026-10-08",
                "initial_quantity": 250.0,
                "quantity": 250.0,
                "unit": "kg",
                "description": "Thu hoạch bổ sung 250 kg chè búp tươi chuẩn bị chuyển tiếp",
            },
            org_id=org_tc.id,
            user_id=actor_id,
        )
        h_pending = Handover(
            batch_id=b_pending.id,
            from_org_id=org_tc.id,
            to_org_id=org_hn.id,
            status=HANDOVER_PENDING,
        )
        db.add(h_pending)
        db.flush()
        record_event(
            db=db,
            batch_id=b_pending.id,
            event_type=EVENT_HANDOVER_INIT,
            payload={"from_org": org_tc.code, "to_org": org_hn.code, "description": "Gửi yêu cầu bàn giao lô chè tươi sang Công ty Chế biến & Logistics Hà Nội, đang chờ tiếp nhận"},
            org_id=org_tc.id,
            user_id=actor_id,
        )

        # ======================================================================
        # BỔ SUNG THỰC TẾ: LÔ ĐÃ TIÊU THỤ HẾT (CONSUMED) ĐỂ MINH HỌA TRỌN VÒNG ĐỜI
        # ======================================================================
        b_consumed = make_batch("CHE-TIEU-THU-HET", plots[1].id, 200.0, 0.0, date(2026, 9, 20), org_bn.id, "CONSUMED")
        record_event(
            db=db,
            batch_id=b_consumed.id,
            event_type=EVENT_HARVEST,
            payload={
                "batch_code": b_consumed.code,
                "product_name": product_che.name,
                "harvest_date": "2026-09-20",
                "initial_quantity": 200.0,
                "quantity": 200.0,
                "unit": "kg",
                "description": "Thu hoạch 200 kg chè búp tươi theo đơn đặt hàng trước của trung tâm phân phối Bắc Ninh",
            },
            org_id=org_tc.id,
            user_id=actor_id,
        )
        h_cons = Handover(
            batch_id=b_consumed.id,
            from_org_id=org_tc.id,
            to_org_id=org_bn.id,
            status=HANDOVER_ACCEPTED,
        )
        db.add(h_cons)
        db.flush()
        record_event(
            db=db,
            batch_id=b_consumed.id,
            event_type=EVENT_HANDOVER_INIT,
            payload={"from_org": org_tc.code, "to_org": org_bn.code, "description": "Bàn giao lô đặt trước sang Trung tâm Phân phối Nông sản Bắc Ninh"},
            org_id=org_tc.id,
            user_id=actor_id,
        )
        record_event(
            db=db,
            batch_id=b_consumed.id,
            event_type=EVENT_HANDOVER_ACCEPT,
            payload={"from_org": org_tc.code, "to_org": org_bn.code, "message": "Trung tâm phân phối Bắc Ninh đã tiếp nhận nhập quầy bán lẻ", "description": "Đã tiếp nhận bàn giao thành công"},
            org_id=org_bn.id,
            user_id=actor_id,
        )
        record_event(
            db=db,
            batch_id=b_consumed.id,
            event_type=EVENT_CONSUMED,
            payload={"product_name": product_che.name, "quantity": 200.0, "unit": "kg", "description": "Đã bán lẻ toàn bộ 200 kg cho khách hàng tiêu dùng tại các siêu thị và điểm bán lẻ Bắc Ninh"},
            org_id=org_bn.id,
            user_id=actor_id,
        )

        db.commit()

    # 7. Thiết lập triggers bảo vệ tính bất biến của sự kiện
    create_event_immutability_triggers(engine)

    # 8. Tạo bảng user_sessions & sprint_demo_marker
    with engine.connect() as conn:
        conn.exec_driver_sql("""CREATE TABLE IF NOT EXISTS user_sessions (
            session_id VARCHAR(128) PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            csrf_token VARCHAR(128) NOT NULL, created_at TIMESTAMP NOT NULL,
            expires_at TIMESTAMP NOT NULL, is_revoked BOOLEAN NOT NULL DEFAULT 0)""")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_user_sessions_user_id ON user_sessions(user_id)")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_user_sessions_expires_at ON user_sessions(expires_at)")
        conn.exec_driver_sql("CREATE TABLE IF NOT EXISTS sprint_demo_marker (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.exec_driver_sql("INSERT OR REPLACE INTO sprint_demo_marker VALUES ('scope','sprint123')")
        conn.commit()

    engine.dispose()
    print(f"Hoàn thành tạo cơ sở dữ liệu mẫu miền Bắc tại: {target_path}")


if __name__ == "__main__":
    out = TRIAL / "demo_sprint123_north.db"
    build_north_db(out)
