"""Kiểm thử tối ưu hóa thuật toán BFS phả hệ hậu duệ (S-26 / SCRUM-63).

Các trường hợp kiểm thử bắt buộc:
1. Đồ thị không có hậu duệ (Target batch không có con -> terminal batch chính là target).
2. Đồ thị phân nhánh và gộp hình thoi (Diamond DAG & Multi-parent): không trùng lặp node trong cùng thế hệ,
   không đếm sai total_descendants.
3. Phát hiện chu trình phả hệ có hướng (Directed cycle detection):
   - Chu trình trực tiếp (A -> B -> A).
   - Chu trình gián tiếp đa tầng (A -> B -> C -> A).
   - Chu trình trong đồ thị nhiều cha (A -> B1 -> C, A -> B2 -> C, C -> B1).
4. Lô CONSUMED: Dừng không mở rộng các nhánh con của lô đã tiêu thụ, phản ánh remaining_quantity=0, nằm trong terminal_batches.
5. Kiểm soát giới hạn max_nodes: Dừng an toàn khi đạt ngưỡng quy định.
6. Benchmark hiệu năng 1.000 nút trên SQLite thử nghiệm riêng: Thời gian thực thi < 2.0 giây.
"""

from datetime import date
from decimal import Decimal
import time
import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    BATCH_STATUS_ACTIVE,
    BATCH_STATUS_CONSUMED,
    RELATION_MERGE,
    RELATION_SPLIT,
    Batch,
    BatchRelation,
    Farm,
    Organization,
    Plot,
    Product,
)
from app.services.traceability import clear_trace_cache, trace_forward


@pytest.fixture()
def s26_base_fixture(session_factory: sessionmaker[Session]) -> dict[str, int]:
    """Tạo tổ chức, nông trại, thửa đất và sản phẩm cơ sở cho kiểm thử S-26."""
    with session_factory() as session:
        org = Organization(
            name="Hợp tác xã Nông nghiệp S26",
            code="HTX-S26",
            description="Tổ chức phục vụ test S-26",
        )
        session.add(org)
        session.flush()

        farm = Farm(
            name="Nông trại Thử nghiệm S26",
            location="Khu thực nghiệm Cao Lãnh, Đồng Tháp",
            area=10.0,
            owner="Nguyễn Văn A",
            organization_id=org.id,
        )
        session.add(farm)
        session.flush()

        plot = Plot(
            name="Thửa Thử nghiệm S26-P01",
            organization_id=org.id,
            area=2.5,
            location="Khu thực nghiệm Cao Lãnh, Đồng Tháp",
            owner="Nguyễn Văn A",
        )
        product = Product(
            name="Xoài Cát Chu VietGAP S26",
            unit="kg",
        )
        session.add_all([plot, product])
        session.commit()

        return {
            "org_id": org.id,
            "farm_id": farm.id,
            "plot_id": plot.id,
            "product_id": product.id,
        }


def test_s26_no_descendants(session_factory: sessionmaker[Session], s26_base_fixture: dict[str, int]):
    """Test 1: Lô gốc không có bất kỳ con nào -> total_descendants=0, terminal_batches=[target_batch]."""
    clear_trace_cache()
    with session_factory() as session:
        root = Batch(
            code="S26-SOLO-01",
            plot_id=s26_base_fixture["plot_id"],
            product_id=s26_base_fixture["product_id"],
            harvest_date=date(2026, 10, 1),
            initial_quantity=Decimal("500.00"),
            remaining_quantity=Decimal("500.00"),
            current_org_id=s26_base_fixture["org_id"],
            status=BATCH_STATUS_ACTIVE,
        )
        session.add(root)
        session.commit()

        result = trace_forward(session, root.id, use_cache=False)
        assert result["total_descendants"] == 0
        assert result["descendants_by_level"] == {}
        assert len(result["terminal_batches"]) == 1
        assert result["terminal_batches"][0]["batch_id"] == root.id
        assert result["terminal_batches"][0]["code"] == "S26-SOLO-01"


