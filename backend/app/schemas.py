"""Pydantic schemas - định nghĩa "hợp đồng" dữ liệu vào/ra của API.

Tách riêng schemas (Pydantic) khỏi models (SQLAlchemy) giúp:
- Không lộ cấu trúc bảng ra ngoài API.
- Validate dữ liệu đầu vào tự động và sinh tài liệu Swagger chuẩn.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class HealthResponse(BaseModel):
    """Response của endpoint ``GET /health``."""

    model_config = ConfigDict(
        json_schema_extra={"example": {"status": "ok", "database": "connected"}},
    )

    status: str = Field(
        ...,
        description="Trạng thái hoạt động của API.",
        examples=["ok"],
    )
    database: str = Field(
        default="connected",
        description="Trạng thái kết nối cơ sở dữ liệu.",
        examples=["connected", "disconnected"],
    )


# ------------------------------------------------------------------ Auth ---
class LoginRequest(BaseModel):
    """Dữ liệu client gửi lên khi đăng nhập (``POST /auth/login``)."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"username": "admin@gmail.com", "password": "123456"},
        },
    )

    username: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Email hoặc tên đăng nhập (S-04).",
        examples=["admin@gmail.com", "admin"],
    )
    password: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Mật khẩu dạng thô.",
        examples=["123456"],
    )


class DemoLoginRequest(BaseModel):
    """Dữ liệu client gửi lên khi đăng nhập nhanh demo (``POST /auth/demo-login``)."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"username": "s123_farm@demo.local"},
        },
    )

    username: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Email hoặc tên đăng nhập của 1 trong 8 tài khoản demo Sprint 1–3.",
        examples=["s123_farm@demo.local", "s123_farm"],
    )


# ---------------------------------------------------------- Organization ---
class OrganizationCreate(BaseModel):
    """Dữ liệu tạo tổ chức mới."""

    name: str = Field(..., min_length=1, max_length=255, description="Tên tổ chức / hợp tác xã.")
    code: str = Field(..., min_length=1, max_length=50, description="Mã định danh tổ chức (duy nhất).")
    description: str | None = Field(default=None, max_length=500, description="Mô tả tổ chức.")


class OrganizationResponse(OrganizationCreate):
    """Thông tin tổ chức trả về API."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="Mã ID tổ chức.")
    created_at: datetime = Field(..., description="Thời điểm tạo.")


class LoginResponse(BaseModel):
    """Kết quả đăng nhập thành công."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "username": "admin",
                "email": "admin@gmail.com",
                "role": "admin",
                "organization_id": 1,
                "organization_name": "Hợp tác xã Nông sản An Toàn Đồng Tháp",
            }
        },
    )

    username: str = Field(..., description="Tên đăng nhập.", examples=["admin"])
    email: str | None = Field(default=None, description="Email tài khoản.", examples=["admin@gmail.com"])
    role: str = Field(..., description="Vai trò tài khoản.", examples=["admin", "farmer"])
    organization_id: int | None = Field(default=None, description="ID tổ chức trực thuộc.", examples=[1])
    organization_name: str | None = Field(
        default=None,
        description="Tên tổ chức trực thuộc.",
        examples=["Hợp tác xã Nông sản An Toàn Đồng Tháp"],
    )
    csrf_token: str | None = Field(
        default=None,
        description="CSRF token gắn với phiên làm việc.",
        examples=["a1b2c3d4e5f6"],
    )


class AccountLockedResponse(BaseModel):
    """Body lỗi 403 Forbidden khi tài khoản bị tạm khoá."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "detail": ("Tài khoản 'farmer' đã bị tạm khoá do nhập sai mật khẩu 5 lần liên tiếp. "
                           "Vui lòng thử lại sau 15 phút.")
            }
        },
    )

    detail: str = Field(..., description="Lý do khoá tài khoản + thời gian chờ còn lại.")


