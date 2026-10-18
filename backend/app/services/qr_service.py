"""Dịch vụ sinh mã QR cho hệ thống AgriTrace (Task S-46).

Hỗ trợ:
- Sinh mã QR dưới dạng ảnh PNG (byte stream cho StreamingResponse hoặc tải file).
- Sinh mã QR dưới dạng Base64 data URL (hiển thị trực tiếp vào thẻ HTML <img>).
- Sinh mã QR dưới dạng SVG vector (phục vụ in ấn bao bì kích thước chuẩn 3cm).
- Tích hợp chuẩn URL truy xuất nguồn gốc lô nông sản theo Epic E-08 / S-46.
"""

from __future__ import annotations

import base64
import io
import os
from typing import Any, Literal
from urllib.parse import urljoin

import qrcode
from qrcode.constants import (
    ERROR_CORRECT_H,
    ERROR_CORRECT_L,
    ERROR_CORRECT_M,
    ERROR_CORRECT_Q,
)
from qrcode.image.svg import SvgImage
from pydantic import BaseModel, ConfigDict, Field


# Bản đồ mức sửa lỗi QR Code
ERROR_CORRECTION_MAP = {
    "L": ERROR_CORRECT_L,  # ~7% phục hồi
    "M": ERROR_CORRECT_M,  # ~15% phục hồi (mặc định khuyến nghị cho tem nhãn)
    "Q": ERROR_CORRECT_Q,  # ~25% phục hồi
    "H": ERROR_CORRECT_H,  # ~30% phục hồi (dùng khi dán tem ngoài trời, dễ trầy xước)
}


# ==============================================================================
# Pydantic Schemas cho API Sinh mã QR
# ==============================================================================

class QRGenerateRequest(BaseModel):
    """Schema yêu cầu sinh mã QR tùy biến từ chuỗi bất kỳ."""
    model_config = ConfigDict(extra="forbid")

    data: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        description="Dữ liệu hoặc URL cần mã hóa vào QR code.",
        examples=["https://trace.agritrace.vn/batches/B1234567"],
    )
    format: Literal["base64", "png", "svg"] = Field(
        default="base64",
        description="Định dạng trả về: 'base64' (JSON kèm data-url), 'png' (ảnh nhị phân), 'svg' (vector).",
    )
    box_size: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Kích thước pixel của mỗi ô vuông trong mã QR (mặc định 10).",
    )
    border: int = Field(
        default=4,
        ge=1,
        le=20,
        description="Độ rộng khoảng đệm (quiet zone) xung quanh mã QR (chuẩn là 4 ô).",
    )
    error_correction: Literal["L", "M", "Q", "H"] = Field(
        default="M",
        description="Mức độ sửa lỗi: L (7%), M (15%), Q (25%), H (30%).",
    )


class QRGenerateResponse(BaseModel):
    """Schema phản hồi khi sinh mã QR dạng JSON/Base64."""
    data: str = Field(..., description="Chuỗi dữ liệu được mã hóa trong QR.")
    format: str = Field(..., description="Định dạng của dữ liệu ảnh.")
    qr_base64: str | None = Field(default=None, description="Chuỗi data URL Base64 để hiển thị thẻ <img>.")
    qr_svg: str | None = Field(default=None, description="Mã nguồn SVG nếu yêu cầu định dạng SVG qua JSON.")
    content_type: str = Field(..., description="MIME type tương ứng.")
    box_size: int = Field(default=10, description="Kích thước box size đã dùng.")
    border: int = Field(default=4, description="Độ dày viền quiet zone đã dùng.")
    message: str = Field(default="Sinh mã QR thành công.")


