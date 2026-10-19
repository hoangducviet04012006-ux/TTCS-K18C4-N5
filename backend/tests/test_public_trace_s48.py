"""Kiểm thử tự động cho Story S-48: Trang công khai chỉ trả về trường được đánh dấu công khai.

Tiêu chuẩn nghiệm thu (Acceptance Criteria):
1. Danh sách trường công khai khai báo ở một chỗ, mặc định mọi trường là nội bộ.
2. Gọi thẳng API công khai cũng không lấy được trường nội bộ (không lộ khối lượng, giá, tên đối tác).
3. Test tự động so sánh phản hồi với danh sách cho phép (whitelist).
4. Tên tổ chức trung gian hiện theo loại (hợp tác xã, đơn vị vận chuyển) chứ không hiện tên riêng, trừ vùng trồng.
"""

import base64
from datetime import date, datetime
import pytest
from pydantic import ValidationError

from app.models import (
    Batch,
    BatchEvent,
    BatchRelation,
    Farm,
    Organization,
    Plot,
    Product,
    User,
)
from app.schemas_public import (
    INTERNAL_SENSITIVE_FIELDS,
    PUBLIC_BATCH_FIELDS,
    PUBLIC_MILESTONE_FIELDS,
    PUBLIC_ORIGIN_FIELDS,
    PUBLIC_ROOT_BATCH_FIELDS,
    PublicBatchTraceResponse,
    PublicOriginInfo,
)
from tests.conftest import TEST_PASSWORD, TEST_USERNAME_FARMER


def _farmer_headers():
    raw = f"{TEST_USERNAME_FARMER}:{TEST_PASSWORD}".encode("utf-8")
    return {"Authorization": "Basic " + base64.b64encode(raw).decode("ascii")}


def _find_all_keys(data: object) -> set[str]:
    """Hàm đệ quy tìm tất cả các key xuất hiện ở bất kỳ tầng nào trong cấu trúc dữ liệu."""
    keys = set()
    if isinstance(data, dict):
        for k, v in data.items():
            keys.add(k)
            keys.update(_find_all_keys(v))
    elif isinstance(data, list):
        for item in data:
            keys.update(_find_all_keys(item))
    return keys


def _create_sample_batch(client):
    headers = _farmer_headers()
    farm_res = client.post(
        "/farms",
        json={
            "name": "Nông trại Hữu cơ Cao Lãnh",
            "location": "Huyện Cao Lãnh, Đồng Tháp",
            "area": 2.5,
            "owner": "Nguyễn Văn Chủ Thửa",
        },
        headers=headers,
    )
    assert farm_res.status_code == 201, farm_res.text
    farm_id = farm_res.json()["id"]

    batch_res = client.post(
        "/batches",
        json={
            "farm_id": farm_id,
            "product_name": "Xoài Cát Chu Cao Lãnh",
            "quantity": 1500.0,
            "harvest_date": "2026-03-15",
        },
        headers=headers,
    )
    assert batch_res.status_code == 201, batch_res.text
    return batch_res.json()


def test_public_trace_fields_strictly_match_allowed_whitelist(client):
    """Test 1: Phản hồi của API công khai khớp chính xác 100% với whitelist được định nghĩa tập trung."""
    batch = _create_sample_batch(client)
    batch_code = batch["code"]

    # Gọi thẳng API công khai không qua đăng nhập
    response = client.get(f"/public/trace/{batch_code}")
    assert response.status_code == 200, response.text
    data = response.json()

    # 1. Cấp cao nhất phải khớp với PUBLIC_BATCH_FIELDS
    assert set(data.keys()) == set(PUBLIC_BATCH_FIELDS)

    # 2. Trường 'origin' phải khớp với PUBLIC_ORIGIN_FIELDS
    assert isinstance(data["origin"], dict)
    assert set(data["origin"].keys()) == set(PUBLIC_ORIGIN_FIELDS)

    # 3. Mỗi phần tử trong 'root_batches' phải là tập con của PUBLIC_ROOT_BATCH_FIELDS
    assert isinstance(data["root_batches"], list)
    assert len(data["root_batches"]) >= 1
    for root in data["root_batches"]:
        assert set(root.keys()) == set(PUBLIC_ROOT_BATCH_FIELDS)

    # 4. Mỗi phần tử trong 'milestones' phải là tập con của PUBLIC_MILESTONE_FIELDS
    assert isinstance(data["milestones"], list)
    assert len(data["milestones"]) >= 1
    for milestone in data["milestones"]:
        assert set(milestone.keys()) == set(PUBLIC_MILESTONE_FIELDS)


