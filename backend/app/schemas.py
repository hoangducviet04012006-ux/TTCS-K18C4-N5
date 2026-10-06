"""Pydantic schemas - định nghĩa "hợp đồng" dữ liệu vào/ra của API.

Tách riêng schemas (Pydantic) khỏi models (SQLAlchemy) giúp:
- Không lộ cấu trúc bảng ra ngoài API.
- Validate dữ liệu đầu vào tự động và sinh tài liệu Swagger chuẩn.
"""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class HealthResponse(BaseModel):
    """Response của endpoint ``GET /health``.

    Ví dụ::

        {"status": "ok", "database": "connected"}
    """

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
# Sprint 4: đăng nhập + phân quyền cơ bản. Không JWT -> response đăng nhập
# chỉ có `username` + `role`, client tự gửi lại thông tin đăng nhập
# (HTTP Basic) ở các request sau.
class LoginRequest(BaseModel):
    """Dữ liệu client gửi lên khi đăng nhập (``POST /auth/login``)."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"username": "admin", "password": "123456"},
        },
    )

    username: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Tên đăng nhập.",
        examples=["admin"],
    )
    password: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Mật khẩu dạng thô (backend tự băm SHA-256 để so sánh với database).",
        examples=["123456"],
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
    """Kết quả đăng nhập thành công: ``username``, ``role``, ``organization_id``, ``organization_name``."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "username": "admin",
                "role": "admin",
                "organization_id": 1,
                "organization_name": "Hợp tác xã Nông sản An Toàn Đồng Tháp",
            }
        },
    )

    username: str = Field(
        ...,
        description="Tên đăng nhập vừa xác thực thành công.",
        examples=["admin"],
    )
    role: str = Field(
        ...,
        description="Vai trò của tài khoản: `admin` (toàn quyền) hoặc `farmer` (nông dân).",
        examples=["admin", "farmer"],
    )
    organization_id: int | None = Field(
        default=None,
        description="ID tổ chức / hợp tác xã trực thuộc.",
        examples=[1],
    )
    organization_name: str | None = Field(
        default=None,
        description="Tên tổ chức / hợp tác xã trực thuộc.",
        examples=["Hợp tác xã Nông sản An Toàn Đồng Tháp"],
    )


class AccountLockedResponse(BaseModel):
    """Body lỗi **403 Forbidden** khi tài khoản bị tạm khoá (Sprint 6)."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "detail": (
                    "Tài khoản 'farmer' đã bị tạm khoá do nhập sai mật khẩu "
                    "5 lần liên tiếp. Vui lòng thử lại sau 15 phút."
                )
            }
        },
    )

    detail: str = Field(
        ...,
        description="Lý do khoá tài khoản + thời gian chờ còn lại (tiếng Việt).",
    )


class UserResponse(BaseModel):
    """Thông tin tài khoản trả ra API (``GET /users`` - chỉ admin)."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": 1,
                "username": "admin",
                "role": "admin",
                "organization_id": 1,
            }
        },
    )

    id: int = Field(..., description="Mã định danh tài khoản.", examples=[1])
    username: str = Field(..., description="Tên đăng nhập.", examples=["admin"])
    role: str = Field(..., description="Vai trò: `admin` hoặc `farmer`.", examples=["admin"])
    organization_id: int | None = Field(
        default=None,
        description="ID tổ chức trực thuộc.",
        examples=[1],
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
    coordinates: str | None = Field(
        default=None,
        max_length=255,
        description="Tọa độ GPS của thửa đất (ví dụ: '10.4539, 105.6324').",
        examples=["10.4539, 105.6324"],
    )
    owner: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Chủ sở hữu vùng trồng.",
        examples=["Hợp tác xã Xoài Mỹ Xương"],
    )