def test_s26_diamond_and_multiparent_deduplication(
    session_factory: sessionmaker[Session], s26_base_fixture: dict[str, int]
):
    """Test 2: Đồ thị hình thoi (Diamond) và nhiều cha (Multi-parent):
    Root A -> {B1, B2} (tách - Tầng 1)
    {B1, B2} -> C1 (gộp - Tầng 2)
    C1 -> {D1, D2} (tách - Tầng 3)
    Yêu cầu:
    - C1 chỉ xuất hiện ĐÚNG 1 LẦN trong descendants_by_level[2].
    - D1, D2 chỉ xuất hiện ĐÚNG 1 LẦN trong descendants_by_level[3].
    - total_descendants == 5 (B1, B2, C1, D1, D2).
    - terminal_batches == [D1, D2].
    """
    clear_trace_cache()
    p_id = s26_base_fixture["plot_id"]
    prd_id = s26_base_fixture["product_id"]
    org_id = s26_base_fixture["org_id"]

    with session_factory() as session:
        root = Batch(code="S26-DIA-ROOT", plot_id=p_id, product_id=prd_id, harvest_date=date(2026, 10, 1),
                     initial_quantity=Decimal("1000.00"), remaining_quantity=Decimal("1000.00"),
                     current_org_id=org_id, status=BATCH_STATUS_ACTIVE)
        session.add(root)
        session.flush()

        b1 = Batch(code="S26-DIA-B1", plot_id=p_id, product_id=prd_id, harvest_date=date(2026, 10, 2),
                   initial_quantity=Decimal("400.00"), remaining_quantity=Decimal("400.00"),
                   current_org_id=org_id, status=BATCH_STATUS_ACTIVE)
        b2 = Batch(code="S26-DIA-B2", plot_id=p_id, product_id=prd_id, harvest_date=date(2026, 10, 2),
                   initial_quantity=Decimal("600.00"), remaining_quantity=Decimal("600.00"),
                   current_org_id=org_id, status=BATCH_STATUS_ACTIVE)
        session.add_all([b1, b2])
        session.flush()

        session.add_all([
            BatchRelation(parent_batch_id=root.id, child_batch_id=b1.id,
                          transferred_quantity=Decimal("400.00"), relation_type=RELATION_SPLIT),
            BatchRelation(parent_batch_id=root.id, child_batch_id=b2.id,
                          transferred_quantity=Decimal("600.00"), relation_type=RELATION_SPLIT),
        ])
        session.flush()

        c1 = Batch(code="S26-DIA-C1", plot_id=p_id, product_id=prd_id, harvest_date=date(2026, 10, 3),
                   initial_quantity=Decimal("1000.00"), remaining_quantity=Decimal("1000.00"),
                   current_org_id=org_id, status=BATCH_STATUS_ACTIVE)
        session.add(c1)
        session.flush()

        session.add_all([
            BatchRelation(parent_batch_id=b1.id, child_batch_id=c1.id,
                          transferred_quantity=Decimal("400.00"), relation_type=RELATION_MERGE),
            BatchRelation(parent_batch_id=b2.id, child_batch_id=c1.id,
                          transferred_quantity=Decimal("600.00"), relation_type=RELATION_MERGE),
        ])
        session.flush()

        d1 = Batch(code="S26-DIA-D1", plot_id=p_id, product_id=prd_id, harvest_date=date(2026, 10, 4),
                   initial_quantity=Decimal("500.00"), remaining_quantity=Decimal("500.00"),
                   current_org_id=org_id, status=BATCH_STATUS_ACTIVE)
        d2 = Batch(code="S26-DIA-D2", plot_id=p_id, product_id=prd_id, harvest_date=date(2026, 10, 4),
                   initial_quantity=Decimal("500.00"), remaining_quantity=Decimal("500.00"),
                   current_org_id=org_id, status=BATCH_STATUS_ACTIVE)
        session.add_all([d1, d2])
        session.flush()

        session.add_all([
            BatchRelation(parent_batch_id=c1.id, child_batch_id=d1.id,
                          transferred_quantity=Decimal("500.00"), relation_type=RELATION_SPLIT),
            BatchRelation(parent_batch_id=c1.id, child_batch_id=d2.id,
                          transferred_quantity=Decimal("500.00"), relation_type=RELATION_SPLIT),
        ])
        session.commit()

        res = trace_forward(session, root.id, use_cache=False)

        assert res["total_descendants"] == 5
        assert len(res["descendants_by_level"][1]) == 2
        assert len(res["descendants_by_level"][2]) == 1  # C1 không bị duplicate!
        assert res["descendants_by_level"][2][0]["code"] == "S26-DIA-C1"
        assert len(res["descendants_by_level"][3]) == 2

        term_codes = [t["code"] for t in res["terminal_batches"]]
        assert sorted(term_codes) == ["S26-DIA-D1", "S26-DIA-D2"]


