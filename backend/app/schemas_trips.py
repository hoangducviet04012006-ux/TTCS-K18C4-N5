from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TripBatchItemResponse(BaseModel):
    """Thông tin chi tiết một lô nông sản được chở trên chuyến xe."""

    model_config = ConfigDict(from_attributes=True)

    batch_id: int = Field(..., description="Mã ID của lô hàng.")
    batch_code: str = Field(..., description="Mã truy xuất 8 ký tự của lô.")
    product_name: str = Field(default="", description="Tên sản phẩm nông sản.")
    quantity: float = Field(default=0.0, description="Khối lượng còn lại của lô.")
    unit: str = Field(default="kg", description="Đơn vị tính.")
    attached_at: datetime = Field(..., description="Thời điểm gán vào xe.")
    detached_at: datetime | None = Field(default=None, description="Thời điểm dỡ khỏi xe.")
    notes: str | None = Field(default=None, description="Ghi chú kiện hàng.")


class TripCreate(BaseModel):
    """Dữ liệu yêu cầu mở chuyến vận chuyển chuỗi lạnh (POST /trips)."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        json_schema_extra={
            "example": {
                "trip_code": "TRIP-20261019-001",
                "container_code": "CONT-COLD-01",
                "batch_ids": [1, 2],
                "driver_name": "Nguyễn Văn Lái",
                "vehicle_plate": "29C-123.45",
                "start_location": "Kho Thái Nguyên",
                "destination_location": "Kho Phân phối Hà Nội",
                "notes": "Chuyến vận chuyển chè xuất khẩu yêu cầu nhiệt độ 2-6 độ C",
            }
        },
    )

    trip_code: str | None = Field(
        default=None,
        max_length=50,
        description="Mã chuyến (tùy chọn; nếu để trống hệ thống sẽ tự sinh TRIP-YYYYMMDD-XXXX).",
    )
    container_code: str = Field(
        ...,
        min_length=2,
        max_length=50,
        description="Mã thùng lạnh / container dùng cho chuyến (bắt buộc).",
    )
    batch_ids: list[int] = Field(
        ...,
        min_length=1,
        description="Danh sách ID các lô nông sản gắn vào chuyến (tối thiểu 1 lô).",
    )
    driver_name: str | None = Field(default=None, max_length=100, description="Họ tên tài xế.")
    vehicle_plate: str | None = Field(default=None, max_length=30, description="Biển số xe vận chuyển.")
    start_location: str | None = Field(default=None, max_length=255, description="Điểm xuất phát.")
    destination_location: str | None = Field(default=None, max_length=255, description="Điểm đến.")
    notes: str | None = Field(default=None, max_length=1000, description="Ghi chú hành trình.")

    @field_validator("container_code")
    @classmethod
    def validate_container_code(cls, v: str) -> str:
        clean = v.strip().upper()
        if len(clean) < 2:
            raise ValueError("Mã thùng lạnh phải có ít nhất 2 ký tự.")
        return clean

    @field_validator("batch_ids")
    @classmethod
    def validate_batch_ids(cls, v: list[int]) -> list[int]:
        if not v:
            raise ValueError("Chuyến xe phải chở ít nhất một lô nông sản.")
        # Loại bỏ ID trùng lặp nhưng giữ nguyên thứ tự
        seen = set()
        unique = []
        for b_id in v:
            if b_id <= 0:
                raise ValueError("Mã ID lô nông sản không hợp lệ.")
            if b_id not in seen:
                seen.add(b_id)
                unique.append(b_id)
        return unique


class TripAddBatchesRequest(BaseModel):
    """Dữ liệu yêu cầu bổ sung lô vào chuyến đang chạy (POST /trips/{id}/batches)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    batch_ids: list[int] = Field(..., min_length=1, description="Danh sách ID các lô bổ sung.")
    notes: str | None = Field(default=None, max_length=255, description="Ghi chú.")

    @field_validator("batch_ids")
    @classmethod
    def validate_batch_ids(cls, v: list[int]) -> list[int]:
        if not v:
            raise ValueError("Phải cung cấp ít nhất một lô nông sản để thêm vào chuyến.")
        return list(dict.fromkeys(v))


class TripCompleteRequest(BaseModel):
    """Dữ liệu yêu cầu kết thúc chuyến xe (POST /trips/{id}/complete)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    notes: str | None = Field(default=None, max_length=500, description="Ghi chú khi dỡ hàng xuống xe.")


class TripResponse(BaseModel):
    """Tóm tắt thông tin chuyến vận chuyển chuỗi lạnh."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    trip_code: str
    container_code: str
    transporter_org_id: int
    transporter_org_name: str | None = None
    status: str
    driver_name: str | None = None
    vehicle_plate: str | None = None
    start_location: str | None = None
    destination_location: str | None = None
    start_time: datetime
    end_time: datetime | None = None
    notes: str | None = None
    batch_count: int = 0
    created_at: datetime


class TripDetailResponse(TripResponse):
    """Chi tiết đầy đủ chuyến vận chuyển chuỗi lạnh kèm danh sách các lô."""

    batches: list[TripBatchItemResponse] = Field(default_factory=list)