def test_direct_api_call_never_exposes_internal_sensitive_fields(client):
    """Test 2: Gọi thẳng API công khai TUYỆT ĐỐI KHÔNG lấy được bất kỳ trường nhạy cảm/nội bộ nào.

    Người tiêu dùng và đối thủ cạnh tranh không thể đọc được:
    - Khối lượng (quantity, initial_quantity, remaining_quantity, v.v.)
    - Giá cả (price, cost)
    - Tên đối tác thương mại trung gian
    - Khóa chính nội bộ (id, batch_id, farm_id, user_id, org_id)
    """
    batch = _create_sample_batch(client)
    batch_code = batch["code"]

    response = client.get(f"/public/trace/{batch_code}")
    assert response.status_code == 200
    data = response.json()

    # Thu thập toàn bộ các key xuất hiện trong JSON response (kể cả lồng nhau)
    all_keys = _find_all_keys(data)

    # Không được chứa bất kỳ trường nào trong danh mục cấm INTERNAL_SENSITIVE_FIELDS
    intersected_forbidden = all_keys.intersection(INTERNAL_SENSITIVE_FIELDS)
    assert not intersected_forbidden, (
        f"CẢNH BÁO VI PHẠM S-48: Phát hiện trường nội bộ rò rỉ ra API công khai: {intersected_forbidden}"
    )

    # Kiểm tra khẳng định chi tiết từng trường kinh doanh cốt lõi
    assert "quantity" not in data
    assert "initial_quantity" not in data
    assert "remaining_quantity" not in data
    assert "price" not in data
    assert "cost" not in data
    assert "id" not in data
    assert "batch_id" not in data
    assert "farm_id" not in data
    assert "plot_id" not in data
    assert "user_id" not in data
    assert "owner" not in data
    assert "plot_area" not in data