def test_s26_cycle_detection_direct_and_indirect(
    session_factory: sessionmaker[Session], s26_base_fixture: dict[str, int]
):
    """Test 3: Phát hiện chu trình phả hệ có hướng:
    3.1. Chu trình trực tiếp (A -> B -> A).
    3.2. Chu trình gián tiếp 3 tầng (A -> B -> C -> A).
    3.3. Chu trình trong đồ thị nhiều cha (A -> B1 -> C, A -> B2 -> C, và C -> B1).
    """
    clear_trace_cache()
    p_id = s26_base_fixture["plot_id"]
    prd_id = s26_base_fixture["product_id"]
    org_id = s26_base_fixture["org_id"]

    # 3.1. Chu trình trực tiếp
    with session_factory() as session:
        r1 = Batch(code="CYC-DIR-ROOT", plot_id=p_id, product_id=prd_id, harvest_date=date(2026, 10, 1),
                   initial_quantity=Decimal("100.00"), remaining_quantity=Decimal("100.00"),
                   current_org_id=org_id, status=BATCH_STATUS_ACTIVE)
        c1 = Batch(code="CYC-DIR-C1", plot_id=p_id, product_id=prd_id, harvest_date=date(2026, 10, 2),
                   initial_quantity=Decimal("100.00"), remaining_quantity=Decimal("100.00"),
                   current_org_id=org_id, status=BATCH_STATUS_ACTIVE)
        session.add_all([r1, c1])
        session.flush()

        session.add_all([
            BatchRelation(parent_batch_id=r1.id, child_batch_id=c1.id,
                          transferred_quantity=Decimal("100.00"), relation_type=RELATION_SPLIT),
            BatchRelation(parent_batch_id=c1.id, child_batch_id=r1.id,
                          transferred_quantity=Decimal("100.00"), relation_type=RELATION_SPLIT),
        ])
        session.commit()

        with pytest.raises(HTTPException) as exc_info:
            trace_forward(session, r1.id, use_cache=False)
        assert exc_info.value.status_code == 400
        assert "Cycle detected" in exc_info.value.detail or "chu trình" in exc_info.value.detail.lower()

    # 3.2. Chu trình gián tiếp đa tầng: A -> B -> C -> D -> A
    with session_factory() as session:
        a = Batch(code="CYC-IND-A", plot_id=p_id, product_id=prd_id, harvest_date=date(2026, 10, 1),
                  initial_quantity=Decimal("100.00"), remaining_quantity=Decimal("100.00"),
                  current_org_id=org_id, status=BATCH_STATUS_ACTIVE)
        b = Batch(code="CYC-IND-B", plot_id=p_id, product_id=prd_id, harvest_date=date(2026, 10, 2),
                  initial_quantity=Decimal("100.00"), remaining_quantity=Decimal("100.00"),
                  current_org_id=org_id, status=BATCH_STATUS_ACTIVE)
        c = Batch(code="CYC-IND-C", plot_id=p_id, product_id=prd_id, harvest_date=date(2026, 10, 3),
                  initial_quantity=Decimal("100.00"), remaining_quantity=Decimal("100.00"),
                  current_org_id=org_id, status=BATCH_STATUS_ACTIVE)
        session.add_all([a, b, c])
        session.flush()

        session.add_all([
            BatchRelation(parent_batch_id=a.id, child_batch_id=b.id,
                          transferred_quantity=Decimal("100.00"), relation_type=RELATION_SPLIT),
            BatchRelation(parent_batch_id=b.id, child_batch_id=c.id,
                          transferred_quantity=Decimal("100.00"), relation_type=RELATION_SPLIT),
            BatchRelation(parent_batch_id=c.id, child_batch_id=a.id,
                          transferred_quantity=Decimal("100.00"), relation_type=RELATION_SPLIT),
        ])
        session.commit()

        with pytest.raises(HTTPException) as exc_info2:
            trace_forward(session, a.id, use_cache=False)
        assert exc_info2.value.status_code == 400
        assert "Cycle detected" in exc_info2.value.detail or "chu trình" in exc_info2.value.detail.lower()

    # 3.3. Chu trình trong đồ thị nhiều cha: Root -> B1 -> C, Root -> B2 -> C, và C -> B1
    with session_factory() as session:
        r3 = Batch(code="CYC-MP-ROOT", plot_id=p_id, product_id=prd_id, harvest_date=date(2026, 10, 1),
                   initial_quantity=Decimal("100.00"), remaining_quantity=Decimal("100.00"),
                   current_org_id=org_id, status=BATCH_STATUS_ACTIVE)
        b1 = Batch(code="CYC-MP-B1", plot_id=p_id, product_id=prd_id, harvest_date=date(2026, 10, 2),
                   initial_quantity=Decimal("50.00"), remaining_quantity=Decimal("50.00"),
                   current_org_id=org_id, status=BATCH_STATUS_ACTIVE)
        b2 = Batch(code="CYC-MP-B2", plot_id=p_id, product_id=prd_id, harvest_date=date(2026, 10, 2),
                   initial_quantity=Decimal("50.00"), remaining_quantity=Decimal("50.00"),
                   current_org_id=org_id, status=BATCH_STATUS_ACTIVE)
        c = Batch(code="CYC-MP-C", plot_id=p_id, product_id=prd_id, harvest_date=date(2026, 10, 3),
                  initial_quantity=Decimal("100.00"), remaining_quantity=Decimal("100.00"),
                  current_org_id=org_id, status=BATCH_STATUS_ACTIVE)
        session.add_all([r3, b1, b2, c])
        session.flush()

        session.add_all([
            BatchRelation(parent_batch_id=r3.id, child_batch_id=b1.id,
                          transferred_quantity=Decimal("50.00"), relation_type=RELATION_SPLIT),
            BatchRelation(parent_batch_id=r3.id, child_batch_id=b2.id,
                          transferred_quantity=Decimal("50.00"), relation_type=RELATION_SPLIT),
            BatchRelation(parent_batch_id=b1.id, child_batch_id=c.id,
                          transferred_quantity=Decimal("50.00"), relation_type=RELATION_MERGE),
            BatchRelation(parent_batch_id=b2.id, child_batch_id=c.id,
                          transferred_quantity=Decimal("50.00"), relation_type=RELATION_MERGE),
            # Tạo chu trình: C quay lại con trỏ vào B1
            BatchRelation(parent_batch_id=c.id, child_batch_id=b1.id,
                          transferred_quantity=Decimal("20.00"), relation_type=RELATION_SPLIT),
        ])
        session.commit()

        with pytest.raises(HTTPException) as exc_info3:
            trace_forward(session, r3.id, use_cache=False)
        assert exc_info3.value.status_code == 400
        assert "Cycle detected" in exc_info3.value.detail or "chu trình" in exc_info3.value.detail.lower()

    # 3.4. Test đối kháng: Chu trình phức tạp đa tầng có đường đi hội tụ chéo mức
    # Root A -> B1 -> D -> E
    # Root A -> B2 -> X -> Y -> D
    # Cạnh nối ngược: E -> Y tạo thành chu trình có hướng D -> E -> Y -> D
    with session_factory() as session:
        r4 = Batch(code="ADV-ROOT", plot_id=p_id, product_id=prd_id, harvest_date=date(2026, 10, 1),
                   initial_quantity=Decimal("100.00"), remaining_quantity=Decimal("100.00"),
                   current_org_id=org_id, status=BATCH_STATUS_ACTIVE)
        b1 = Batch(code="ADV-B1", plot_id=p_id, product_id=prd_id, harvest_date=date(2026, 10, 2),
                   initial_quantity=Decimal("50.00"), remaining_quantity=Decimal("50.00"),
                   current_org_id=org_id, status=BATCH_STATUS_ACTIVE)
        b2 = Batch(code="ADV-B2", plot_id=p_id, product_id=prd_id, harvest_date=date(2026, 10, 2),
                   initial_quantity=Decimal("50.00"), remaining_quantity=Decimal("50.00"),
                   current_org_id=org_id, status=BATCH_STATUS_ACTIVE)
        d = Batch(code="ADV-D", plot_id=p_id, product_id=prd_id, harvest_date=date(2026, 10, 3),
                  initial_quantity=Decimal("50.00"), remaining_quantity=Decimal("50.00"),
                  current_org_id=org_id, status=BATCH_STATUS_ACTIVE)
        e = Batch(code="ADV-E", plot_id=p_id, product_id=prd_id, harvest_date=date(2026, 10, 4),
                  initial_quantity=Decimal("50.00"), remaining_quantity=Decimal("50.00"),
                  current_org_id=org_id, status=BATCH_STATUS_ACTIVE)
        x = Batch(code="ADV-X", plot_id=p_id, product_id=prd_id, harvest_date=date(2026, 10, 3),
                  initial_quantity=Decimal("50.00"), remaining_quantity=Decimal("50.00"),
                  current_org_id=org_id, status=BATCH_STATUS_ACTIVE)
        y = Batch(code="ADV-Y", plot_id=p_id, product_id=prd_id, harvest_date=date(2026, 10, 4),
                  initial_quantity=Decimal("50.00"), remaining_quantity=Decimal("50.00"),
                  current_org_id=org_id, status=BATCH_STATUS_ACTIVE)
        session.add_all([r4, b1, b2, d, e, x, y])
        session.flush()

        session.add_all([
            BatchRelation(parent_batch_id=r4.id, child_batch_id=b1.id,
                          transferred_quantity=Decimal("50.00"), relation_type=RELATION_SPLIT),
            BatchRelation(parent_batch_id=r4.id, child_batch_id=b2.id,
                          transferred_quantity=Decimal("50.00"), relation_type=RELATION_SPLIT),
            BatchRelation(parent_batch_id=b1.id, child_batch_id=d.id,
                          transferred_quantity=Decimal("50.00"), relation_type=RELATION_SPLIT),
            BatchRelation(parent_batch_id=d.id, child_batch_id=e.id,
                          transferred_quantity=Decimal("50.00"), relation_type=RELATION_SPLIT),
            BatchRelation(parent_batch_id=b2.id, child_batch_id=x.id,
                          transferred_quantity=Decimal("50.00"), relation_type=RELATION_SPLIT),
            BatchRelation(parent_batch_id=x.id, child_batch_id=y.id,
                          transferred_quantity=Decimal("50.00"), relation_type=RELATION_SPLIT),
            BatchRelation(parent_batch_id=y.id, child_batch_id=d.id,
                          transferred_quantity=Decimal("25.00"), relation_type=RELATION_MERGE),
            # Cạnh nối ngược hoàn thành chu trình: E -> Y (tạo chu trình D -> E -> Y -> D)
            BatchRelation(parent_batch_id=e.id, child_batch_id=y.id,
                          transferred_quantity=Decimal("10.00"), relation_type=RELATION_SPLIT),
        ])
        session.commit()

        with pytest.raises(HTTPException) as exc_info4:
            trace_forward(session, r4.id, use_cache=False)
        assert exc_info4.value.status_code == 400
        assert "Cycle detected" in exc_info4.value.detail or "chu trình" in exc_info4.value.detail.lower()