class UserResponse(BaseModel):
    """Thông tin tài khoản trả ra API."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="Mã định danh tài khoản.", examples=[1])
    username: str = Field(..., description="Tên đăng nhập.", examples=["admin"])
    email: str | None = Field(default=None, description="Email tài khoản (dùng để đăng nhập).", examples=["admin@gmail.com"])
    role: str = Field(..., description="Vai trò: `admin` hoặc `farmer`.", examples=["admin"])
    organization_id: int | None = Field(default=None, description="ID tổ chức trực thuộc.", examples=[1])
    is_active: bool = True
    is_locked: bool = False
    locked_until: datetime | None = None


# ---------------------------------------------------------------- Product (T-16, T-17) ---
class ProductCreate(BaseModel):
    """Dữ liệu client gửi lên khi tạo sản phẩm mới (POST /products)."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"name": "Xoài cát Chu", "unit": "kg"},
        }
    )

    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Tên sản phẩm duy nhất toàn hệ thống.",
        examples=["Xoài cát Chu"],
    )
    unit: str = Field(
        ...,
        description="Đơn vị tính: 'kg', 'tấn' hoặc 'thùng'.",
        examples=["kg"],
    )

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Tên sản phẩm không được để trống.")
        return value

    @field_validator("unit")
    @classmethod
    def validate_unit(cls, v: str) -> str:
        clean = v.strip().lower()
        if clean not in ("kg", "tấn", "thùng"):
            raise ValueError("Đơn vị tính phải là 'kg', 'tấn' hoặc 'thùng'.")
        return clean


class ProductResponse(BaseModel):
    """Thông tin sản phẩm trả về API."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="Mã ID sản phẩm.", examples=[1])
    name: str = Field(..., description="Tên sản phẩm.", examples=["Xoài cát Chu"])
    unit: str = Field(..., description="Đơn vị tính.", examples=["kg"])
    created_at: datetime = Field(..., description="Thời điểm tạo.")


# ---------------------------------------------------------------- Farm / Plot ---
class FarmCreate(BaseModel):
    """Dữ liệu client gửi lên khi tạo vùng trồng mới (``POST /farms``)."""

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

    name: str = Field(..., min_length=1, max_length=255, description="Tên vùng trồng.")
    location: str = Field(..., min_length=1, max_length=255, description="Địa điểm vùng trồng.")
    area: float = Field(..., gt=0, description="Diện tích canh tác (ha). Phải lớn hơn 0.")
    coordinates: str | None = Field(default=None, max_length=255, description="Tọa độ GPS.")
    owner: str = Field(..., min_length=1, max_length=255, description="Chủ sở hữu vùng trồng.")


class FarmUpdate(FarmCreate):
    """Dữ liệu cập nhật vùng trồng."""


class FarmResponse(BaseModel):
    """Dữ liệu API trả về cho một vùng trồng."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="Mã định danh vùng trồng.", examples=[1])
    organization_id: int = Field(..., description="ID tổ chức trực thuộc.", examples=[1])
    name: str = Field(..., description="Tên vùng trồng.")
    location: str = Field(..., description="Địa điểm của vùng trồng.")
    area: float = Field(..., description="Diện tích canh tác (ha).")
    coordinates: str | None = Field(default=None, description="Tọa độ GPS của thửa đất.")
    owner: str = Field(..., description="Chủ sở hữu vùng trồng.")


# ----------------------------------------------------------------- Batch (T-18, T-21, T-33) ---
def validate_quantity(value):
    if value is None:
        return value
    number = Decimal(str(value))
    if not number.is_finite() or abs(number) > Decimal("99999999.99") or number != number.quantize(Decimal("0.01")):
        raise ValueError("Khối lượng cần hữu hạn, tối đa 99999999.99 và không quá 2 chữ số thập phân.")
    return value