class FarmUpdate(FarmCreate):
    """Dữ liệu client gửi lên khi **sửa** vùng trồng (``PUT /farms/{farm_id}``).

    Kế thừa ``FarmCreate`` để dùng lại đúng bộ quy tắc validate (tên/địa điểm/
    chủ sở hữu không rỗng, diện tích > 0). ``PUT`` là cập nhật *thay thế* nên
    client gửi **đầy đủ các trường** như khi tạo mới; backend ghi đè giá trị cũ.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Vùng trồng xoài Cao Lãnh",
                "location": "Xã Mỹ Xương, Huyện Cao Lãnh, Tỉnh Đồng Tháp",
                "area": 3.2,
                "coordinates": "10.4539, 105.6324",
                "owner": "Hợp tác xã Xoài Mỹ Xương",
            }
        },
    )


class FarmResponse(BaseModel):
    """Dữ liệu API trả về cho một vùng trồng (kèm ``id`` và ``organization_id``)."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"example": _FARM_EXAMPLE},
    )

    id: int = Field(..., description="Mã định danh vùng trồng.", examples=[1])
    organization_id: int = Field(..., description="ID tổ chức trực thuộc.", examples=[1])
    name: str = Field(..., description="Tên vùng trồng.")
    location: str = Field(..., description="Địa điểm của vùng trồng.")
    area: float = Field(..., description="Diện tích canh tác (ha).")
    coordinates: str | None = Field(default=None, description="Tọa độ GPS của thửa đất.")
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


class BatchUpdate(BatchCreate):
    """Dữ liệu client gửi lên khi **sửa** lô nông sản (``PUT /batches/{batch_id}``).

    Kế thừa ``BatchCreate`` (dùng lại validate: ``farm_id`` > 0, ``quantity`` > 0,
    ``harvest_date`` đúng định dạng ISO). Client gửi **đầy đủ 4 trường**; router
    trả ``404`` nếu lô hoặc ``farm_id`` mới không tồn tại.

    Lưu ý: đổi ``farm_id`` = chuyển lô sang vùng trồng khác (vẫn phải tồn tại).

    Ví dụ::

        {"farm_id": 1, "product_name": "Xoài cát Chu", "quantity": 150,
         "harvest_date": "2026-01-16"}
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "farm_id": 1,
                "product_name": "Xoài cát Chu",
                "quantity": 150,
                "harvest_date": "2026-01-16",
            }
        },
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
    current_org_id: int | None = Field(default=None, description="ID tổ chức đang nắm giữ lô hàng.")
    current_org_name: str | None = Field(default=None, description="Tên tổ chức đang nắm giữ lô hàng.")
    parent_id: int | None = Field(default=None, description="ID lô mẹ trực tiếp (nếu có).")
    remaining_quantity: float | None = Field(default=None, description="Khối lượng còn lại (kg).")
    status: str | None = Field(default="Đang lưu kho", description="Trạng thái lô nông sản.")
    unit: str | None = Field(default="kg", description="Đơn vị khối lượng.")


class BatchSummaryResponse(BaseModel):
    """Tóm tắt thông tin một lô nông sản (dùng cho lô mẹ / lô con trực tiếp)."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="Mã định danh lô.")
    product_name: str = Field(..., description="Tên sản phẩm.")
    quantity: float = Field(..., description="Khối lượng ban đầu (kg).")
    remaining_quantity: float | None = Field(default=None, description="Khối lượng còn lại.")
    unit: str = Field(default="kg", description="Đơn vị khối lượng.")
    status: str = Field(default="Đang lưu kho", description="Trạng thái lô.")
    current_org_name: str | None = Field(default=None, description="Tên tổ chức đang nắm giữ.")