def test_intermediate_organizations_masked_to_type_not_private_name(client, session_factory):
    """Test 3: Tên đối tác trung gian hiển thị theo loại (HTX, vận chuyển, phân phối) chứ không lộ tên riêng.

    Ngoại lệ: Vùng trồng gốc vẫn hiển thị tên trang trại minh bạch xuất xứ ("trừ vùng trồng").
    """
    with session_factory() as db:
        # Lấy hoặc tạo user phục vụ created_by_user_id của event
        user = db.query(User).first()

        # Tạo tổ chức vùng trồng (gốc)
        farm_org = Organization(name="Hợp tác xã Xoài Mỹ Xương", code="HTX-MX-S48")
        db.add(farm_org)
        db.flush()

        # Tạo tổ chức vận chuyển trung gian (có tên doanh nghiệp riêng)
        transporter_org = Organization(
            name="Công ty Cổ phần Vận Tải Đông Nam Á Logistics",
            code="TRANS-LOG-S48",
        )
        db.add(transporter_org)
        db.flush()

        # Tạo tổ chức phân phối trung gian (có tên doanh nghiệp riêng)
        distributor_org = Organization(
            name="Tổng Công ty Xuất Nhập Khẩu Phân Phối Nông Sản Mega",
            code="MEGA-DIST-S48",
        )
        db.add(distributor_org)
        db.flush()

        product = db.query(Product).first()
        if product is None:
            product = Product(name="Xoài Cát Chu", unit="kg")
            db.add(product)
            db.flush()

        farm = Farm(
            organization_id=farm_org.id,
            name="Trang trại Xoài Cát Mỹ Xương",
            location="Huyện Cao Lãnh, Đồng Tháp",
            area=3.0,
            owner="Chủ Vườn",
        )
        db.add(farm)
        db.flush()

        plot = Plot(
            organization_id=farm_org.id,
            name="Thửa đất số 08",
            location="Ấp Mỹ Xương, Cao Lãnh, Đồng Tháp",
            area=1.5,
            owner="Chủ Vườn",
        )
        db.add(plot)
        db.flush()

        # Tạo lô hàng
        batch = Batch(
            code="LOT-S48-MASK-001",
            plot_id=plot.id,
            farm_id=farm.id,
            product_id=product.id,
            product_name="Xoài Cát Chu",
            harvest_date=date(2026, 3, 20),
            initial_quantity=5000,
            remaining_quantity=5000,
            quantity=5000,
            current_org_id=distributor_org.id,
            status="ACTIVE",
        )
        db.add(batch)
        db.flush()

        # Ghi sự kiện các khâu
        evt1 = BatchEvent(
            batch_id=batch.id,
            event_type="HARVEST",
            organization_id=farm_org.id,
            created_by_user_id=user.id if user else 1,
            created_at=datetime(2026, 3, 20, 8, 0, 0),
        )
        evt2 = BatchEvent(
            batch_id=batch.id,
            event_type="TRIP_DISPATCH",
            organization_id=transporter_org.id,
            created_by_user_id=user.id if user else 1,
            from_org_id=farm_org.id,
            to_org_id=distributor_org.id,
            created_at=datetime(2026, 3, 21, 9, 30, 0),
        )
        evt3 = BatchEvent(
            batch_id=batch.id,
            event_type="HANDOVER_ACCEPT",
            organization_id=distributor_org.id,
            created_by_user_id=user.id if user else 1,
            from_org_id=transporter_org.id,
            to_org_id=distributor_org.id,
            created_at=datetime(2026, 3, 22, 14, 0, 0),
        )
        db.add_all([evt1, evt2, evt3])
        db.commit()

    # Gọi API công khai
    response = client.get("/public/trace/LOT-S48-MASK-001")
    assert response.status_code == 200
    res_text = response.text
    data = response.json()

    # 1. Tên riêng của đối tác trung gian TUYỆT ĐỐI KHÔNG xuất hiện
    assert "Công ty Cổ phần Vận Tải Đông Nam Á Logistics" not in res_text
    assert "Tổng Công ty Xuất Nhập Khẩu Phân Phối Nông Sản Mega" not in res_text

    # 2. Các đơn vị trung gian được chuẩn hóa thành loại hình chung
    org_types = [m["organization_type"] for m in data["milestones"]]
    assert "Đơn vị vận chuyển" in org_types
    assert "Nhà phân phối" in org_types

    # 3. Ngoại lệ: Vùng trồng gốc được phép hiển thị tên để minh bạch nguồn gốc ("trừ vùng trồng")
    assert data["origin"]["farm_name"] == "Trang trại Xoài Cát Mỹ Xương"
    assert "Cao Lãnh, Đồng Tháp" in data["origin"]["location"]