class BatchCreate(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    """Dữ liệu client gửi lên khi thu hoạch / tạo lô nông sản (POST /batches)."""

    plot_id: int | None = Field(default=None, gt=0, description="ID thửa đất (plots.id).")
    farm_id: int | None = Field(default=None, gt=0, description="ID vùng trồng (farms.id - tương thích ngược).")
    product_id: int | None = Field(default=None, gt=0, description="ID sản phẩm (products.id).")
    product_name: str | None = Field(default=None, max_length=255, description="Tên sản phẩm (tương thích ngược).")
    initial_quantity: float | Decimal | None = Field(
        default=None,
        gt=0,
        description="Khối lượng thu hoạch ban đầu. Bắt buộc > 0.",
        examples=[500.0],
    )
    quantity: float | None = Field(
        default=None,
        gt=0,
        description="Khối lượng (tương thích ngược).",
        examples=[500.0],
    )
    harvest_date: date = Field(..., description="Ngày thu hoạch (định dạng yyyy-MM-dd).")

    @field_validator("initial_quantity", "quantity")
    @classmethod
    def precision(cls, value):
        return validate_quantity(value)


class BatchUpdate(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    """Dữ liệu cập nhật lô nông sản."""

    plot_id: int | None = Field(default=None, gt=0)
    farm_id: int | None = Field(default=None, gt=0)
    product_id: int | None = Field(default=None, gt=0)
    product_name: str | None = Field(default=None, max_length=255)
    initial_quantity: float | Decimal | None = None
    remaining_quantity: float | Decimal | None = None
    quantity: float | None = None
    harvest_date: date

    @field_validator("initial_quantity", "remaining_quantity", "quantity")
    @classmethod
    def precision(cls, value):
        return validate_quantity(value)


class PendingHandoverBrief(BaseModel):
    """Tóm tắt yêu cầu bàn giao đang chờ xác nhận, gắn kèm vào BatchResponse (T-56, T-57).

    Nhờ trường này mà CẢ bên gửi (thấy trong danh sách lô) lẫn bên nhận
    (thấy trong danh sách chờ duyệt) đều biết lô đang chờ bàn giao và có bị quá hạn 48h hay không.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="Mã yêu cầu bàn giao đang chờ.")
    status: str = Field(..., description="Trạng thái bàn giao (PENDING).")
    is_overdue: bool = Field(default=False, description="Cờ quá hạn 48 giờ chưa xác nhận (T-56).")
    to_org_id: int = Field(..., description="ID tổ chức tiếp nhận bàn giao.")
    created_at: datetime = Field(..., description="Thời điểm gửi yêu cầu bàn giao.")


class BatchResponse(BaseModel):
    """Dữ liệu API trả về cho một lô nông sản."""

    model_config = ConfigDict(from_attributes=True)
    location_id: int | None = None
    current_location: str | None = None
    current_location_name: str | None = None

    id: int = Field(..., description="Mã định danh lô nông sản.")
    code: str | None = Field(default="", description="Mã lô ngẫu nhiên 8 ký tự (T-19).")
    plot_id: int | None = Field(default=None, description="ID thửa đất xuất xứ.")
    farm_id: int | None = Field(default=None, description="ID vùng trồng (tương thích ngược).")
    product_id: int | None = Field(default=None, description="ID sản phẩm.")
    product_name: str | None = Field(default=None, description="Tên sản phẩm của lô.")
    initial_quantity: float | None = Field(default=None, description="Khối lượng thu hoạch ban đầu.")
    remaining_quantity: float | None = Field(default=None, description="Khối lượng còn lại.")
    quantity: float | None = Field(default=None, description="Khối lượng (tương thích ngược).")
    unit: str | None = Field(default="kg", description="Đơn vị tính.")
    harvest_date: date = Field(..., description="Ngày thu hoạch.")
    current_org_id: int | None = Field(default=None, description="ID tổ chức đang nắm giữ lô hàng.")
    current_org_name: str | None = Field(default=None, description="Tên tổ chức đang nắm giữ lô hàng.")
    status: str | None = Field(default="ACTIVE", description="Trạng thái lô hàng (ACTIVE, CLOSED...).")
    origin_id: int | None = Field(default=None, description="ID gốc trong tập dữ liệu thực hành nếu là dữ liệu mô phỏng.")
    dataset_source: str = Field(
        default="operational",
        description="Nguồn gốc dữ liệu: operational, practice_th1, practice_th2.",
    )
    is_simulation: bool = Field(default=False, description="Cờ đánh dấu dữ liệu mô phỏng thực hành.")
    is_pending: bool = Field(default=False, description="Lô đang có yêu cầu bàn giao chờ xác nhận (T-56, T-57).")
    pending_handover: PendingHandoverBrief | None = Field(
        default=None,
        description="Thông tin bàn giao đang chờ (kèm cờ quá hạn 48h) để cả bên gửi và bên nhận cùng thấy (T-56, T-57).",
    )

    @field_validator("code", mode="before")
    @classmethod
    def ensure_code(cls, v: Any) -> str:
        return str(v) if v is not None else ""

    @field_validator("status", mode="before")
    @classmethod
    def ensure_status(cls, v: Any) -> str:
        return str(v) if v is not None else "ACTIVE"


# ----------------------------------------------------------------- Delete ---
class DeleteResponse(BaseModel):
    """Kết quả xoá thành công."""

    model_config = ConfigDict(from_attributes=True)

    message: str = Field(..., description="Thông báo kết quả xoá.")
    deleted_id: int = Field(..., description="ID của bản ghi vừa bị xoá.")
    deleted_batches: int | None = Field(default=None, description="Số lô nông sản bị xoá kèm.")


# ------------------------------------------------------------ Audit log ---
class AuditLogResponse(BaseModel):
    """Một dòng lịch sử thao tác trong response của GET /audit-logs."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="Mã dòng log.")
    user_id: int = Field(..., description="ID tài khoản thực hiện.")
    username: str = Field(..., description="Tên đăng nhập.")
    action: str = Field(..., description="Hành động: create, update, delete.")
    entity: str = Field(..., description="Đối tượng tác động: farm, batch.")
    entity_id: int = Field(..., description="ID bản ghi bị tác động.")
    created_at: datetime = Field(..., description="Thời điểm ghi log (UTC).")
    source_ip: str | None = None
    operation: str | None = None
    organization_id: int | None = None
    batch_ids: list[int] = Field(default_factory=list)
    location_id: int | None = None
    location_name: str | None = None
    location_address: str | None = None


# ------------------------------------------------------------- Handover (T-35, T-36, T-37, T-38) ---
class HandoverCreate(BaseModel):
    """Dữ liệu gửi lên khi tạo yêu cầu bàn giao lô nông sản (POST /batches/{id}/handover)."""

    to_org_id: int = Field(
        ...,
        gt=0,
        description="ID tổ chức tiếp nhận lô hàng (phải khác tổ chức hiện tại).",
        examples=[2],
    )
    note: str | None = Field(
        default=None,
        max_length=500,
        description="Ghi chú kèm theo khi bàn giao (tùy chọn).",
        examples=["Bàn giao đợt 1 để sơ chế và đóng gói xuất khẩu"],
    )


class HandoverRejectRequest(BaseModel):
    """Dữ liệu gửi lên khi từ chối bàn giao (POST /handovers/{id}/reject)."""

    reject_reason: str = Field(
        ...,
        min_length=10,
        max_length=500,
        description="Lý do từ chối (bắt buộc, tối thiểu 10 ký tự).",
        examples=["Nông sản không đạt tiêu chuẩn độ ẩm theo thỏa thuận."],
    )


class HandoverRespond(BaseModel):
    """Dữ liệu phản hồi yêu cầu bàn giao (tương thích ngược POST /handovers/{id}/respond)."""

    action: str = Field(
        ...,
        description="Hành động xử lý: 'ACCEPT' (nhận lô) hoặc 'REJECT' (từ chối).",
        examples=["ACCEPT", "REJECT"],
    )
    reject_reason: str | None = Field(
        default=None,
        max_length=500,
        description="Lý do từ chối (bắt buộc khi action='REJECT', tối thiểu 10 ký tự).",
        examples=["Nông sản không đạt độ chín theo tiêu chuẩn quy định"],
    )

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        upper = v.strip().upper()
        if upper not in ("ACCEPT", "REJECT"):
            raise ValueError("Hành động phải là 'ACCEPT' hoặc 'REJECT'.")
        return upper

    @model_validator(mode="after")
    def validate_reject_reason(self) -> "HandoverRespond":
        if self.action == "REJECT":
            if not self.reject_reason or len(self.reject_reason.strip()) < 10:
                raise ValueError("Lý do từ chối là bắt buộc và phải có tối thiểu 10 ký tự.")
        return self


class HandoverOut(BaseModel):
    """Dữ liệu trả về cho một yêu cầu bàn giao."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="Mã định danh bàn giao.")
    batch_id: int = Field(..., description="Mã lô nông sản.")
    from_org_id: int = Field(..., description="ID tổ chức gửi.")
    to_org_id: int = Field(..., description="ID tổ chức nhận.")
    status: str = Field(..., description="Trạng thái: PENDING, ACCEPTED, REJECTED.")
    reject_reason: str | None = Field(default=None, description="Lý do từ chối (nếu có).")
    is_overdue: bool = Field(default=False, description="Cờ cảnh báo bàn giao quá hạn 48 giờ (T-56).")
    created_at: datetime = Field(..., description="Thời điểm gửi yêu cầu.")
    updated_at: datetime = Field(..., description="Thời điểm cập nhật mới nhất.")

    # Thông tin mở rộng hỗ trợ frontend
    batch_code: str | None = Field(default=None, description="Mã code của lô nông sản.")
    batch_product_name: str | None = Field(default=None, description="Tên sản phẩm của lô.")
    batch_quantity: float | None = Field(default=None, description="Khối lượng của lô (kg).")
    batch_unit: str = "kg"
    note: str | None = None
    from_org_name: str | None = Field(default=None, description="Tên tổ chức gửi.")
    to_org_name: str | None = Field(default=None, description="Tên tổ chức nhận.")


# ------------------------------------------------------------- Batch Events (T-23, T-31) ---
class BatchEventCreate(BaseModel):
    """Dữ liệu client gửi lên khi tạo sự kiện mới cho lô (``POST /batches/{batch_id}/events``)."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "event_type": "HARVEST",
                "event_data": "Thu hoạch xoài cát Chu đợt 1, nhiệt độ bảo quản 15°C.",
            }
        }
    )

    event_type: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Loại sự kiện (HARVEST, HANDOVER_INIT, HANDOVER_ACCEPT, HANDOVER_REJECT...).",
        examples=["HARVEST"],
    )
    event_data: str | None = Field(
        default=None,
        max_length=2000,
        description="Mô tả sự kiện dạng chuỗi.",
        examples=["Thu hoạch xoài cát Chu đợt 1, nhiệt độ bảo quản 15°C."],
    )
    payload: dict[str, Any] | None = Field(
        default=None,
        description="Dữ liệu payload JSON có cấu trúc của sự kiện.",
    )