def test_s26_consumed_stops_expansion(
    session_factory: sessionmaker[Session], s26_base_fixture: dict[str, int]
):
    """Test 4: Khi gặp lô CONSUMED:
    - Thuật toán dừng mở rộng con của lô CONSUMED đó.
    - remaining_quantity phản ánh 0.0, is_consumed=True.
    - Lô CONSUMED nằm trong danh sách terminal_batches.
    """
    clear_trace_cache()
    p_id = s26_base_fixture["plot_id"]
    prd_id = s26_base_fixture["product_id"]
    org_id = s26_base_fixture["org_id"]

    with session_factory() as session:
        root = Batch(code="S26-CSM-ROOT", plot_id=p_id, product_id=prd_id, harvest_date=date(2026, 10, 1),
                     initial_quantity=Decimal("1000.00"), remaining_quantity=Decimal("1000.00"),
                     current_org_id=org_id, status=BATCH_STATUS_ACTIVE)
        session.add(root)
        session.flush()

        # Nhánh 1: B1 bị CONSUMED
        b1 = Batch(code="S26-CSM-B1", plot_id=p_id, product_id=prd_id, harvest_date=date(2026, 10, 2),
                   initial_quantity=Decimal("500.00"), remaining_quantity=Decimal("0.00"),
                   current_org_id=org_id, status=BATCH_STATUS_CONSUMED)
        # Nhánh 2: B2 ACTIVE
        b2 = Batch(code="S26-CSM-B2", plot_id=p_id, product_id=prd_id, harvest_date=date(2026, 10, 2),
                   initial_quantity=Decimal("500.00"), remaining_quantity=Decimal("500.00"),
                   current_org_id=org_id, status=BATCH_STATUS_ACTIVE)
        session.add_all([b1, b2])
        session.flush()

        session.add_all([
            BatchRelation(parent_batch_id=root.id, child_batch_id=b1.id,
                          transferred_quantity=Decimal("500.00"), relation_type=RELATION_SPLIT),
            BatchRelation(parent_batch_id=root.id, child_batch_id=b2.id,
                          transferred_quantity=Decimal("500.00"), relation_type=RELATION_SPLIT),
        ])
        session.flush()

        # Giả sử trong DB có lô C1 là con của B1 (trước khi B1 bị consumed) và C2 là con của B2
        c1 = Batch(code="S26-CSM-C1", plot_id=p_id, product_id=prd_id, harvest_date=date(2026, 10, 3),
                   initial_quantity=Decimal("200.00"), remaining_quantity=Decimal("200.00"),
                   current_org_id=org_id, status=BATCH_STATUS_ACTIVE)
        c2 = Batch(code="S26-CSM-C2", plot_id=p_id, product_id=prd_id, harvest_date=date(2026, 10, 3),
                   initial_quantity=Decimal("200.00"), remaining_quantity=Decimal("200.00"),
                   current_org_id=org_id, status=BATCH_STATUS_ACTIVE)
        session.add_all([c1, c2])
        session.flush()

        session.add_all([
            BatchRelation(parent_batch_id=b1.id, child_batch_id=c1.id,
                          transferred_quantity=Decimal("200.00"), relation_type=RELATION_SPLIT),
            BatchRelation(parent_batch_id=b2.id, child_batch_id=c2.id,
                          transferred_quantity=Decimal("200.00"), relation_type=RELATION_SPLIT),
        ])
        session.commit()

        res = trace_forward(session, root.id, use_cache=False)

        # C1 không được phép xuất hiện vì nhánh B1 đã dừng khi B1 bị CONSUMED
        all_codes = [n["code"] for level_nodes in res["descendants_by_level"].values() for n in level_nodes]
        assert "S26-CSM-C1" not in all_codes
        assert "S26-CSM-C2" in all_codes

        # B1 phải nằm trong terminal_batches vì là điểm kết thúc chuỗi
        term_map = {t["code"]: t for t in res["terminal_batches"]}
        assert "S26-CSM-B1" in term_map
        assert term_map["S26-CSM-B1"]["is_consumed"] is True
        assert term_map["S26-CSM-B1"]["remaining_quantity"] == 0.0