class BatchQRResponse(BaseModel):
    """Schema phản hồi khi sinh mã QR cho một lô nông sản cụ thể (S-46)."""
    batch_id: int = Field(..., description="ID định danh nội bộ của lô.")
    batch_code: str = Field(..., description="Mã định danh công khai của lô nông sản (VD: B1234567).")
    product_name: str | None = Field(default=None, description="Tên sản phẩm nông sản của lô.")
    target_url: str = Field(..., description="URL truy xuất nguồn gốc công khai gắn trong mã QR.")
    qr_base64: str = Field(..., description="Chuỗi Data URL (data:image/png;base64,...) hiển thị ngay lên thẻ <img>.")
    download_png_url: str = Field(..., description="Đường dẫn API để tải tệp ảnh PNG.")
    download_svg_url: str = Field(..., description="Đường dẫn API để tải tệp vector SVG cho in ấn bao bì.")
    physical_size_cm: float = Field(
        default=3.0,
        description="Kích thước tem nhãn in ấn khuyến nghị theo đặc tả S-46 (3.0 cm).",
    )
    message: str = Field(default="Sinh mã QR cho lô nông sản thành công.")


# ==============================================================================
# Các hàm nghiệp vụ sinh mã QR
# ==============================================================================

def create_qr_instance(
    box_size: int = 10,
    border: int = 4,
    error_correction: str = "M",
    image_factory: Any | None = None,
) -> qrcode.QRCode:
    """Khởi tạo đối tượng QRCode với cấu hình chuẩn."""
    ec_level = ERROR_CORRECTION_MAP.get(error_correction.upper(), ERROR_CORRECT_M)
    return qrcode.QRCode(
        version=None,  # Tự động chọn version nhỏ nhất vừa vặn với kích thước dữ liệu
        error_correction=ec_level,
        box_size=max(1, box_size),
        border=max(1, border),
        image_factory=image_factory,
    )


def generate_qr_png_bytes(
    data: str,
    box_size: int = 10,
    border: int = 4,
    error_correction: str = "M",
) -> bytes:
    """Sinh ảnh mã QR dưới dạng mảng byte PNG (dùng cho StreamingResponse hoặc lưu file)."""
    if not data or not str(data).strip():
        raise ValueError("Dữ liệu cần sinh mã QR không được để trống.")

    qr = create_qr_instance(
        box_size=box_size,
        border=border,
        error_correction=error_correction,
    )
    qr.add_data(str(data).strip())
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def generate_qr_svg_bytes(
    data: str,
    box_size: int = 10,
    border: int = 4,
    error_correction: str = "M",
) -> bytes:
    """Sinh ảnh mã QR vector SVG (phù hợp in tem nhãn sắc nét mọi kích thước)."""
    if not data or not str(data).strip():
        raise ValueError("Dữ liệu cần sinh mã QR không được để trống.")

    qr = create_qr_instance(
        box_size=box_size,
        border=border,
        error_correction=error_correction,
        image_factory=SvgImage,
    )
    qr.add_data(str(data).strip())
    qr.make(fit=True)

    img = qr.make_image()
    buffer = io.BytesIO()
    img.save(buffer)
    return buffer.getvalue()


def generate_qr_base64(
    data: str,
    box_size: int = 10,
    border: int = 4,
    error_correction: str = "M",
) -> str:
    """Sinh chuỗi data URL Base64 để hiển thị trực tiếp vào thẻ <img src="...">."""
    png_bytes = generate_qr_png_bytes(
        data=data,
        box_size=box_size,
        border=border,
        error_correction=error_correction,
    )
    b64_str = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{b64_str}"


def build_batch_trace_url(batch_code: str, base_url: str | None = None) -> str:
    """Xây dựng URL truy xuất nguồn gốc công khai cho lô hàng theo S-46 / S-47.

    Ưu tiên:
    1. base_url truyền vào qua query/tham số.
    2. Biến môi trường AGRITRACE_PUBLIC_URL.
    3. Mặc định fallback cổng frontend local: http://localhost:5500/#trace?batch=...
    """
    clean_code = str(batch_code).strip()
    root_url = base_url or os.getenv("AGRITRACE_PUBLIC_URL") or "http://localhost:5500"
    root_url = root_url.rstrip("/")

    # Đường dẫn truy xuất công khai theo mã lô (S-46 & S-47)
    return f"{root_url}/#trace?batch={clean_code}"