class BatchEventOut(BaseModel):
    """Dữ liệu trả về cho một sự kiện vòng đời lô nông sản (Timeline T-31, T-32)."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="Mã định danh sự kiện.")
    batch_id: int = Field(..., description="Mã lô nông sản.")
    event_type: str = Field(..., description="Loại sự kiện (HARVEST, HANDOVER_INIT, HANDOVER_ACCEPT...).")
    payload: dict[str, Any] = Field(default_factory=dict, description="Payload dữ liệu JSON của sự kiện.")
    organization_id: int | None = Field(default=None, description="ID tổ chức thực hiện.")
    organization_name: str | None = Field(default=None, description="Tên tổ chức thực hiện.")
    created_by_user_id: int | None = Field(default=None, description="ID tài khoản thực hiện.")
    username: str | None = Field(default=None, description="Tên tài khoản thực hiện.")
    timestamp: datetime = Field(..., description="Thời điểm ghi nhận sự kiện (UTC).")
    prev_hash: str = Field(..., description="Mã băm SHA-256 của sự kiện liền kề trước.")
    current_hash: str = Field(..., description="Mã băm SHA-256 của sự kiện hiện tại.")

    # Các trường tương thích ngược Sprint 1
    event_data: str | None = Field(default=None, description="Dữ liệu sự kiện (tương thích ngược).")
    user_id: int | None = Field(default=None, description="ID tài khoản (tương thích ngược).")
    created_at: datetime | None = Field(default=None, description="Thời điểm (tương thích ngược).")
    record_hash: str | None = Field(default=None, description="Mã băm (tương thích ngược).")
    notes: str | None = Field(default=None, description="Ghi chú (tương thích ngược).")
    from_org_id: int | None = Field(default=None, description="Tổ chức từ (tương thích ngược).")
    to_org_id: int | None = Field(default=None, description="Tổ chức đến (tương thích ngược).")


class BatchEventResponse(BatchEventOut):
    """Alias cho BatchEventOut."""


class BatchIntegrityResponse(BaseModel):
    """Kết quả kiểm tra toàn vẹn chuỗi sự kiện của một lô nông sản (T-28, T-29)."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "is_valid": True,
                "valid": True,
                "batch_id": 1,
                "total_events": 3,
                "message": "Toàn bộ 3 sự kiện của lô #1 đều hợp lệ và đảm bảo tính toàn vẹn dữ liệu.",
            }
        }
    )

    is_valid: bool = Field(default=True, description="True nếu chuỗi toàn vẹn, False nếu có vi phạm.")
    valid: bool | None = Field(default=None, description="Alias cho is_valid (tương thích ngược).")
    batch_id: int = Field(..., description="ID lô nông sản.")
    total_events: int | None = Field(default=None, description="Tổng số sự kiện.")
    tampered_event_id: int | None = Field(default=None, description="ID sự kiện bị can thiệp đầu tiên (nếu có lỗi).")
    event_id: int | None = Field(default=None, description="Alias cho tampered_event_id.")
    index: int | None = Field(default=None, description="Vị trí index 0-based của sự kiện lỗi trong chuỗi.")
    error_type: str | None = Field(
        default=None,
        description="Loại lỗi phát hiện: 'HASH_MISMATCH' hoặc 'CHAIN_BROKEN'.",
    )
    expected_hash: str | None = Field(default=None, description="Mã băm kỳ vọng.")
    actual_hash: str | None = Field(default=None, description="Mã băm thực tế trong cơ sở dữ liệu.")
    message: str | None = Field(default=None, description="Thông báo chi tiết vị trí đứt mạch/sai băm.")

    @model_validator(mode="after")
    def sync_valid_fields(self) -> "BatchIntegrityResponse":
        if self.valid is None:
            self.valid = self.is_valid
        if self.event_id is None and self.tampered_event_id is not None:
            self.event_id = self.tampered_event_id
        if self.tampered_event_id is None and self.event_id is not None:
            self.tampered_event_id = self.event_id
        return self