def test_s26_max_nodes_limit(session_factory: sessionmaker[Session], s26_base_fixture: dict[str, int]):
    """Test 5: max_nodes dừng an toàn khi vượt ngưỡng và không duyệt thừa quá giới hạn."""
    clear_trace_cache()
    p_id = s26_base_fixture["plot_id"]
    prd_id = s26_base_fixture["product_id"]
    org_id = s26_base_fixture["org_id"]

    with session_factory() as session:
        root = Batch(code="S26-MAX-ROOT", plot_id=p_id, product_id=prd_id, harvest_date=date(2026, 10, 1),
                     initial_quantity=Decimal("1000.00"), remaining_quantity=Decimal("1000.00"),
                     current_org_id=org_id, status=BATCH_STATUS_ACTIVE)
        session.add(root)
        session.flush()

        # Tạo chuỗi 15 thế hệ
        prev_id = root.id
        for i in range(1, 16):
            child = Batch(code=f"S26-MAX-NODE-{i:02d}", plot_id=p_id, product_id=prd_id,
                          harvest_date=date(2026, 10, 1), initial_quantity=Decimal("100.00"),
                          remaining_quantity=Decimal("100.00"), current_org_id=org_id, status=BATCH_STATUS_ACTIVE)
            session.add(child)
            session.flush()
            session.add(BatchRelation(parent_batch_id=prev_id, child_batch_id=child.id,
                                      transferred_quantity=Decimal("100.00"), relation_type=RELATION_SPLIT))
            prev_id = child.id
        session.commit()

        # Trường hợp 1: Gọi với max_nodes = 5 khi đồ thị có 15 nút (thực sự bị cắt)
        res = trace_forward(session, root.id, use_cache=False, max_nodes=5)
        assert res["total_descendants"] == 5
        assert res["target_batch"]["is_truncated"] is True
        assert res["target_batch"]["max_nodes_reached"] is True

        # Trường hợp 2: Gọi với max_nodes = 50 khi đồ thị có 15 nút (không chạm trần, không bị cắt)
        res_full = trace_forward(session, root.id, use_cache=False, max_nodes=50)
        assert res_full["total_descendants"] == 15
        assert res_full["target_batch"]["is_truncated"] is False
        assert res_full["target_batch"]["max_nodes_reached"] is False

        # Xác nhận: max_nodes KHÔNG đếm nút gốc (root không nằm trong descendants)
        all_desc_ids = [n["batch_id"] for lvl in res_full["descendants_by_level"].values() for n in lvl]
        assert root.id not in all_desc_ids

        # Trường hợp 3: Đồ thị độc lập có ĐÚNG 3 nút con, gọi với max_nodes = 3
        # Đạt ngưỡng trần max_nodes_reached = True, nhưng KHÔNG BỊ CẮT vì không còn con chưa duyệt -> is_truncated = False
        exact_root = Batch(code="S26-EXACT-ROOT", plot_id=p_id, product_id=prd_id, harvest_date=date(2026, 10, 1),
                           initial_quantity=Decimal("300.00"), remaining_quantity=Decimal("300.00"),
                           current_org_id=org_id, status=BATCH_STATUS_ACTIVE)
        session.add(exact_root)
        session.flush()

        for k in range(1, 4):
            ex_child = Batch(code=f"S26-EXACT-C{k}", plot_id=p_id, product_id=prd_id,
                             harvest_date=date(2026, 10, 2), initial_quantity=Decimal("100.00"),
                             remaining_quantity=Decimal("100.00"), current_org_id=org_id, status=BATCH_STATUS_ACTIVE)
            session.add(ex_child)
            session.flush()
            session.add(BatchRelation(parent_batch_id=exact_root.id, child_batch_id=ex_child.id,
                                      transferred_quantity=Decimal("100.00"), relation_type=RELATION_SPLIT))
        session.commit()

        res_exact = trace_forward(session, exact_root.id, use_cache=False, max_nodes=3)
        assert res_exact["total_descendants"] == 3
        assert res_exact["target_batch"]["max_nodes_reached"] is True
        assert res_exact["target_batch"]["is_truncated"] is False  # Không bị cắt vì đồ thị đã hết con!