class BatchDetailResponse(BaseModel):
    """Dữ liệu chi tiết đầy đủ của một lô nông sản phục vụ S-25 Trang chi tiết lô."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="Mã định danh lô nông sản.")
    farm_id: int = Field(..., description="ID vùng trồng xuất xứ.")
    farm_name: str | None = Field(default=None, description="Tên vùng trồng xuất xứ.")
    farm_location: str | None = Field(default=None, description="Địa điểm vùng trồng xuất xứ.")
    product_name: str = Field(..., description="Tên sản phẩm.")
    initial_quantity: float = Field(..., description="Khối lượng ban đầu (kg).")
    remaining_quantity: float = Field(..., description="Khối lượng còn lại (kg).")
    unit: str = Field(default="kg", description="Đơn vị khối lượng.")
    harvest_date: date = Field(..., description="Ngày thu hoạch.")
    status: str = Field(default="Đang lưu kho", description="Trạng thái lô.")
    current_org_id: int | None = Field(default=None, description="ID tổ chức đang nắm giữ.")
    current_org_name: str | None = Field(default=None, description="Tên tổ chức đang nắm giữ.")
    parent_id: int | None = Field(default=None, description="ID lô mẹ trực tiếp (nếu có).")
    parent: BatchSummaryResponse | None = Field(default=None, description="Thông tin lô mẹ trực tiếp.")
    children: list[BatchSummaryResponse] = Field(default_factory=list, description="Danh sách các lô con trực tiếp.")


# ----------------------------------------------------------------- Chung ---
class DeleteResponse(BaseModel):
    """Kết quả một lần xoá thành công (``DELETE /farms/{id}``, ``DELETE /batches/{id}``).

    Cố tình trả **200 OK kèm nội dung** (thay vì ``204 No Content``) để giao diện
    hiển thị được thông báo "đã xoá cái gì" cho người dùng.

    Ví dụ::

        {"message": "Đã xoá vùng trồng #2 và 2 lô nông sản thuộc vùng đó.",
         "deleted_id": 2, "deleted_batches": 2}
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "message": "Đã xoá vùng trồng #2 và 2 lô nông sản thuộc vùng đó.",
                "deleted_id": 2,
                "deleted_batches": 2,
            }
        },
    )

    message: str = Field(
        ...,
        description="Thông báo kết quả xoá (hiển thị trực tiếp trên giao diện).",
        examples=["Đã xoá vùng trồng #2 và 2 lô nông sản thuộc vùng đó."],
    )
    deleted_id: int = Field(
        ...,
        description="ID của bản ghi vừa bị xoá.",
        examples=[2],
    )
    deleted_batches: int | None = Field(
        default=None,
        description=(
            "Số lô nông sản bị xoá kèm - chỉ có giá trị khi gọi "
            "`DELETE /farms/{farm_id}` (xoá vùng trồng sẽ xoá theo mọi lô thuộc "
            "vùng đó). `null` khi xoá một lô nông sản."
        ),
        examples=[2],
    )


# ------------------------------------------------------------ Audit log ---
# Sprint 7: lịch sử thao tác ("ai đã làm gì"). Chỉ admin xem được
# (`GET /audit-logs`) - xem `app/routers/audit.py`.
_AUDIT_LOG_EXAMPLE: dict = {
    "id": 3,
    "user_id": 1,
    "username": "admin",
    "action": "update",
    "entity": "farm",
    "entity_id": 2,
    "created_at": "2026-01-20T03:15:42.123456",
}


class AuditLogResponse(BaseModel):
    """Một dòng lịch sử thao tác trong response của ``GET /audit-logs``.

    Mỗi dòng cho biết **ai** (``user_id`` / ``username``) đã **làm gì**
    (``action``) trên **dữ liệu nào** (``entity`` + ``entity_id``) và **lúc nào**
    (``created_at``, UTC -> ``null`` `timezone`).

    Ví dụ::

        {"id": 3, "user_id": 1, "username": "admin", "action": "update",
         "entity": "farm", "entity_id": 2, "created_at": "2026-01-20T03:15:42.123456"}
    """

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"example": _AUDIT_LOG_EXAMPLE},
    )

    id: int = Field(..., description="Mã dòng log.", examples=[3])
    user_id: int = Field(
        ...,
        description="ID tài khoản đã thực hiện thao tác (khoá ngoại tới bảng `users`).",
        examples=[1],
    )
    username: str = Field(
        ...,
        description=(
            "Tên đăng nhập của người thực hiện - tiện hiển thị, suy ra từ "
            "`user_id` (không phải cột riêng trong bảng `audit_logs`)."
        ),
        examples=["admin", "farmer"],
    )
    action: str = Field(
        ...,
        description="Hành động đã xảy ra: `create` (tạo), `update` (sửa), `delete` (xoá).",
        examples=["create", "update", "delete"],
    )
    entity: str = Field(
        ...,
        description="Loại dữ liệu bị tác động: `farm` (vùng trồng) hoặc `batch` (lô nông sản).",
        examples=["farm", "batch"],
    )
    entity_id: int = Field(
        ...,
        description="ID bản ghi bị tác động (trong bảng `farms` hoặc `batches`).",
        examples=[2],
    )
    created_at: datetime = Field(
        ...,
        description="Thời điểm ghi log (UTC, ISO 8601).",
        examples=["2026-01-20T03:15:42.123456"],
    )


# ------------------------------------------------------------- Handover ---
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


