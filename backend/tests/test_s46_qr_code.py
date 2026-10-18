"""Bộ kiểm thử cho chức năng Sinh mã QR - Task S-46 (AgriTrace).

Kiểm thử:
1. Dịch vụ qr_service:
   - Tạo mã PNG byte stream hợp lệ (bắt đầu bằng PNG magic bytes).
   - Tạo mã Base64 data URL hợp lệ.
   - Tạo mã vector SVG hợp lệ.
   - Bắt lỗi khi dữ liệu rỗng.
   - Sinh URL truy xuất nguồn gốc đúng định dạng S-46 / S-47.
2. Endpoint API tĩnh:
   - POST /batches/qr/generate (Base64 JSON, PNG stream, SVG).
   - GET /batches/qr/generate (Query params, download flag).
3. Endpoint API cho lô nông sản:
   - GET /batches/{batch_id}/qr (trả về Base64, PNG, SVG cho lô có sẵn).
   - Kiểm tra mã lỗi 404 khi lô không tồn tại.
   - Kiểm tra header Content-Disposition khi bật cờ download=true.
"""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.models import Batch, Farm, Plot, Product
from app.services.qr_service import (
    build_batch_trace_url,
    generate_qr_base64,
    generate_qr_png_bytes,
    generate_qr_svg_bytes,
)


PNG_MAGIC_BYTES = b"\x89PNG\r\n\x1a\n"


# ==============================================================================
# 1. Unit test tầng Service (qr_service.py)
# ==============================================================================

def test_generate_qr_png_bytes():
    """Kiểm tra sinh byte stream PNG có đúng định dạng magic bytes của PNG."""
    data = "https://trace.agritrace.vn/batches/B1234567"
    raw_bytes = generate_qr_png_bytes(data, box_size=10, border=4)
    assert isinstance(raw_bytes, bytes)
    assert len(raw_bytes) > 0
    assert raw_bytes.startswith(PNG_MAGIC_BYTES)


def test_generate_qr_base64():
    """Kiểm tra sinh chuỗi data URI Base64 để hiển thị lên thẻ img."""
    data = "BATCH_CODE_TEST_123"
    b64 = generate_qr_base64(data)
    assert isinstance(b64, str)
    assert b64.startswith("data:image/png;base64,")
    # Tách phần base64 kiểm tra độ dài
    encoded_part = b64.split("data:image/png;base64,")[1]
    assert len(encoded_part) > 50


def test_generate_qr_svg_bytes():
    """Kiểm tra sinh vector SVG có chứa thẻ <svg>."""
    data = "https://agritrace.local/trace/BATCH"
    svg_bytes = generate_qr_svg_bytes(data)
    assert isinstance(svg_bytes, bytes)
    assert b"<svg" in svg_bytes
    assert b"</svg>" in svg_bytes


def test_generate_qr_empty_data_raises_error():
    """Kiểm tra ném ValueError khi truyền chuỗi rỗng."""
    with pytest.raises(ValueError, match="không được để trống"):
        generate_qr_png_bytes("")

    with pytest.raises(ValueError, match="không được để trống"):
        generate_qr_base64("   ")


def test_build_batch_trace_url():
    """Kiểm tra hàm tạo đường dẫn truy xuất nguồn gốc S-46."""
    url = build_batch_trace_url("BTEST123", base_url="https://trace.agritrace.vn")
    assert url == "https://trace.agritrace.vn/#trace?batch=BTEST123"


# ==============================================================================
# 2. Integration test API endpoints
# ==============================================================================

