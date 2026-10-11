"""Bộ kiểm thử toàn diện Sprint 3 (T-40, T-43, T-44, T-45, T-48, T-51, T-55).

Bao gồm:
1. test_split_batch_atomic: Tách lô nguyên tử, kiểm tra trừ khối lượng và quan hệ.
2. test_split_concurrency_race_condition: Thử nghiệm đồng thời 2 giao dịch cùng tách 1 lô (Threading Barrier).
3. test_merge_prevent_deadlock_and_diff_products: Gộp lô, chống deadlock và chặn gộp khác loại sản phẩm.
4. test_hash_integrity_after_split_merge: Kiểm tra toàn vẹn chuỗi băm của các lô sau khi tách/gộp.
5. test_bfs_trace_backwards_matches_fixture: Đối chiếu kết quả thuật toán BFS với file đáp án đếm tay.
6. test_bfs_cycle_detection: Cố ý tạo chu trình phả hệ và kiểm tra ném lỗi Cycle Detected.
7. test_ancestor_view_permissions_three_orgs: Phân quyền tổ tiên giữa 3 tổ chức.
"""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.events import verify_batch_events_integrity
from app.hash_chain import verify_batch_chain
from app.models import (
    EVENT_EXPORT_MERGE,
    EVENT_GENESIS_SPLIT,
    EVENT_HANDOVER_ACCEPT,
    EVENT_HANDOVER_INIT,
    EVENT_MERGE,
    EVENT_SPLIT,
    HANDOVER_PENDING,
    RELATION_MERGE,
    RELATION_SPLIT,
    ROLE_FARMER,
    ROLE_PROCESSOR,
    Batch,
    BatchEvent,
    BatchRelation,
    Farm,
    Handover,
    Organization,
    Plot,
    Product,
    User,
)
from app.security import hash_password
from app.seeds.seed_lineage_graph import seed_lineage_graph
from app.services.permissions import can_view_batch
from app.services.traceability import clear_trace_cache, trace_backwards
from tests.conftest import TEST_PASSWORD, TEST_USERNAME_FARMER


def _get_auth_headers(username: str = TEST_USERNAME_FARMER, password: str = TEST_PASSWORD) -> dict[str, str]:
    import base64
    credentials = f"{username}:{password}"
    encoded = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
    return {"Authorization": f"Basic {encoded}"}


def _setup_base_data(session_factory: sessionmaker[Session]) -> dict[str, int]:
    with session_factory() as session:
        # Tổ chức 1
        org = session.scalar(select(Organization).where(Organization.id == 1))
        if org is None:
            org = Organization(id=1, name="HTX Đồng Tháp", code="HTX-DT")
            session.add(org)
            session.flush()

        # Tạo user processor cho các nghiệp vụ gộp lô (MERGE) theo chuẩn RBAC 1B.1
        u_proc = session.scalar(select(User).where(User.username == "processor_user"))
        if u_proc is None:
            session.add(
                User(
                    username="processor_user",
                    email="processor@test.local",
                    password=hash_password(TEST_PASSWORD),
                    role=ROLE_PROCESSOR,
                    organization_id=org.id,
                )
            )

        product = session.scalar(select(Product).where(Product.id == 1))
        if product is None:
            product = Product(id=1, name="Xoài cát Chu", unit="kg")
            session.add(product)
            session.flush()

        farm = session.scalar(select(Farm).where(Farm.id == 1))
        if farm is None:
            farm = Farm(id=1, name="Vườn mẫu", location="Cao Lãnh", area=3.0, owner="Ông An", organization_id=org.id)
            session.add(farm)
            session.flush()

        plot = session.scalar(select(Plot).where(Plot.id == 1))
        if plot is None:
            plot = Plot(id=1, name="Thửa mẫu", location="Cao Lãnh", area=3.0, owner="Ông An", organization_id=org.id)
            session.add(plot)
            session.flush()

        batch = Batch(
            code="B-TEST-MẸ-01",
            plot_id=plot.id,
            farm_id=farm.id,
            product_id=product.id,
            product_name=product.name,
            harvest_date=date(2026, 9, 1),
            initial_quantity=Decimal("1000.00"),
            remaining_quantity=Decimal("1000.00"),
            quantity=1000.0,
            current_org_id=org.id,
            status="ACTIVE",
        )
        session.add(batch)
        session.commit()
        return {"org_id": org.id, "product_id": product.id, "batch_id": batch.id}