# ------------------------------------------------------------- Sprint 3: Split & Merge (T-40, T-44) ---
class BatchSplitItem(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    """Một phần khối lượng tách cho lô con (T-40)."""

    quantity: float = Field(..., gt=0, description="Khối lượng của lô con mới (phải > 0).", examples=[400.0])

    @field_validator("quantity")
    @classmethod
    def precision(cls, value):
        return validate_quantity(value)


class BatchSplitRequest(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    """Yêu cầu tách lô nông sản (POST /batches/{id}/split)."""

    items: list[BatchSplitItem] | None = Field(default=None, description="Danh sách khối lượng các lô con cần tách.")
    child_quantities: list[float] | None = Field(
        default=None, description="Danh sách khối lượng các lô con dạng số (tương thích).")

    @model_validator(mode="before")
    @classmethod
    def parse_flexible_split_payload(cls, data: Any) -> Any:
        if isinstance(data, list):
            items = []
            for x in data:
                q = float(x.get("quantity") if isinstance(x, dict) else x)
                items.append({"quantity": q})
            return {"items": items, "child_quantities": [it["quantity"] for it in items]}
        if isinstance(data, dict):
            if "child_quantities" in data and not data.get("items"):
                cq = data["child_quantities"]
                return {
                    "items": [{"quantity": float(q)} for q in cq],
                    "child_quantities": [float(q) for q in cq],
                }
            if "items" in data and not data.get("child_quantities"):
                items = data["items"]
                return {
                    "items": items,
                    "child_quantities": [float(it.get("quantity") if isinstance(it, dict) else it) for it in items],
                }
        return data

    @model_validator(mode="after")
    def ensure_has_items(self) -> "BatchSplitRequest":
        if not self.items:
            raise ValueError("Danh sách khối lượng các lô con không được để trống.")
        return self


class BatchSplitResponse(BaseModel):
    """Kết quả tách lô nông sản thành công (T-40, T-41)."""

    model_config = ConfigDict(from_attributes=True)

    parent_batch: BatchResponse = Field(..., description="Thông tin lô mẹ sau khi trừ khối lượng.")
    child_batches: list[BatchResponse] = Field(..., description="Danh sách các lô con vừa được sinh ra.")
    message: str = Field(default="Tách lô nông sản thành công.")


class BatchMergeItem(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    """Thông tin lô mẹ và lượng lấy để gộp (T-44, T-45)."""

    parent_batch_id: int = Field(..., gt=0, description="ID của lô mẹ cần lấy khối lượng.")
    quantity: float = Field(..., gt=0, description="Khối lượng lấy từ lô mẹ này (phải > 0).")

    @field_validator("quantity")
    @classmethod
    def precision(cls, value):
        return validate_quantity(value)


class BatchMergeRequest(BaseModel):
    """Yêu cầu gộp nhiều lô nông sản (POST /batches/merge - T-44, T-45)."""

    items: list[BatchMergeItem] = Field(..., min_length=2, description="Danh sách tối thiểu 2 lô mẹ cần gộp.")
    product_id: int = Field(..., gt=0, description="Mã sản phẩm chung của các lô gộp.")


class BatchMergeResponse(BaseModel):
    """Kết quả gộp lô nông sản thành công (T-44, T-46)."""

    model_config = ConfigDict(from_attributes=True)

    merged_batch: BatchResponse = Field(..., description="Lô mới được tạo từ việc gộp.")
    parent_batches: list[dict[str, Any]] = Field(..., description="Danh sách các lô mẹ và số lượng đã lấy.")
    message: str = Field(default="Gộp lô nông sản thành công.")


# ------------------------------------------------------------- Sprint 3: Traceability & BFS (T-49, T-50) ---
class TraceNode(BaseModel):
    """Thông tin một mắt xích trong cây phả hệ tổ tiên (T-49)."""

    model_config = ConfigDict(from_attributes=True)

    batch_id: int
    code: str
    unit: str = "kg"
    product_id: int | None = None
    product_name: str | None = None
    plot_id: int | None = None
    plot_name: str | None = None
    farm_name: str | None = None
    plot_area: float | None = None
    location: str | None = None
    owner: str | None = None
    current_org_id: int | None = None
    current_org_name: str | None = None
    initial_quantity: float | None = None
    remaining_quantity: float | None = None
    harvest_date: str | None = None
    relation_type: str | None = None
    transferred_quantity: float | None = None
    level: int = 0
    status: str | None = None
    is_consumed: bool = False


class RootBatchInfo(BaseModel):
    """Thông tin vùng trồng / thửa đất ban đầu của lô thu hoạch gốc (T-49)."""

    model_config = ConfigDict(from_attributes=True)

    batch_id: int
    code: str
    unit: str = "kg"
    product_name: str | None = None
    plot_id: int | None = None
    plot_name: str | None = None
    farm_name: str | None = None
    plot_area: float | None = None
    location: str | None = None
    owner: str | None = None
    harvest_date: str | None = None
    initial_quantity: float | None = None


class TraceBackResponse(BaseModel):
    """Kết quả truy ngược nguồn gốc phả hệ BFS (GET /batches/{id}/trace-back - T-49, T-50)."""

    target_batch: dict[str, Any] = Field(..., description="Thông tin lô đích đang truy xuất.")
    ancestors_by_level: dict[int, list[TraceNode]] = Field(..., description="Cây phả hệ phân tầng theo khoảng cách thế hệ.")
    root_batches: list[RootBatchInfo] = Field(..., description="Danh sách các lô thu hoạch gốc và thửa đất ban đầu.")
    total_ancestors: int = Field(..., description="Tổng số tổ tiên đã tìm thấy.")


# ------------------------------------------------------------- Sprint 4: Forward Traceability BFS (S-26, S-27) ---
class TraceForwardNode(BaseModel):
    """Thông tin một mắt xích hậu duệ trong cây truy xuôi (S-26, S-27)."""

    model_config = ConfigDict(from_attributes=True)
    location_id: int | None = None
    current_location: str | None = None
    current_location_name: str | None = None

    batch_id: int
    code: str
    parent_batch_id: int | None = None
    relation_type: str | None = None
    transferred_quantity: float | None = None
    level: int = 1
    current_org_id: int | None = None
    current_org_name: str | None = None
    location: str | None = None
    owner: str | None = None
    plot_id: int | None = None
    plot_name: str | None = None
    farm_name: str | None = None
    initial_quantity: float | None = None
    remaining_quantity: float | None = None
    status: str | None = "ACTIVE"
    is_consumed: bool = False
    harvest_date: str | None = None
    product_id: int | None = None
    product_name: str | None = None
    unit: str = "kg"
    is_masked: bool = False


class TerminalBatchInfo(BaseModel):
    """Thông tin lô lá cuối cùng (chưa có con hoặc đã tiêu thụ - S-27, S-29)."""

    model_config = ConfigDict(from_attributes=True)

    location_id: int | None = None
    current_location: str | None = None
    current_location_name: str | None = None
    batch_id: int
    code: str
    unit: str = "kg"
    product_name: str | None = None
    current_org_id: int | None = None
    current_org_name: str | None = None
    location: str | None = None
    initial_quantity: float | None = None
    remaining_quantity: float | None = None
    status: str | None = None
    is_consumed: bool = False
    harvest_date: str | None = None


class TraceForwardEdge(BaseModel):
    """A stored relation between authorized returned lots."""

    parent_batch_id: int
    child_batch_id: int
    relation_type: str
    transferred_quantity: float | None = None


class TraceForwardResponse(BaseModel):
    """Kết quả truy xuôi nguồn gốc phả hệ BFS (GET /batches/{id}/trace-forward - S-26, S-27)."""

    edges: list[TraceForwardEdge] = Field(
        default_factory=list, description="Quan hệ thật giữa các lô được phép xem trong kết quả."
    )
    target_batch: dict[str, Any] = Field(..., description="Thông tin lô gốc đang truy xuôi.")
    descendants_by_level: dict[int, list[TraceForwardNode]] = Field(
        ..., description="Danh sách các thế hệ hậu duệ phân tầng theo khoảng cách."
    )
    terminal_batches: list[TerminalBatchInfo] = Field(
        ..., description="Danh sách các lô lá cuối chuỗi cung ứng hoặc đã tiêu thụ."
    )
    total_descendants: int = Field(..., description="Tổng số lô hậu duệ tìm thấy.")


# ------------------------------------------------------------- Sprint 4: Consumed (S-29) ---
class BatchConsumeRequest(BaseModel):
    """Yêu cầu ghi nhận lô hàng đã bán hết cho người tiêu dùng (POST /batches/{id}/consume - S-29)."""

    notes: str | None = Field(default=None, description="Ghi chú khi tiêu thụ / bán hết lô hàng.")


class BatchConsumeResponse(BaseModel):
    """Kết quả ghi nhận lô nông sản đã tiêu thụ thành công (S-29)."""

    model_config = ConfigDict(from_attributes=True)

    batch: BatchResponse = Field(..., description="Thông tin lô nông sản sau khi cập nhật CONSUMED.")
    event: BatchEventOut = Field(..., description="Sự kiện CONSUMED vừa được ghi vào hash-chain.")
    message: str = Field(default="Ghi nhận lô nông sản đã tiêu thụ thành công.")


# ------------------------------------------------------------- Sprint 3: Batch Summary (T-58) ---
class BatchSummaryResponse(BaseModel):
    """Tổng hợp thông tin chi tiết lô trung tâm tối ưu <= 3 truy vấn SQL (GET /batches/{id}/summary - T-58)."""

    batch: BatchResponse
    plot: dict[str, Any] | None = None
    product: dict[str, Any] | None = None
    current_org: dict[str, Any] | None = None
    direct_parents: list[dict[str, Any]] = Field(default_factory=list)
    direct_children: list[dict[str, Any]] = Field(default_factory=list)
    has_pending_handover: bool = False
    pending_handover_id: int | None = None
    can_split: bool = True
    can_merge: bool = True
    can_handover: bool = True
    can_consume: bool = False