def test_api_generate_custom_qr_post_base64(client: TestClient):
    """POST /batches/qr/generate trả về JSON kèm Base64 data URL."""
    payload = {
        "data": "https://trace.agritrace.vn/#trace?batch=BTEST999",
        "format": "base64",
        "box_size": 8,
        "border": 4,
    }
    response = client.post("/batches/qr/generate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["format"] == "base64"
    assert data["qr_base64"].startswith("data:image/png;base64,")
    assert data["content_type"] == "image/png"


def test_api_generate_custom_qr_post_png_stream(client: TestClient):
    """POST /batches/qr/generate với format='png' trả về StreamingResponse ảnh PNG."""
    payload = {
        "data": "CUSTOM_DATA_FOR_PNG",
        "format": "png",
    }
    response = client.post("/batches/qr/generate", json=payload)
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(PNG_MAGIC_BYTES)


def test_api_generate_custom_qr_get(client: TestClient):
    """GET /batches/qr/generate hỗ trợ query parameter và tải file."""
    # Test JSON Base64
    res_b64 = client.get("/batches/qr/generate?data=HELLO_AGRITRACE&format=base64")
    assert res_b64.status_code == 200
    assert "data:image/png;base64," in res_b64.json()["qr_base64"]

    # Test PNG Stream với download=true
    res_png = client.get("/batches/qr/generate?data=HELLO_AGRITRACE&format=png&download=true")
    assert res_png.status_code == 200
    assert res_png.headers["content-type"] == "image/png"
    assert "attachment" in res_png.headers["content-disposition"]
    assert res_png.content.startswith(PNG_MAGIC_BYTES)

    # Test SVG Vector
    res_svg = client.get("/batches/qr/generate?data=HELLO_AGRITRACE&format=svg")
    assert res_svg.status_code == 200
    assert "image/svg+xml" in res_svg.headers["content-type"]
    assert b"<svg" in res_svg.content


def test_api_get_batch_qr_404(client: TestClient):
    """GET /batches/{id}/qr trả về 404 nếu lô nông sản không tồn tại."""
    response = client.get("/batches/999999/qr")
    assert response.status_code == 404
    assert "Không tìm thấy" in response.json()["detail"]


def test_api_get_batch_qr_success(
    client: TestClient,
    session_factory: sessionmaker[Session],
    users: list[str],
):
    """GET /batches/{id}/qr cho một lô nông sản có thật."""
    # Tạo dữ liệu lô mẫu
    with session_factory() as session:
        farm = Farm(
            name="Vùng trồng Thử Nghiệm",
            location="Đồng Tháp",
            area=1.5,
            owner="Nguyễn Văn Test",
            organization_id=1,
        )
        session.add(farm)
        session.flush()

        plot = Plot(
            name="Thửa đất số 1",
            location="Đồng Tháp",
            area=1.0,
            owner="Nguyễn Văn Test",
            organization_id=1,
        )
        session.add(plot)
        session.flush()

        product = Product(name="Xoài Cát Chu", unit="kg")
        session.add(product)
        session.flush()

        batch = Batch(
            code="B9988776",
            plot_id=plot.id,
            farm_id=farm.id,
            product_id=product.id,
            product_name=product.name,
            harvest_date=date.today(),
            initial_quantity=Decimal("150.0"),
            remaining_quantity=Decimal("150.0"),
            quantity=150.0,
            current_org_id=1,
            status="ACTIVE",
        )
        session.add(batch)
        session.commit()
        batch_id = batch.id
        batch_code = batch.code

    # 1. Gọi lấy Base64 (mặc định)
    res_base64 = client.get(f"/batches/{batch_id}/qr?format=base64")
    assert res_base64.status_code == 200
    json_data = res_base64.json()
    assert json_data["batch_id"] == batch_id
    assert json_data["batch_code"] == batch_code
    assert json_data["product_name"] == "Xoài Cát Chu"
    assert json_data["physical_size_cm"] == 3.0
    assert batch_code in json_data["target_url"]
    assert json_data["qr_base64"].startswith("data:image/png;base64,")

    # 2. Gọi lấy PNG stream để nhúng trực tiếp thẻ <img>
    res_png = client.get(f"/batches/{batch_id}/qr?format=png")
    assert res_png.status_code == 200
    assert res_png.headers["content-type"] == "image/png"
    assert res_png.content.startswith(PNG_MAGIC_BYTES)

    # 3. Gọi lấy SVG vector để in ấn bao bì
    res_svg = client.get(f"/batches/{batch_id}/qr?format=svg&download=true")
    assert res_svg.status_code == 200
    assert "image/svg+xml" in res_svg.headers["content-type"]
    assert f"qr_{batch_code}.svg" in res_svg.headers["content-disposition"]
    assert b"<svg" in res_svg.content