# ==============================================================================
# 1. TEST TÁCH LÔ NGUYÊN TỬ (T-40)
# ==============================================================================
def test_split_batch_atomic(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    data = _setup_base_data(session_factory)
    batch_id = data["batch_id"]
    headers = _get_auth_headers()

    split_payload = {
        "items": [
            {"quantity": 400.0},
            {"quantity": 600.0},
        ]
    }

    res = client.post(f"/batches/{batch_id}/split", json=split_payload, headers=headers)
    assert res.status_code == 201, res.text
    res_data = res.json()

    assert res_data["parent_batch"]["remaining_quantity"] == 0.0
    assert len(res_data["child_batches"]) == 2
    assert res_data["child_batches"][0]["initial_quantity"] == 400.0
    assert res_data["child_batches"][1]["initial_quantity"] == 600.0

    # Kiểm tra database
    with session_factory() as session:
        parent = session.get(Batch, batch_id)
        assert parent.remaining_quantity == Decimal("0.00")
        assert parent.status == "SPLIT"

        # Kiểm tra quan hệ BatchRelation
        relations = list(session.scalars(select(BatchRelation).where(BatchRelation.parent_batch_id == batch_id)).all())
        assert len(relations) == 2
        assert all(r.relation_type == RELATION_SPLIT for r in relations)
        assert {float(r.transferred_quantity) for r in relations} == {400.0, 600.0}

        # Kiểm tra hash events
        p_event_types = [e.event_type for e in parent.events]
        assert EVENT_SPLIT in p_event_types

        for c_id in [relations[0].child_batch_id, relations[1].child_batch_id]:
            child = session.get(Batch, c_id)
            c_event_types = [e.event_type for e in child.events]
            assert EVENT_GENESIS_SPLIT in c_event_types


# ==============================================================================
# 2. TEST CHỐNG RACE CONDITION KHI 2 GIAO DỊCH CÙNG TÁCH (T-42, T-43)
# ==============================================================================
def test_split_concurrency_race_condition(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    data = _setup_base_data(session_factory)
    batch_id = data["batch_id"]

    # Barrier đồng bộ hóa để 2 luồng gửi request CHÍNH XÁC cùng một thời điểm
    barrier = Barrier(2)
    results: list[int] = []

    def make_split_request() -> None:
        headers = _get_auth_headers()
        barrier.wait()  # Chờ cả 2 luồng sẵn sàng
        # Mỗi bên đòi tách 700kg từ lô 1000kg -> nếu không khóa dòng sẽ bị âm (1400kg > 1000kg)
        resp = client.post(
            f"/batches/{batch_id}/split",
            json={"items": [{"quantity": 700.0}]},
            headers=headers,
        )
        results.append(resp.status_code)

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(make_split_request)
        f2 = executor.submit(make_split_request)
        f1.result()
        f2.result()

    # Khẳng định: Chính xác 1 request thành công (201) và 1 request thất bại (400 thiếu khối lượng hoặc 409/500 do lock)
    assert 201 in results, f"Không có giao dịch nào thành công: {results}"
    assert (400 in results or 409 in results or 500 in results), f"Cả 2 bên đều thành công hoặc kết quả lạ: {results}"

    with session_factory() as session:
        parent = session.get(Batch, batch_id)
        # Khối lượng còn lại phải là 300kg (1000 - 700), tuyệt đối không được âm!
        assert parent.remaining_quantity == Decimal("300.00")
        assert parent.remaining_quantity >= Decimal("0.00")


# ==============================================================================
# 3. TEST GỘP LÔ, CHỐNG DEADLOCK & CHẶN KHÁC SẢN PHẨM (T-44, T-45)
# ==============================================================================
def test_merge_prevent_deadlock_and_diff_products(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    headers = _get_auth_headers()
    _setup_base_data(session_factory)

    with session_factory() as session:
        org = session.scalar(select(Organization).where(Organization.id == 1))
        p1 = session.scalar(select(Product).where(Product.name == "Xoài cát Chu"))
        if p1 is None:
            p1 = Product(name="Xoài cát Chu", unit="kg")
            session.add(p1)
            session.flush()

        p2 = session.scalar(select(Product).where(Product.name == "Sầu riêng Ri6"))
        if p2 is None:
            p2 = Product(name="Sầu riêng Ri6", unit="kg")
            session.add(p2)
            session.flush()

        plot = session.scalar(select(Plot).where(Plot.id == 1))

        b1 = Batch(code="B-M1", plot_id=plot.id, farm_id=plot.id, product_id=p1.id, product_name=p1.name, harvest_date=date(2026, 9, 1), initial_quantity=Decimal("500.00"), remaining_quantity=Decimal("500.00"), current_org_id=org.id)
        b2 = Batch(code="B-M2", plot_id=plot.id, farm_id=plot.id, product_id=p1.id, product_name=p1.name, harvest_date=date(2026, 9, 2), initial_quantity=Decimal("500.00"), remaining_quantity=Decimal("500.00"), current_org_id=org.id)
        b3_diff = Batch(code="B-M3-DIFF", plot_id=plot.id, farm_id=plot.id, product_id=p2.id, product_name=p2.name, harvest_date=date(2026, 9, 3), initial_quantity=Decimal("500.00"), remaining_quantity=Decimal("500.00"), current_org_id=org.id)
        session.add_all([b1, b2, b3_diff])
        session.commit()
        b1_id, b2_id, b3_id = b1.id, b2.id, b3_diff.id
        p1_id = p1.id

    # 0. Kiểm tra RBAC 1B.1: farmer không được phép thực hiện MERGE (chỉ processor)
    farmer_merge_res = client.post(
        "/batches/merge",
        json={
            "product_id": p1_id,
            "items": [
                {"parent_batch_id": b1_id, "quantity": 100.0},
                {"parent_batch_id": b2_id, "quantity": 100.0},
            ],
        },
        headers=headers,
    )
    assert farmer_merge_res.status_code == 403
    assert "không có quyền thực hiện hành động 'MERGE'" in farmer_merge_res.json()["detail"]

    headers_proc = _get_auth_headers(username="processor_user")

    # 1. Thử gộp 2 lô khác sản phẩm -> Bị chặn 400 (T-45)
    bad_res = client.post(
        "/batches/merge",
        json={
            "product_id": p1_id,
            "items": [
                {"parent_batch_id": b1_id, "quantity": 200.0},
                {"parent_batch_id": b3_id, "quantity": 200.0},
            ],
        },
        headers=headers_proc,
    )
    assert bad_res.status_code == 400
    assert "khác với mã sản phẩm" in bad_res.json()["detail"] or "sản phẩm khác" in bad_res.json()["detail"]

    # 2. Thử lấy vượt quá khối lượng còn lại -> Bị chặn 400
    over_res = client.post(
        "/batches/merge",
        json={
            "product_id": p1_id,
            "items": [
                {"parent_batch_id": b1_id, "quantity": 600.0},
                {"parent_batch_id": b2_id, "quantity": 200.0},
            ],
        },
        headers=headers_proc,
    )
    assert over_res.status_code == 400
    assert "vượt quá khối lượng" in over_res.json()["detail"]

    # 3. Gộp hợp lệ: đưa ID lộn xộn (b2_id > b1_id) để kiểm tra thuật toán sắp xếp chống deadlock (T-44)
    merge_res = client.post(
        "/batches/merge",
        json={
            "product_id": p1_id,
            "items": [
                {"parent_batch_id": max(b1_id, b2_id), "quantity": 300.0},
                {"parent_batch_id": min(b1_id, b2_id), "quantity": 200.0},
            ],
        },
        headers=headers_proc,
    )
    assert merge_res.status_code == 201, merge_res.text
    m_data = merge_res.json()
    assert m_data["merged_batch"]["initial_quantity"] == 500.0

    with session_factory() as session:
        b1_db = session.get(Batch, b1_id)
        b2_db = session.get(Batch, b2_id)
        assert b1_db.remaining_quantity == Decimal("300.00")
        assert b2_db.remaining_quantity == Decimal("200.00")

        # Kiểm tra quan hệ MERGE
        merged_id = m_data["merged_batch"]["id"]
        relations = list(session.scalars(select(BatchRelation).where(BatchRelation.child_batch_id == merged_id)).all())
        assert len(relations) == 2
        assert all(r.relation_type == RELATION_MERGE for r in relations)


# ==============================================================================
# 4. TEST TOÀN VẸN HASH-CHAIN SAU KHI TÁCH/GỘP (T-48)
# ==============================================================================
def test_hash_integrity_after_split_merge(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    data = _setup_base_data(session_factory)
    parent_id = data["batch_id"]
    headers = _get_auth_headers()

    # Tách lô
    split_res = client.post(
        f"/batches/{parent_id}/split",
        json={"items": [{"quantity": 500.0}, {"quantity": 500.0}]},
        headers=headers,
    )
    assert split_res.status_code == 201
    c1_id = split_res.json()["child_batches"][0]["id"]
    c2_id = split_res.json()["child_batches"][1]["id"]

    # Gộp 2 lô con (thực hiện bởi processor)
    headers_proc = _get_auth_headers(username="processor_user")
    merge_res = client.post(
        "/batches/merge",
        json={
            "product_id": data["product_id"],
            "items": [
                {"parent_batch_id": c1_id, "quantity": 250.0},
                {"parent_batch_id": c2_id, "quantity": 250.0},
            ],
        },
        headers=headers_proc,
    )
    assert merge_res.status_code == 201
    merged_id = merge_res.json()["merged_batch"]["id"]

    # Xác minh tính toàn vẹn hash-chain trên TẤT CẢ các lô liên quan (T-48)
    with session_factory() as session:
        for b_id in [parent_id, c1_id, c2_id, merged_id]:
            integ = verify_batch_events_integrity(session, b_id)
            assert integ["valid"] is True, f"Hash-chain của lô {b_id} không hợp lệ: {integ}"

            chain_check = verify_batch_chain(session, b_id)
            assert chain_check["is_valid"] is True, f"Verify chain failed cho lô {b_id}: {chain_check}"

        # Sự kiện phải được ghi lên chuỗi băm của TẤT CẢ lô liên quan (T-47)
        parent_events = [e.event_type for e in session.get(Batch, parent_id).events]
        assert EVENT_SPLIT in parent_events, "Lô mẹ phải có sự kiện SPLIT trên chuỗi băm."

        for child_id in (c1_id, c2_id):
            child_events = [e.event_type for e in session.get(Batch, child_id).events]
            assert EVENT_GENESIS_SPLIT in child_events, "Lô con phải có sự kiện GENESIS_SPLIT."
            # Lô con vừa là nguồn gộp -> phải có sự kiện EXPORT_MERGE trên chính chuỗi của nó
            assert EVENT_EXPORT_MERGE in child_events, "Lô mẹ-gộp phải có sự kiện EXPORT_MERGE."

        merged_events = [e.event_type for e in session.get(Batch, merged_id).events]
        assert EVENT_MERGE in merged_events, "Lô gộp phải có sự kiện MERGE trên chuỗi băm."


# ==============================================================================
# 5. TEST BFS TRUY NGƯỢC SO KHỚP FIXTURE ĐÁP ÁN ĐẾM TAY (T-51)
# ==============================================================================
def test_bfs_trace_backwards_matches_fixture(session_factory: sessionmaker[Session]) -> None:
    # 1. Khởi tạo đồ thị mẫu 3 tầng
    with session_factory() as session:
        batch_codes_map = seed_lineage_graph(session)

    # 2. Đọc file đáp án đếm tay
    fixture_path = Path(__file__).parent / "fixtures" / "lineage_fixture_answers.json"
    assert fixture_path.exists(), f"Không tìm thấy file fixture tại {fixture_path}"
    with open(fixture_path, "r", encoding="utf-8") as f:
        answers = json.load(f)

    # 3. So khớp 100% từng lô
    with session_factory() as session:
        clear_trace_cache()
        for code, expected in answers.items():
            b_id = batch_codes_map[code]
            result = trace_backwards(session, b_id, use_cache=False)

            # So khớp danh sách roots
            actual_roots = [r["code"] for r in result["root_batches"]]
            assert sorted(actual_roots) == sorted(expected["roots"]), (
                f"Lô {code}: Root batches thực tế {actual_roots} khác đáp án {expected['roots']}"
            )

            # So khớp danh sách tổ tiên theo tầng
            expected_levels = expected.get("levels", {})
            actual_levels = {
                str(lvl): [node["code"] for node in nodes]
                for lvl, nodes in result["ancestors_by_level"].items()
            }

            for lvl_str, exp_codes in expected_levels.items():
                act_codes = actual_levels.get(lvl_str, [])
                assert sorted(act_codes) == sorted(exp_codes), (
                    f"Lô {code} Tầng {lvl_str}: Thực tế {act_codes} khác đáp án {exp_codes}"
                )


# ==============================================================================
# 6. TEST PHÁT HIỆN CHU TRÌNH PHẢ HỆ (CYCLE DETECTION - T-51)
# ==============================================================================
def test_bfs_cycle_detection(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        batch_codes_map = seed_lineage_graph(session)
        root_id = batch_codes_map["B-ROOT-01"]
        final_id = batch_codes_map["B-FINAL-01"]

        # Cố ý chèn quan hệ chu trình bất thường: final_id lại là cha của root_id (vòng lặp!)
        cyclic_rel = BatchRelation(
            parent_batch_id=final_id,
            child_batch_id=root_id,
            transferred_quantity=Decimal("10.00"),
            relation_type="SPLIT",
        )
        session.add(cyclic_rel)
        session.commit()

        clear_trace_cache()
        # Chạy BFS từ final_id -> phải phát hiện chu trình và ném lỗi 400
        with pytest.raises(Exception) as exc_info:
            trace_backwards(session, final_id, use_cache=False)

        assert "Cycle detected" in str(exc_info.value.detail)
        assert "chu trình phả hệ bất thường" in str(exc_info.value.detail).lower()


# ==============================================================================
# 7. TEST PHÂN QUYỀN TỔ TIÊN GIỮA 3 TỔ CHỨC (T-54, T-55)
# ==============================================================================
def test_ancestor_view_permissions_three_orgs(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        batch_codes_map = seed_lineage_graph(session)
        org1 = session.scalar(select(Organization).where(Organization.code == "HTX-DT"))
        org2 = session.scalar(select(Organization).where(Organization.code == "HTX-TG"))
        org3 = session.scalar(select(Organization).where(Organization.code == "DN-XNK"))

        org1_id, org2_id, org3_id = org1.id, org2.id, org3.id

        fin1_id = batch_codes_map["B-FINAL-01"]  # Đang ở Org 2
        fin2_id = batch_codes_map["B-FINAL-02"]  # Đang ở Org 3
        root1_id = batch_codes_map["B-ROOT-01"]  # Tổ tiên gốc của fin1 và fin2
        root2_id = batch_codes_map["B-ROOT-02"]  # Tổ tiên gốc của fin1 và fin2
        m3_id = batch_codes_map["B-MERGE-03"]    # Thuộc Org 1, KHÔNG liên quan đến fin2

    with session_factory() as session:
        # Org 3 (DN-XNK) đang giữ B-FINAL-02 -> Có quyền xem fin2
        assert can_view_batch(session, org3_id, fin2_id) is True

        # Org 3 CÓ QUYỀN xem B-ROOT-01 và B-ROOT-02 vì là tổ tiên của B-FINAL-02 (T-54)
        assert can_view_batch(session, org3_id, root1_id) is True
        assert can_view_batch(session, org3_id, root2_id) is True

        # Org 3 KHÔNG CÓ QUYỀN xem B-MERGE-03 của Org 1 vì không liên quan phả hệ! (T-55)
        assert can_view_batch(session, org3_id, m3_id) is False

    # Kiểm tra qua API với tài khoản distributor (thuộc Org 3)
    headers_org3 = _get_auth_headers("distributor", "123456")

    # Xem summary của tổ tiên B-ROOT-01 -> Thành công (200)
    res_anc = client.get(f"/batches/{root1_id}/summary", headers=headers_org3)
    assert res_anc.status_code == 200

    # Xem summary của lô không liên quan B-MERGE-03 -> Bị chặn (403 Forbidden)
    res_unrelated = client.get(f"/batches/{m3_id}/summary", headers=headers_org3)
    assert res_unrelated.status_code == 403


# ==============================================================================
# 8. TEST CHI TIẾT LÔ TRUNG TÂM (T-58, S-25): GET /batches/{id}/summary
# ==============================================================================
def test_batch_summary_detail_endpoint(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    """S-25/T-58: Endpoint tổng hợp trả đủ sản phẩm, khối lượng còn lại, đơn vị giữ, cha/con trực tiếp và cờ hành động."""
    with session_factory() as session:
        batch_codes_map = seed_lineage_graph(session)
        org_tg = session.scalar(select(Organization).where(Organization.code == "HTX-TG"))

        # Tạo tài khoản đại diện Org 2 (bên đang nắm giữ B-FINAL-01)
        if session.scalar(select(User).where(User.username == "farmer_tg")) is None:
            session.add(
                User(
                    username="farmer_tg",
                    password=hash_password("123456"),
                    role=ROLE_FARMER,
                    organization_id=org_tg.id,
                )
            )
            session.commit()

        fin1_id = batch_codes_map["B-FINAL-01"]

    headers_org2 = _get_auth_headers("farmer_tg", "123456")

    res = client.get(f"/batches/{fin1_id}/summary", headers=headers_org2)
    assert res.status_code == 200, res.text
    data = res.json()

    # 1. Thông tin lô trung tâm: sản phẩm, khối lượng còn lại, đơn vị đang giữ
    assert data["batch"]["product_name"] == "Xoài cát Chu"
    assert data["batch"]["remaining_quantity"] == 500.0
    assert data["current_org"]["code"] == "HTX-TG"
    assert data["plot"]["name"] is not None

    # 2. Cha trực tiếp phải là B-MERGE-01 (lô bị tách để sinh ra B-FINAL-01), không có con
    parent_codes = [p["code"] for p in data["direct_parents"]]
    assert "B-MERGE-01" in parent_codes
    assert data["direct_children"] == []

    # 3. Lô ACTIVE, còn khối lượng, đúng chủ sở hữu -> cho phép tách / bàn giao
    assert data["has_pending_handover"] is False
    assert data["can_split"] is True
    assert data["can_handover"] is True

    # 4. Tổ chức xa lạ (không liên quan phả hệ) không được xem chi tiết -> 403
    with session_factory() as session:
        stranger = Organization(name="Công ty Lạ", code="ORG-LA")
        session.add(stranger)
        session.flush()
        session.add(
            User(
                username="stranger",
                password=hash_password("123456"),
                role=ROLE_FARMER,
                organization_id=stranger.id,
            )
        )
        session.commit()

    res_forbidden = client.get(f"/batches/{fin1_id}/summary", headers=_get_auth_headers("stranger", "123456"))
    assert res_forbidden.status_code == 403


# ==============================================================================
# 9. TEST CẢNH BÁO BÀN GIAO QUÁ HẠN 48H CHO CẢ HAI BÊN (T-56, T-57, S-24)
# ==============================================================================
def test_overdue_handover_flagged_both_sides(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    """S-24: Bàn giao PENDING quá 48h phải được gắn cờ is_overdue thấy được ở cả bên gửi lẫn bên nhận."""
    data = _setup_base_data(session_factory)
    batch_id = data["batch_id"]
    org1_id = data["org_id"]

    with session_factory() as session:
        org2 = Organization(name="HTX Tiếp Nhận", code="HTX-NHAN")
        session.add(org2)
        session.flush()
        session.add(
            User(
                username="receiver",
                password=hash_password("123456"),
                role=ROLE_FARMER,
                organization_id=org2.id,
            )
        )
        # Yêu cầu bàn giao đã gửi cách đây 50 giờ (vượt ngưỡng 48h)
        overdue_created = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=50)
        handover = Handover(
            batch_id=batch_id,
            from_org_id=org1_id,
            to_org_id=org2.id,
            status=HANDOVER_PENDING,
            created_at=overdue_created,
        )
        session.add(handover)
        session.commit()
        handover_id = handover.id
        org2_id = org2.id

    headers_sender = _get_auth_headers()  # farmer thuộc Org 1 (bên gửi)
    headers_receiver = _get_auth_headers("receiver", "123456")  # thuộc Org 2 (bên nhận)

    # 1. Quét quá hạn -> gắn cờ is_overdue
    scan = client.post("/handovers/check-overdue", headers=headers_sender)
    assert scan.status_code == 200
    assert scan.json()["overdue_count"] >= 1

    # 2. Bên NHẬN thấy cờ quá hạn trong danh sách chờ duyệt
    pending = client.get("/handovers/pending", headers=headers_receiver)
    assert pending.status_code == 200
    item = next(h for h in pending.json() if h["id"] == handover_id)
    assert item["is_overdue"] is True

    # 3. Bên GỬI thấy cờ quá hạn ngay trên danh sách lô của mình (pending_handover kèm is_overdue)
    batches = client.get("/batches", headers=headers_sender)
    assert batches.status_code == 200
    b_item = next(b for b in batches.json() if b["id"] == batch_id)
    assert b_item["is_pending"] is True
    assert b_item["pending_handover"] is not None
    assert b_item["pending_handover"]["is_overdue"] is True

    # 4. Xác nhận muộn -> sự kiện HANDOVER_ACCEPT phải ghi chú quá hạn để lưu vết minh bạch
    accept = client.post(f"/handovers/{handover_id}/accept", headers=headers_receiver)
    assert accept.status_code == 200

    with session_factory() as session:
        accept_ev = session.scalar(
            select(BatchEvent).where(
                BatchEvent.batch_id == batch_id,
                BatchEvent.event_type == EVENT_HANDOVER_ACCEPT,
            )
        )
        assert accept_ev is not None
        assert accept_ev.payload.get("is_overdue") is True

        batch_db = session.get(Batch, batch_id)
        assert batch_db.current_org_id == org2_id


# ==============================================================================
# 10. TEST LÔ NHẬN VỀ TỪ TỔ CHỨC KHÁC VẪN XEM ĐƯỢC LỊCH SỬ TRƯỚC ĐÓ (S-23, T-54)
# ==============================================================================
def test_received_batch_history_visible_to_new_owner(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    """S-23: Tổ chức nhận lô vẫn truy được toàn bộ lịch sử (sự kiện) do tổ chức cũ ghi trước đó."""
    with session_factory() as session:
        batch_codes_map = seed_lineage_graph(session)
        fin2_id = batch_codes_map["B-FINAL-02"]  # HTX-DT bàn giao cho DN-XNK (Org 3)

    headers_org3 = _get_auth_headers("distributor", "123456")

    res = client.get(f"/batches/{fin2_id}/events", headers=headers_org3)
    assert res.status_code == 200
    event_types = {e["event_type"] for e in res.json()}

    # Phải thấy được sự kiện khởi tạo tách (do Org 1 ghi) và chuỗi bàn giao (Org 1 -> Org 3)
    assert EVENT_GENESIS_SPLIT in event_types
    assert EVENT_HANDOVER_INIT in event_types
    assert EVENT_HANDOVER_ACCEPT in event_types
