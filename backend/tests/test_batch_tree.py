"""Bộ kiểm thử cho Task T-58: Truy vấn tổng hợp chi tiết lô kèm lô mẹ và lô con trực tiếp."""

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.batch_tree import build_batch_tree_response, get_batch_with_direct_relations
from app.models import Batch
from tests.conftest import TEST_PASSWORD, TEST_USERNAME_FARMER


def _get_farmer_auth_headers() -> dict[str, str]:
    import base64

    credentials = f"{TEST_USERNAME_FARMER}:{TEST_PASSWORD}"
    encoded = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
    return {"Authorization": f"Basic {encoded}"}


def _create_farm(client: TestClient) -> int:
    headers = _get_farmer_auth_headers()
    res = client.post(
        "/farms",
        json={
            "name": "Nông trường Thử nghiệm T-58",
            "location": "Tháp Mười, Đồng Tháp",
            "area": 5.0,
            "owner": "HTX Đồng Tháp",
        },
        headers=headers,
    )
    return res.json()["id"]


def test_t58_batch_khong_ton_tai(client: TestClient) -> None:
    """Test 4 – Lô không tồn tại: Gọi API /batches/99999/tree phải trả về HTTP 404 Not Found."""
    res = client.get("/batches/99999/tree")
    assert res.status_code == 404
    assert "Không tìm thấy" in res.json()["detail"]


def test_t58_lo_khong_co_parent_va_khong_co_child(client: TestClient) -> None:
    """Test 2 & 3 – Lô không có parent và không có child: `parent` = null và `children` = []."""
    headers = _get_farmer_auth_headers()
    farm_id = _create_farm(client)

    batch_res = client.post(
        "/batches",
        json={
            "farm_id": farm_id,
            "product_name": "Xoài Cát Chu T58 Độc Lập",
            "quantity": 800.0,
            "harvest_date": "2026-06-01",
        },
        headers=headers,
    )
    batch_id = batch_res.json()["id"]

    res = client.get(f"/batches/{batch_id}/tree")
    assert res.status_code == 200
    data = res.json()

    assert data["batch"]["id"] == batch_id
    assert data["batch"]["product"] == "Xoài Cát Chu T58 Độc Lập"
    assert data["batch"]["remaining_quantity"] == 800.0
    assert data["batch"]["unit"] == "kg"
    assert data["parent"] is None
    assert data["children"] == []


def test_t58_cay_da_the_he_chi_tra_ve_truc_tiep(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """Test 1 & 5 – Cây đa thế hệ (Ông -> Mẹ -> Lô mục tiêu -> Con -> Cháu):
    Đảm bảo chỉ trả về parent TRỰC TIẾP và children TRỰC TIẾP, hoàn toàn không lẫn thế hệ xa hơn.
    """
    headers = _get_farmer_auth_headers()
    farm_id = _create_farm(client)
    today = date(2026, 6, 15)

    # 1. Tạo Lô Ông (Grandparent - ID #100)
    res_gp = client.post(
        "/batches",
        json={
            "farm_id": farm_id,
            "product_name": "Lô Ông (Grandparent)",
            "quantity": 10000.0,
            "harvest_date": "2026-06-01",
        },
        headers=headers,
    )
    gp_id = res_gp.json()["id"]

    # 2. Xây dựng cây quan hệ 4 thế hệ trong DB
    with session_factory() as session:
        # Lô Mẹ (Parent - ID #200) thuộc Lô Ông
        parent_batch = Batch(
            farm_id=farm_id,
            product_name="Lô Mẹ trực tiếp (Parent)",
            quantity=5000.0,
            remaining_quantity=4500.0,
            harvest_date=today,
            parent_id=gp_id,
            status="Đang phân loại",
        )
        session.add(parent_batch)
        session.commit()
        parent_id = parent_batch.id

        # Lô Mục tiêu (Target - ID #300) thuộc Lô Mẹ
        target_batch = Batch(
            farm_id=farm_id,
            product_name="Lô Mục tiêu (Target Batch)",
            quantity=2000.0,
            remaining_quantity=1800.0,
            harvest_date=today,
            parent_id=parent_id,
            status="Đang lưu kho",
        )
        session.add(target_batch)
        session.commit()
        target_id = target_batch.id

        # Lô Con 1 & Lô Con 2 trực tiếp thuộc Lô Mục tiêu
        child1 = Batch(
            farm_id=farm_id,
            product_name="Lô Con 1 trực tiếp (Child 1)",
            quantity=800.0,
            remaining_quantity=800.0,
            harvest_date=today,
            parent_id=target_id,
            status="Đang đóng gói",
        )
        child2 = Batch(
            farm_id=farm_id,
            product_name="Lô Con 2 trực tiếp (Child 2)",
            quantity=700.0,
            remaining_quantity=700.0,
            harvest_date=today,
            parent_id=target_id,
            status="Đang vận chuyển",
        )
        session.add_all([child1, child2])
        session.commit()
        c1_id = child1.id
        c2_id = child2.id

        # Lô Cháu (Grandchild) thuộc Lô Con 1
        grandchild = Batch(
            farm_id=farm_id,
            product_name="Lô Cháu (Grandchild - Con của Child 1)",
            quantity=300.0,
            remaining_quantity=300.0,
            harvest_date=today,
            parent_id=c1_id,
            status="Xuất bán lẻ",
        )
        session.add(grandchild)
        session.commit()
        gc_id = grandchild.id

    # 3. Gọi API kiểm tra Lô Mục tiêu (`target_id`)
    res = client.get(f"/batches/{target_id}/tree")
    assert res.status_code == 200
    data = res.json()

    # Kiểm tra Lô mục tiêu
    assert data["batch"]["id"] == target_id
    assert data["batch"]["product"] == "Lô Mục tiêu (Target Batch)"
    assert data["batch"]["remaining_quantity"] == 1800.0

    # KIỂM TRA LÔ MẸ TRỰC TIẾP: Chỉ là parent_id (#200), KHÔNG PHẢI gp_id (#100)
    assert data["parent"] is not None
    assert data["parent"]["id"] == parent_id
    assert data["parent"]["id"] != gp_id
    assert data["parent"]["product"] == "Lô Mẹ trực tiếp (Parent)"

    # KIỂM TRA LÔ CON TRỰC TIẾP: Chỉ gồm c1_id (#401) và c2_id (#402), KHÔNG BAO GỒM gc_id (#501)
    assert len(data["children"]) == 2
    child_ids = [c["id"] for c in data["children"]]
    assert c1_id in child_ids
    assert c2_id in child_ids
    assert gc_id not in child_ids

    # 4. Kiểm tra trực tiếp hàm Python get_batch_with_direct_relations & build_batch_tree_response
    with session_factory() as session:
        batch_orm = get_batch_with_direct_relations(session, target_id)
        assert batch_orm is not None
        dict_tree = build_batch_tree_response(batch_orm)
        assert dict_tree["parent"]["id"] == parent_id
        assert len(dict_tree["children"]) == 2
        assert gc_id not in [c["id"] for c in dict_tree["children"]]