class HandoverRespond(BaseModel):
    """Dữ liệu phản hồi yêu cầu bàn giao (POST /handovers/{id}/respond)."""

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
    created_at: datetime = Field(..., description="Thời điểm gửi yêu cầu.")
    updated_at: datetime = Field(..., description="Thời điểm cập nhật mới nhất.")

    # Thông tin mở rộng hỗ trợ frontend
    batch_product_name: str | None = Field(default=None, description="Tên sản phẩm của lô.")
    batch_quantity: float | None = Field(default=None, description="Khối lượng của lô (kg).")
    from_org_name: str | None = Field(default=None, description="Tên tổ chức gửi.")
    to_org_name: str | None = Field(default=None, description="Tên tổ chức nhận.")


class BatchEventOut(BaseModel):
    """Dữ liệu trả về cho một sự kiện vòng đời lô nông sản."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="Mã định danh sự kiện.")
    batch_id: int = Field(..., description="Mã lô nông sản.")
    event_type: str = Field(..., description="Loại sự kiện (HANDOVER_PENDING, HANDOVER_ACCEPTED, HANDOVER_REJECTED,...).")
    user_id: int | None = Field(default=None, description="ID tài khoản thực hiện.")
    from_org_id: int | None = Field(default=None, description="ID tổ chức gửi (nếu có).")
    to_org_id: int | None = Field(default=None, description="ID tổ chức nhận (nếu có).")
    notes: str | None = Field(default=None, description="Ghi chú chi tiết sự kiện.")
    created_at: datetime = Field(..., description="Thời điểm ghi nhận sự kiện.")


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
        description="Loại sự kiện (VD: BATCH_CREATED, HARVEST, PROCESSING, TEMP_CHECK, TRANSPORT, QUALITY_INSPECTION...).",
        examples=["HARVEST"],
    )
    event_data: str | None = Field(
        default=None,
        max_length=2000,
        description="Dữ liệu / thông tin mô tả chi tiết của sự kiện.",
        examples=["Thu hoạch xoài cát Chu đợt 1, nhiệt độ bảo quản 15°C."],
    )


class BatchEventResponse(BaseModel):
    """Dữ liệu trả về cho một sự kiện lô nông sản (append-only log)."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="ID sự kiện.", examples=[1])
    batch_id: int = Field(..., description="ID lô nông sản.", examples=[1])
    event_type: str = Field(..., description="Loại sự kiện.", examples=["HARVEST"])
    event_data: str | None = Field(default=None, description="Thông tin dữ liệu sự kiện.")
    user_id: int | None = Field(default=None, description="ID người thực hiện.")
    from_org_id: int | None = Field(default=None, description="ID tổ chức từ.")
    to_org_id: int | None = Field(default=None, description="ID tổ chức đến.")
    notes: str | None = Field(default=None, description="Ghi chú.")
    created_at: datetime = Field(..., description="Thời điểm ghi nhận sự kiện (UTC).")
    prev_hash: str = Field(..., description="Hash SHA-256 của sự kiện liền trước của lô.")
    record_hash: str = Field(..., description="Hash SHA-256 của bản ghi hiện tại.")


class BatchIntegrityResponse(BaseModel):
    """Kết quả kiểm tra toàn vẹn chuỗi sự kiện của một lô nông sản (Sprint S-12)."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "valid": True,
                "batch_id": 1,
                "total_events": 3,
                "message": "Toàn bộ 3 sự kiện của lô #1 đều hợp lệ và đảm bảo tính toàn vẹn dữ liệu.",
            }
        }
    )

    valid: bool = Field(..., description="`true` nếu chuỗi sự kiện toàn vẹn, `false` nếu bị đứt mạch/sai băm.")
    batch_id: int = Field(..., description="ID lô nông sản.")
    total_events: int | None = Field(default=None, description="Tổng số sự kiện (khi valid = true).")
    event_id: int | None = Field(default=None, description="ID của sự kiện bị lỗi/đứt mạch đầu tiên (khi valid = false).")
    index: int | None = Field(default=None, description="Vị trí (index 0-based) của sự kiện bị lỗi trong chuỗi.")
    error_type: str | None = Field(
        default=None,
        description="Loại lỗi phát hiện (`PREV_HASH_MISMATCH`, `RECORD_HASH_MISMATCH`).",
    )
    expected_hash: str | None = Field(default=None, description="Mã băm kỳ vọng theo công thức hash chain.")
    actual_hash: str | None = Field(default=None, description="Mã băm thực tế ghi trong cơ sở dữ liệu / prev_hash.")
    message: str | None = Field(default=None, description="Thông báo chi tiết giải thích vị trí đứt mạch.")