def test_s26_benchmark_1000_nodes(session_factory: sessionmaker[Session], s26_base_fixture: dict[str, int]):
    """Test 6 (Benchmark AC): Đồ thị 1.000 nút thực tế trên SQLite thử nghiệm riêng:
    - Xây dựng đồ thị DAG 1.000 lô con với nhiều tầng tách và gộp.
    - Thực thi trace_forward(session, root.id, use_cache=False, max_nodes=1000).
    - Đo thời gian chính xác bằng time.perf_counter().
    - Acceptance Criteria: Thời gian thực thi < 2.0 giây.
    """
    clear_trace_cache()
    p_id = s26_base_fixture["plot_id"]
    prd_id = s26_base_fixture["product_id"]
    org_id = s26_base_fixture["org_id"]

    TARGET_COUNT = 1000

    with session_factory() as session:
        root = Batch(
            code="S26-BENCH-ROOT",
            plot_id=p_id,
            product_id=prd_id,
            harvest_date=date(2026, 10, 1),
            initial_quantity=Decimal("100000.00"),
            remaining_quantity=Decimal("100000.00"),
            current_org_id=org_id,
            status=BATCH_STATUS_ACTIVE,
        )
        session.add(root)
        session.flush()

        batches_to_add = []
        for i in range(1, TARGET_COUNT + 1):
            batches_to_add.append(
                Batch(
                    code=f"S26-B-{i:04d}",
                    plot_id=p_id,
                    product_id=prd_id,
                    harvest_date=date(2026, 10, 1),
                    initial_quantity=Decimal("100.00"),
                    remaining_quantity=Decimal("100.00"),
                    current_org_id=org_id,
                    status=BATCH_STATUS_ACTIVE,
                )
            )
        session.add_all(batches_to_add)
        session.flush()

        batch_ids = [b.id for b in batches_to_add]

        # Xây dựng đồ thị 10 tầng, mỗi tầng 100 nút, có tách và gộp
        relations_to_add = []
        # Tầng 1: root tách ra 100 nút đầu tiên
        for i in range(100):
            relations_to_add.append(
                BatchRelation(
                    parent_batch_id=root.id,
                    child_batch_id=batch_ids[i],
                    transferred_quantity=Decimal("10.00"),
                    relation_type=RELATION_SPLIT,
                )
            )

        # Các tầng 2 đến 10: Tầng k -> Tầng k+1 (có quan hệ gộp chéo)
        for layer in range(9):
            parent_offset = layer * 100
            child_offset = (layer + 1) * 100
            for j in range(100):
                p1 = batch_ids[parent_offset + j]
                p2 = batch_ids[parent_offset + ((j + 1) % 100)]
                c = batch_ids[child_offset + j]
                # c nhận từ p1
                relations_to_add.append(
                    BatchRelation(
                        parent_batch_id=p1,
                        child_batch_id=c,
                        transferred_quantity=Decimal("5.00"),
                        relation_type=RELATION_SPLIT if j % 2 == 0 else RELATION_MERGE,
                    )
                )
                # Mỗi nút chẵn nhận thêm từ p2 (quan hệ gộp - Diamond pattern)
                if j % 2 == 0:
                    relations_to_add.append(
                        BatchRelation(
                            parent_batch_id=p2,
                            child_batch_id=c,
                            transferred_quantity=Decimal("5.00"),
                            relation_type=RELATION_MERGE,
                        )
                    )

        session.add_all(relations_to_add)
        session.commit()

        # Thực thi đo benchmark
        start_time = time.perf_counter()
        result = trace_forward(session, root.id, use_cache=False, max_nodes=1000)
        elapsed_time = time.perf_counter() - start_time

        print("\n=======================================================")
        print(f"[S-26 BENCHMARK] Traversed {result['total_descendants']} DAG nodes across 10 levels")
        print(f"[S-26 BENCHMARK] Actual execution time: {elapsed_time:.4f} seconds")
        print("[S-26 BENCHMARK] Acceptance Criteria: < 2.0000 seconds")
        print("=======================================================")

        # Khẳng định chất lượng
        assert result["total_descendants"] == TARGET_COUNT, (
            f"Kỳ vọng {TARGET_COUNT} nút nhưng nhận được {result['total_descendants']}"
        )
        assert len(result["descendants_by_level"]) == 10, "Kỳ vọng đủ 10 tầng thế hệ"
        assert elapsed_time < 2.0, (
            f"Hiệu năng không đạt: thực thi mất {elapsed_time:.4f}s (ngưỡng tối đa 2.0s)"
        )
