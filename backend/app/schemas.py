"""Pydantic schemas - định nghĩa "hợp đồng" dữ liệu vào/ra của API.

Tách riêng schemas (Pydantic) khỏi models (SQLAlchemy) giúp:
- Không lộ cấu trúc bảng ra ngoài API.
- Validate dữ liệu đầu vào tự động và sinh tài liệu Swagger chuẩn.
"""

from datetime import date, datetime

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
