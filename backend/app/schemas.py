"""Pydantic schemas - định nghĩa "hợp đồng" dữ liệu vào/ra của API.

Tách riêng schemas (Pydantic) khỏi models (SQLAlchemy) giúp:
- Không lộ cấu trúc bảng ra ngoài API.
- Validate dữ liệu đầu vào tự động và sinh tài liệu Swagger chuẩn.
"""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    """Response của endpoint ``GET /health``.

    Ví dụ::

        {"status": "running"}
    """

    model_config = ConfigDict(
        json_schema_extra={"example": {"status": "running"}},
    )

    status: str = Field(
        ...,
        description="Trạng thái hoạt động của API.",
        examples=["running"],
    )


# ------------------------------------------------------------------ Farm ---
_FARM_EXAMPLE: dict = {
    "id": 1,
    "name": "Vùng trồng xoài Cao Lãnh",
    "location": "Xã Mỹ Xương, Huyện Cao Lãnh, Tỉnh Đồng Tháp",
    "area": 2.5,
    "owner": "Hợp tác xã Xoài Mỹ Xương",
}


class FarmCreate(BaseModel):
    """Dữ liệu client gửi lên khi tạo vùng trồng mới (``POST /farms``).

    Chỉ chứa các field client được phép nhập - ``id`` do database sinh ra.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Vùng trồng xoài Cao Lãnh",
                "location": "Xã Mỹ Xương, Huyện Cao Lãnh, Tỉnh Đồng Tháp",
                "area": 2.5,
                "owner": "Hợp tác xã Xoài Mỹ Xương",
            }
        },
    )

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Tên vùng trồng.",
        examples=["Vùng trồng xoài Cao Lãnh"],
    )
    location: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Địa điểm của vùng trồng (xã/huyện/tỉnh).",
        examples=["Xã Mỹ Xương, Huyện Cao Lãnh, Tỉnh Đồng Tháp"],
    )
    area: float = Field(
        ...,
        gt=0,
        description="Diện tích canh tác, đơn vị hecta (ha). Phải lớn hơn 0.",
        examples=[2.5],
    )
    owner: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Chủ sở hữu vùng trồng.",
        examples=["Hợp tác xã Xoài Mỹ Xương"],
    )


class FarmResponse(BaseModel):
    """Dữ liệu API trả về cho một vùng trồng (kèm ``id``).

    ``from_attributes=True`` cho phép khởi tạo trực tiếp từ ORM object
    (``Farm``) mà không cần convert thủ công::

        FarmResponse.model_validate(farm_obj)
    """

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"example": _FARM_EXAMPLE},
    )

    id: int = Field(..., description="Mã định danh vùng trồng.", examples=[1])
    name: str = Field(..., description="Tên vùng trồng.")
    location: str = Field(..., description="Địa điểm của vùng trồng.")
    area: float = Field(..., description="Diện tích canh tác (ha).")
    owner: str = Field(..., description="Chủ sở hữu vùng trồng.")


# ----------------------------------------------------------------- Batch ---
_BATCH_EXAMPLE: dict = {
    "id": 1,
    "farm_id": 1,
    "product_name": "Xoài cát Chu",
    "quantity": 120.5,
    "harvest_date": "2026-01-15",
}


class BatchCreate(BaseModel):
    """Dữ liệu client gửi lên khi tạo lô nông sản mới (``POST /batches``).

    ``farm_id`` phải trỏ tới một vùng trồng **đã tồn tại** — router sẽ trả
    ``404 Not Found`` nếu không tìm thấy.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "farm_id": 1,
                "product_name": "Xoài cát Chu",
                "quantity": 120.5,
                "harvest_date": "2026-01-15",
            }
        },
    )

    farm_id: int = Field(
        ...,
        gt=0,
        description="ID vùng trồng (farms.id) - phải tồn tại.",
        examples=[1],
    )
    product_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Tên sản phẩm của lô.",
        examples=["Xoài cát Chu"],
    )
    quantity: float = Field(
        ...,
        gt=0,
        description="Số lượng / khối lượng của lô, đơn vị kg. Phải lớn hơn 0.",
        examples=[120.5],
    )
    harvest_date: date = Field(
        ...,
        description="Ngày thu hoạch, định dạng yyyy-MM-dd.",
        examples=["2026-01-15"],
    )


class BatchResponse(BaseModel):
    """Dữ liệu API trả về cho một lô nông sản (kèm ``id``).

    ``harvest_date`` được serialize thành chuỗi ``yyyy-MM-dd``.
    """

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"example": _BATCH_EXAMPLE},
    )

    id: int = Field(..., description="Mã định danh lô nông sản.", examples=[1])
    farm_id: int = Field(..., description="ID vùng trồng xuất xứ.", examples=[1])
    product_name: str = Field(..., description="Tên sản phẩm của lô.")
    quantity: float = Field(..., description="Số lượng / khối lượng (kg).")
    harvest_date: date = Field(..., description="Ngày thu hoạch.")