def test_multi_source_merged_batch_returns_only_public_fields_for_all_roots(client, session_factory):
    """Test 4: Lô gộp từ nhiều nguồn hiển thị tất cả vùng trồng gốc nhưng không lộ khối lượng pha trộn."""
    with session_factory() as db:
        org = Organization(name="HTX Hợp Nhất Nông Sản", code="HTX-HN-S48")
        db.add(org)
        db.flush()

        product = db.query(Product).first()
        if product is None:
            product = Product(name="Xoài Cát", unit="kg")
            db.add(product)
            db.flush()

        farm_a = Farm(organization_id=org.id, name="Vùng trồng A - Xoài Cát", location="Đồng Tháp", area=1.0, owner="Ông A")
        farm_b = Farm(organization_id=org.id, name="Vùng trồng B - Xoài Cát", location="Tiền Giang", area=1.0, owner="Ông B")
        db.add_all([farm_a, farm_b])
        db.flush()

        plot_a = Plot(organization_id=org.id, name="Thửa A1", location="Đồng Tháp", area=0.5, owner="Ông A")
        plot_b = Plot(organization_id=org.id, name="Thửa B1", location="Tiền Giang", area=0.5, owner="Ông B")
        db.add_all([plot_a, plot_b])
        db.flush()

        batch_a = Batch(
            code="ROOT-A-S48",
            plot_id=plot_a.id,
            farm_id=farm_a.id,
            product_id=product.id,
            product_name="Xoài Cát",
            harvest_date=date(2026, 3, 10),
            initial_quantity=1000,
            remaining_quantity=1000,
            quantity=1000,
            current_org_id=org.id,
            status="ACTIVE",
        )
        batch_b = Batch(
            code="ROOT-B-S48",
            plot_id=plot_b.id,
            farm_id=farm_b.id,
            product_id=product.id,
            product_name="Xoài Cát",
            harvest_date=date(2026, 3, 11),
            initial_quantity=2000,
            remaining_quantity=2000,
            quantity=2000,
            current_org_id=org.id,
            status="ACTIVE",
        )
        db.add_all([batch_a, batch_b])
        db.flush()

        # Tạo lô gộp (plot_id kế thừa thửa cha đầu tiên)
        batch_merged = Batch(
            code="MERGED-C-S48",
            plot_id=plot_a.id,
            farm_id=farm_a.id,
            product_id=product.id,
            product_name="Xoài Cát Gộp Chuỗi",
            harvest_date=date(2026, 3, 12),
            initial_quantity=3000,
            remaining_quantity=3000,
            quantity=3000,
            current_org_id=org.id,
            status="ACTIVE",
        )
        db.add(batch_merged)
        db.flush()

        rel_a = BatchRelation(
            parent_batch_id=batch_a.id,
            child_batch_id=batch_merged.id,
            transferred_quantity=1000,
            relation_type="MERGE",
        )
        rel_b = BatchRelation(
            parent_batch_id=batch_b.id,
            child_batch_id=batch_merged.id,
            transferred_quantity=2000,
            relation_type="MERGE",
        )
        db.add_all([rel_a, rel_b])
        db.commit()

    # Truy vấn lô gộp
    response = client.get("/public/trace/MERGED-C-S48")
    assert response.status_code == 200
    data = response.json()

    # Kiểm tra cả 2 vùng trồng gốc đều được báo cáo cho người tiêu dùng
    roots = data["root_batches"]
    assert len(roots) == 2
    root_codes = {r["batch_code"] for r in roots}
    assert "ROOT-A-S48" in root_codes
    assert "ROOT-B-S48" in root_codes

    # Không để lộ khối lượng pha trộn của từng lô gốc
    for r in roots:
        assert set(r.keys()) == set(PUBLIC_ROOT_BATCH_FIELDS)
        assert "quantity" not in r
        assert "transferred_quantity" not in r
        assert "initial_quantity" not in r


def test_public_endpoint_unauthenticated_and_404_no_data_leak(client):
    """Test 5: Endpoint công khai không yêu cầu Auth; mã không tồn tại trả về 404 không lộ chi tiết."""
    # 1. Gọi mã không tồn tại
    res_404 = client.get("/public/trace/MA-LO-KHONG-TON-TAI-999")
    assert res_404.status_code == 404
    detail = res_404.json()["detail"]
    assert "Không tìm thấy" in detail
    assert "MA-LO-KHONG-TON-TAI-999" in detail
    # Không để lộ SQL error, table name hay trace
    assert "sqlalchemy" not in res_404.text.lower()
    assert "select" not in res_404.text.lower()


def test_pydantic_schema_extra_forbid_strictly_enforces_whitelist():
    """Test 6: Pydantic Schema PublicBatchTraceResponse ném ValidationError nếu chèn trường lạ."""
    valid_payload = {
        "batch_code": "LOT-VALID",
        "product_name": "Nông sản",
        "harvest_date": "2026-03-01",
        "status": "Đang lưu kho",
        "origin": PublicOriginInfo(farm_name="Trang trại A", location="Đồng Tháp"),
        "root_batches": [],
        "milestones": [],
    }

    # Hợp lệ khi chỉ có các trường cho phép
    model = PublicBatchTraceResponse(**valid_payload)
    assert model.batch_code == "LOT-VALID"

    # Ném ValidationError khi cố tình đính kèm trường nội bộ (extra="forbid")
    with pytest.raises(ValidationError):
        PublicBatchTraceResponse(**valid_payload, internal_quantity=500)

    with pytest.raises(ValidationError):
        PublicBatchTraceResponse(**valid_payload, price=100000)

    with pytest.raises(ValidationError):
        PublicBatchTraceResponse(**valid_payload, database_id=123)
