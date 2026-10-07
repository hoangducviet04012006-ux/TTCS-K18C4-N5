"""Pydantic schemas - Ä‘á»‹nh nghÄ©a "há»£p Ä‘á»“ng" dá»¯ liá»‡u vÃ o/ra cá»§a API.

TÃ¡ch riÃªng schemas (Pydantic) khá»i models (SQLAlchemy) giÃºp:
- KhÃ´ng lá»™ cáº¥u trÃºc báº£ng ra ngoÃ i API.
- Validate dá»¯ liá»‡u Ä‘áº§u vÃ o tá»± Ä‘á»™ng vÃ  sinh tÃ i liá»‡u Swagger chuáº©n.
"""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class HealthResponse(BaseModel):
    """Response cá»§a endpoint ``GET /health``.

    VÃ­ dá»¥::

        {"status": "ok", "database": "connected"}
    """

    model_config = ConfigDict(
        json_schema_extra={"example": {"status": "ok", "database": "connected"}},
    )

    status: str = Field(
        ...,
        description="Tráº¡ng thÃ¡i hoáº¡t Ä‘á»™ng cá»§a API.",
        examples=["ok"],
    )
    database: str = Field(
        default="connected",
        description="Tráº¡ng thÃ¡i káº¿t ná»‘i cÆ¡ sá»Ÿ dá»¯ liá»‡u.",
        examples=["connected", "disconnected"],
    )


# ------------------------------------------------------------------ Auth ---
# Sprint 4: Ä‘Äƒng nháº­p + phÃ¢n quyá»n cÆ¡ báº£n. KhÃ´ng JWT -> response Ä‘Äƒng nháº­p
# chá»‰ cÃ³ `username` + `role`, client tá»± gá»­i láº¡i thÃ´ng tin Ä‘Äƒng nháº­p
# (HTTP Basic) á»Ÿ cÃ¡c request sau.
class LoginRequest(BaseModel):
    """Dá»¯ liá»‡u client gá»­i lÃªn khi Ä‘Äƒng nháº­p (``POST /auth/login``)."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"username": "admin", "password": "123456"},
        },
    )

    username: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="TÃªn Ä‘Äƒng nháº­p.",
        examples=["admin"],
    )
    password: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Máº­t kháº©u dáº¡ng thÃ´ (backend tá»± bÄƒm SHA-256 Ä‘á»ƒ so sÃ¡nh vá»›i database).",
        examples=["123456"],
    )


# ---------------------------------------------------------- Organization ---
class OrganizationCreate(BaseModel):
    """Dá»¯ liá»‡u táº¡o tá»• chá»©c má»›i."""

    name: str = Field(..., min_length=1, max_length=255, description="TÃªn tá»• chá»©c / há»£p tÃ¡c xÃ£.")
    code: str = Field(..., min_length=1, max_length=50, description="MÃ£ Ä‘á»‹nh danh tá»• chá»©c (duy nháº¥t).")
    description: str | None = Field(default=None, max_length=500, description="MÃ´ táº£ tá»• chá»©c.")


class OrganizationResponse(OrganizationCreate):
    """ThÃ´ng tin tá»• chá»©c tráº£ vá» API."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="MÃ£ ID tá»• chá»©c.")
    created_at: datetime = Field(..., description="Thá»i Ä‘iá»ƒm táº¡o.")


class LoginResponse(BaseModel):
    """Káº¿t quáº£ Ä‘Äƒng nháº­p thÃ nh cÃ´ng: ``username``, ``role``, ``organization_id``, ``organization_name``."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "username": "admin",
                "role": "admin",
                "organization_id": 1,
                "organization_name": "Há»£p tÃ¡c xÃ£ NÃ´ng sáº£n An ToÃ n Äá»“ng ThÃ¡p",
            }
        },
    )

    username: str = Field(
        ...,
        description="TÃªn Ä‘Äƒng nháº­p vá»«a xÃ¡c thá»±c thÃ nh cÃ´ng.",
        examples=["admin"],
    )
    role: str = Field(
        ...,
        description="Vai trÃ² cá»§a tÃ i khoáº£n: `admin` (toÃ n quyá»n) hoáº·c `farmer` (nÃ´ng dÃ¢n).",
        examples=["admin", "farmer"],
    )
    organization_id: int | None = Field(
        default=None,
        description="ID tá»• chá»©c / há»£p tÃ¡c xÃ£ trá»±c thuá»™c.",
        examples=[1],
    )
    organization_name: str | None = Field(
        default=None,
        description="TÃªn tá»• chá»©c / há»£p tÃ¡c xÃ£ trá»±c thuá»™c.",
        examples=["Há»£p tÃ¡c xÃ£ NÃ´ng sáº£n An ToÃ n Äá»“ng ThÃ¡p"],
    )


class AccountLockedResponse(BaseModel):
    """Body lá»—i **403 Forbidden** khi tÃ i khoáº£n bá»‹ táº¡m khoÃ¡ (Sprint 6)."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "detail": (
                    "TÃ i khoáº£n 'farmer' Ä‘Ã£ bá»‹ táº¡m khoÃ¡ do nháº­p sai máº­t kháº©u "
                    "5 láº§n liÃªn tiáº¿p. Vui lÃ²ng thá»­ láº¡i sau 15 phÃºt."
                )
            }
        },
    )

    detail: str = Field(
        ...,
        description="LÃ½ do khoÃ¡ tÃ i khoáº£n + thá»i gian chá» cÃ²n láº¡i (tiáº¿ng Viá»‡t).",
    )


class UserResponse(BaseModel):
    """ThÃ´ng tin tÃ i khoáº£n tráº£ ra API (``GET /users`` - chá»‰ admin)."""

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

    id: int = Field(..., description="MÃ£ Ä‘á»‹nh danh tÃ i khoáº£n.", examples=[1])
    username: str = Field(..., description="TÃªn Ä‘Äƒng nháº­p.", examples=["admin"])
    role: str = Field(..., description="Vai trÃ²: `admin` hoáº·c `farmer`.", examples=["admin"])
    organization_id: int | None = Field(
        default=None,
        description="ID tá»• chá»©c trá»±c thuá»™c.",
        examples=[1],
    )


# ------------------------------------------------------------------ Farm ---
_FARM_EXAMPLE: dict = {
    "id": 1,
    "name": "VÃ¹ng trá»“ng xoÃ i Cao LÃ£nh",
    "location": "XÃ£ Má»¹ XÆ°Æ¡ng, Huyá»‡n Cao LÃ£nh, Tá»‰nh Äá»“ng ThÃ¡p",
    "area": 2.5,
    "owner": "Há»£p tÃ¡c xÃ£ XoÃ i Má»¹ XÆ°Æ¡ng",
}


class FarmCreate(BaseModel):
    """Dá»¯ liá»‡u client gá»­i lÃªn khi táº¡o vÃ¹ng trá»“ng má»›i (``POST /farms``).

    Chá»‰ chá»©a cÃ¡c field client Ä‘Æ°á»£c phÃ©p nháº­p - ``id`` do database sinh ra.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "VÃ¹ng trá»“ng xoÃ i Cao LÃ£nh",
                "location": "XÃ£ Má»¹ XÆ°Æ¡ng, Huyá»‡n Cao LÃ£nh, Tá»‰nh Äá»“ng ThÃ¡p",
                "area": 2.5,
                "owner": "Há»£p tÃ¡c xÃ£ XoÃ i Má»¹ XÆ°Æ¡ng",
            }
        },
    )

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="TÃªn vÃ¹ng trá»“ng.",
        examples=["VÃ¹ng trá»“ng xoÃ i Cao LÃ£nh"],
    )
    location: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Äá»‹a Ä‘iá»ƒm cá»§a vÃ¹ng trá»“ng (xÃ£/huyá»‡n/tá»‰nh).",
        examples=["XÃ£ Má»¹ XÆ°Æ¡ng, Huyá»‡n Cao LÃ£nh, Tá»‰nh Äá»“ng ThÃ¡p"],
    )
    area: float = Field(
        ...,
        gt=0,
        description="Diá»‡n tÃ­ch canh tÃ¡c, Ä‘Æ¡n vá»‹ hecta (ha). Pháº£i lá»›n hÆ¡n 0.",
        examples=[2.5],
    )
    coordinates: str | None = Field(
        default=None,
        max_length=255,
        description="Tá»a Ä‘á»™ GPS cá»§a thá»­a Ä‘áº¥t (vÃ­ dá»¥: '10.4539, 105.6324').",
        examples=["10.4539, 105.6324"],
    )
    owner: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Chá»§ sá»Ÿ há»¯u vÃ¹ng trá»“ng.",
        examples=["Há»£p tÃ¡c xÃ£ XoÃ i Má»¹ XÆ°Æ¡ng"],
    )


class FarmUpdate(FarmCreate):
    """Dá»¯ liá»‡u client gá»­i lÃªn khi **sá»­a** vÃ¹ng trá»“ng (``PUT /farms/{farm_id}``).

    Káº¿ thá»«a ``FarmCreate`` Ä‘á»ƒ dÃ¹ng láº¡i Ä‘Ãºng bá»™ quy táº¯c validate (tÃªn/Ä‘á»‹a Ä‘iá»ƒm/
    chá»§ sá»Ÿ há»¯u khÃ´ng rá»—ng, diá»‡n tÃ­ch > 0). ``PUT`` lÃ  cáº­p nháº­t *thay tháº¿* nÃªn
    client gá»­i **Ä‘áº§y Ä‘á»§ cÃ¡c trÆ°á»ng** nhÆ° khi táº¡o má»›i; backend ghi Ä‘Ã¨ giÃ¡ trá»‹ cÅ©.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "VÃ¹ng trá»“ng xoÃ i Cao LÃ£nh",
                "location": "XÃ£ Má»¹ XÆ°Æ¡ng, Huyá»‡n Cao LÃ£nh, Tá»‰nh Äá»“ng ThÃ¡p",
                "area": 3.2,
                "coordinates": "10.4539, 105.6324",
                "owner": "Há»£p tÃ¡c xÃ£ XoÃ i Má»¹ XÆ°Æ¡ng",
            }
        },
    )


class FarmResponse(BaseModel):
    """Dá»¯ liá»‡u API tráº£ vá» cho má»™t vÃ¹ng trá»“ng (kÃ¨m ``id`` vÃ  ``organization_id``)."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"example": _FARM_EXAMPLE},
    )

    id: int = Field(..., description="MÃ£ Ä‘á»‹nh danh vÃ¹ng trá»“ng.", examples=[1])
    organization_id: int = Field(..., description="ID tá»• chá»©c trá»±c thuá»™c.", examples=[1])
    name: str = Field(..., description="TÃªn vÃ¹ng trá»“ng.")
    location: str = Field(..., description="Äá»‹a Ä‘iá»ƒm cá»§a vÃ¹ng trá»“ng.")
    area: float = Field(..., description="Diá»‡n tÃ­ch canh tÃ¡c (ha).")
    coordinates: str | None = Field(default=None, description="Tá»a Ä‘á»™ GPS cá»§a thá»­a Ä‘áº¥t.")
    owner: str = Field(..., description="Chá»§ sá»Ÿ há»¯u vÃ¹ng trá»“ng.")


class ProductCreate(BaseModel):
    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="TÃªn sáº£n pháº©m.",
    )
    code: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="MÃ£ sáº£n pháº©m.",
    )
    active: bool = Field(
        default=True,
        description="Sáº£n pháº©m cÃ²n Ä‘Æ°á»£c phÃ©p chá»n hay khÃ´ng.",
    )


class ProductUpdate(ProductCreate):
    pass


class ProductResponse(ProductCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int


class UnitCreate(BaseModel):
    name: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="TÃªn Ä‘Æ¡n vá»‹ tÃ­nh.",
    )
    symbol: str = Field(
        ...,
        min_length=1,
        max_length=20,
        description="KÃ½ hiá»‡u Ä‘Æ¡n vá»‹ tÃ­nh, vÃ­ dá»¥ kg, táº¥n.",
    )
    active: bool = Field(default=True)


class UnitUpdate(UnitCreate):
    pass


class UnitResponse(UnitCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int

# ----------------------------------------------------------------- Batch ---


_BATCH_EXAMPLE: dict = {
    "id": 1,
    "farm_id": 1,
    "product_name": "XoÃ i cÃ¡t Chu",
    "quantity": 120.5,
    "harvest_date": "2026-01-15",
}


class BatchCreate(BaseModel):
    """Dá»¯ liá»‡u client gá»­i lÃªn khi táº¡o lÃ´ nÃ´ng sáº£n má»›i (``POST /batches``).

    ``farm_id`` pháº£i trá» tá»›i má»™t vÃ¹ng trá»“ng **Ä‘Ã£ tá»“n táº¡i** â€” router sáº½ tráº£
    ``404 Not Found`` náº¿u khÃ´ng tÃ¬m tháº¥y.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "farm_id": 1,
                "product_name": "XoÃ i cÃ¡t Chu",
                "quantity": 120.5,
                "harvest_date": "2026-01-15",
            }
        },
    )

    farm_id: int = Field(
        ...,
        gt=0,
        description="ID vÃ¹ng trá»“ng (farms.id) - pháº£i tá»“n táº¡i.",
        examples=[1],
    )
    product_id: int | None = Field(
        default=None,
        gt=0,
        description="ID sản phẩm trong danh mục products.",
        examples=[1],
    )
    unit_id: int | None = Field(
        default=None,
        gt=0,
        description="ID đơn vị tính trong danh mục units.",
        examples=[1],
    )
    product_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="TÃªn sáº£n pháº©m cá»§a lÃ´.",
        examples=["XoÃ i cÃ¡t Chu"],
    )
    quantity: float = Field(
        ...,
        gt=0,
        description="Sá»‘ lÆ°á»£ng / khá»‘i lÆ°á»£ng cá»§a lÃ´, Ä‘Æ¡n vá»‹ kg. Pháº£i lá»›n hÆ¡n 0.",
        examples=[120.5],
    )
    harvest_date: date = Field(
        ...,
        description="NgÃ y thu hoáº¡ch, Ä‘á»‹nh dáº¡ng yyyy-MM-dd.",
        examples=["2026-01-15"],
    )
    @field_validator("harvest_date")
    @classmethod
    def validate_harvest_date(cls, value: date) -> date:
        if value > date.today():
            raise ValueError("Ngày thu hoạch không được lớn hơn ngày hiện tại.")
        return value
    parent_id: int | None = Field(
        default=None,
        gt=0,
        description="ID lÃ´ máº¹ trá»±c tiáº¿p (náº¿u Ä‘Ã¢y lÃ  lÃ´ con Ä‘Æ°á»£c tÃ¡ch ra tá»« lÃ´ khÃ¡c).",
        examples=[None],
    )


class BatchUpdate(BatchCreate):
    """Dá»¯ liá»‡u client gá»­i lÃªn khi **sá»­a** lÃ´ nÃ´ng sáº£n (``PUT /batches/{batch_id}``).

    Káº¿ thá»«a ``BatchCreate`` (dÃ¹ng láº¡i validate: ``farm_id`` > 0, ``quantity`` > 0,
    ``harvest_date`` Ä‘Ãºng Ä‘á»‹nh dáº¡ng ISO). Client gá»­i **Ä‘áº§y Ä‘á»§ 4 trÆ°á»ng**; router
    tráº£ ``404`` náº¿u lÃ´ hoáº·c ``farm_id`` má»›i khÃ´ng tá»“n táº¡i.

    LÆ°u Ã½: Ä‘á»•i ``farm_id`` = chuyá»ƒn lÃ´ sang vÃ¹ng trá»“ng khÃ¡c (váº«n pháº£i tá»“n táº¡i).

    VÃ­ dá»¥::

        {"farm_id": 1, "product_name": "XoÃ i cÃ¡t Chu", "quantity": 150,
         "harvest_date": "2026-01-16"}
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "farm_id": 1,
                "product_name": "XoÃ i cÃ¡t Chu",
                "quantity": 150,
                "harvest_date": "2026-01-16",
            }
        },
    )


class BatchResponse(BaseModel):
    """Dá»¯ liá»‡u API tráº£ vá» cho má»™t lÃ´ nÃ´ng sáº£n (kÃ¨m ``id``).

    ``harvest_date`` Ä‘Æ°á»£c serialize thÃ nh chuá»—i ``yyyy-MM-dd``.
    """

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"example": _BATCH_EXAMPLE},
    )

    batch_code: str | None = Field(
        default=None,
        description="M? l? thu ho?ch g?m 8 k? t? IN HOA, d? ??c.",
        examples=["A7K2M9QP"],
    )
    id: int = Field(..., description="MÃ£ Ä‘á»‹nh danh lÃ´ nÃ´ng sáº£n.", examples=[1])
    farm_id: int = Field(..., description="ID vÃ¹ng trá»“ng xuáº¥t xá»©.", examples=[1])
    product_name: str = Field(..., description="TÃªn sáº£n pháº©m cá»§a lÃ´.")
    quantity: float = Field(..., description="Sá»‘ lÆ°á»£ng / khá»‘i lÆ°á»£ng (kg).")
    harvest_date: date = Field(..., description="NgÃ y thu hoáº¡ch.")
    current_org_id: int | None = Field(default=None, description="ID tá»• chá»©c Ä‘ang náº¯m giá»¯ lÃ´ hÃ ng.")
    current_org_name: str | None = Field(default=None, description="TÃªn tá»• chá»©c Ä‘ang náº¯m giá»¯ lÃ´ hÃ ng.")
    parent_id: int | None = Field(default=None, description="ID lÃ´ máº¹ trá»±c tiáº¿p (náº¿u cÃ³).")
    remaining_quantity: float | None = Field(default=None, description="Khá»‘i lÆ°á»£ng cÃ²n láº¡i (kg).")
    status: str | None = Field(default="Äang lÆ°u kho", description="Tráº¡ng thÃ¡i lÃ´ nÃ´ng sáº£n.")
    unit: str | None = Field(default="kg", description="ÄÆ¡n vá»‹ khá»‘i lÆ°á»£ng.")


class BatchSummaryResponse(BaseModel):
    """TÃ³m táº¯t thÃ´ng tin má»™t lÃ´ nÃ´ng sáº£n (dÃ¹ng cho lÃ´ máº¹ / lÃ´ con trá»±c tiáº¿p)."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="MÃ£ Ä‘á»‹nh danh lÃ´.")
    product_name: str = Field(..., description="TÃªn sáº£n pháº©m.")
    quantity: float = Field(..., description="Khá»‘i lÆ°á»£ng ban Ä‘áº§u (kg).")
    remaining_quantity: float | None = Field(default=None, description="Khá»‘i lÆ°á»£ng cÃ²n láº¡i.")
    unit: str = Field(default="kg", description="ÄÆ¡n vá»‹ khá»‘i lÆ°á»£ng.")
    status: str = Field(default="Äang lÆ°u kho", description="Tráº¡ng thÃ¡i lÃ´.")
    current_org_name: str | None = Field(default=None, description="TÃªn tá»• chá»©c Ä‘ang náº¯m giá»¯.")


class BatchDetailResponse(BaseModel):
    """Dá»¯ liá»‡u chi tiáº¿t Ä‘áº§y Ä‘á»§ cá»§a má»™t lÃ´ nÃ´ng sáº£n phá»¥c vá»¥ S-25 Trang chi tiáº¿t lÃ´."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="MÃ£ Ä‘á»‹nh danh lÃ´ nÃ´ng sáº£n.")
    farm_id: int = Field(..., description="ID vÃ¹ng trá»“ng xuáº¥t xá»©.")
    farm_name: str | None = Field(default=None, description="TÃªn vÃ¹ng trá»“ng xuáº¥t xá»©.")
    farm_location: str | None = Field(default=None, description="Äá»‹a Ä‘iá»ƒm vÃ¹ng trá»“ng xuáº¥t xá»©.")
    product_name: str = Field(..., description="TÃªn sáº£n pháº©m.")
    initial_quantity: float = Field(..., description="Khá»‘i lÆ°á»£ng ban Ä‘áº§u (kg).")
    remaining_quantity: float = Field(..., description="Khá»‘i lÆ°á»£ng cÃ²n láº¡i (kg).")
    unit: str = Field(default="kg", description="ÄÆ¡n vá»‹ khá»‘i lÆ°á»£ng.")
    harvest_date: date = Field(..., description="NgÃ y thu hoáº¡ch.")
    status: str = Field(default="Äang lÆ°u kho", description="Tráº¡ng thÃ¡i lÃ´.")
    current_org_id: int | None = Field(default=None, description="ID tá»• chá»©c Ä‘ang náº¯m giá»¯.")
    current_org_name: str | None = Field(default=None, description="TÃªn tá»• chá»©c Ä‘ang náº¯m giá»¯.")
    parent_id: int | None = Field(default=None, description="ID lÃ´ máº¹ trá»±c tiáº¿p (náº¿u cÃ³).")
    parent: BatchSummaryResponse | None = Field(default=None, description="ThÃ´ng tin lÃ´ máº¹ trá»±c tiáº¿p.")
    children: list[BatchSummaryResponse] = Field(default_factory=list, description="Danh sÃ¡ch cÃ¡c lÃ´ con trá»±c tiáº¿p.")


class BatchTreeNodeResponse(BaseModel):
    """ThÃ´ng tin lÃ´ nÃºt (lÃ´ máº¹ hoáº·c lÃ´ con trá»±c tiáº¿p) cho T-58."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="MÃ£ Ä‘á»‹nh danh lÃ´.")
    product: str = Field(..., description="TÃªn sáº£n pháº©m cá»§a lÃ´.")
    product_name: str | None = Field(default=None, description="TÃªn sáº£n pháº©m cá»§a lÃ´.")
    quantity: float = Field(..., description="Khá»‘i lÆ°á»£ng ban Ä‘áº§u (kg).")
    remaining_quantity: float = Field(..., description="Khá»‘i lÆ°á»£ng cÃ²n láº¡i (kg).")
    unit: str = Field(default="kg", description="ÄÆ¡n vá»‹ khá»‘i lÆ°á»£ng.")
    status: str = Field(default="Äang lÆ°u kho", description="Tráº¡ng thÃ¡i lÃ´.")
    current_org_name: str | None = Field(default=None, description="TÃªn tá»• chá»©c Ä‘ang náº¯m giá»¯.")


class BatchTreeMainInfo(BaseModel):
    """ThÃ´ng tin chi tiáº¿t lÃ´ chÃ­nh cho T-58."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="MÃ£ Ä‘á»‹nh danh lÃ´.")
    product: str = Field(..., description="TÃªn sáº£n pháº©m cá»§a lÃ´.")
    product_name: str | None = Field(default=None, description="TÃªn sáº£n pháº©m cá»§a lÃ´.")
    quantity: float = Field(..., description="Khá»‘i lÆ°á»£ng ban Ä‘áº§u (kg).")
    remaining_quantity: float = Field(..., description="Khá»‘i lÆ°á»£ng cÃ²n láº¡i (kg).")
    unit: str = Field(default="kg", description="ÄÆ¡n vá»‹ khá»‘i lÆ°á»£ng.")
    location: str | None = Field(default=None, description="Vá»‹ trÃ­ / Ä‘á»‹a Ä‘iá»ƒm vÃ¹ng trá»“ng hoáº·c Ä‘Æ¡n vá»‹ náº¯m giá»¯.")
    status: str = Field(default="Äang lÆ°u kho", description="Tráº¡ng thÃ¡i lÃ´.")
    current_org_name: str | None = Field(default=None, description="TÃªn tá»• chá»©c Ä‘ang náº¯m giá»¯.")
    harvest_date: date = Field(..., description="NgÃ y thu hoáº¡ch.")
    farm_id: int | None = Field(default=None, description="ID vÃ¹ng trá»“ng xuáº¥t xá»©.")
    farm_name: str | None = Field(default=None, description="TÃªn vÃ¹ng trá»“ng xuáº¥t xá»©.")


class BatchTreeDetailResponse(BaseModel):
    """Cáº¥u trÃºc response chuáº©n cá»§a T-58: chi tiáº¿t lÃ´ kÃ¨m lÃ´ máº¹ vÃ  cÃ¡c lÃ´ con trá»±c tiáº¿p."""

    model_config = ConfigDict(from_attributes=True)

    batch: BatchTreeMainInfo = Field(..., description="ThÃ´ng tin chi tiáº¿t cá»§a lÃ´ Ä‘Æ°á»£c truy váº¥n.")
    parent: BatchTreeNodeResponse | None = Field(default=None, description="LÃ´ máº¹ trá»±c tiáº¿p (null náº¿u khÃ´ng cÃ³).")
    children: list[BatchTreeNodeResponse] = Field(
        default_factory=list,
        description="Danh sÃ¡ch cÃ¡c lÃ´ con trá»±c tiáº¿p (máº£ng rá»—ng [] náº¿u khÃ´ng cÃ³).",
    )


class BatchAncestorNodeResponse(BaseModel):
    """ThÃ´ng tin má»™t lÃ´ tá»• tiÃªn trong danh sÃ¡ch tá»• tiÃªn (T-59)."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="MÃ£ Ä‘á»‹nh danh lÃ´ tá»• tiÃªn.")
    product: str = Field(..., description="TÃªn sáº£n pháº©m.")
    product_name: str | None = Field(default=None, description="TÃªn sáº£n pháº©m.")
    quantity: float = Field(..., description="Khá»‘i lÆ°á»£ng ban Ä‘áº§u (kg).")
    remaining_quantity: float = Field(..., description="Khá»‘i lÆ°á»£ng cÃ²n láº¡i (kg).")
    unit: str = Field(default="kg", description="ÄÆ¡n vá»‹ khá»‘i lÆ°á»£ng.")
    status: str = Field(default="Äang lÆ°u kho", description="Tráº¡ng thÃ¡i lÃ´.")
    current_org_name: str | None = Field(default=None, description="TÃªn tá»• chá»©c Ä‘ang náº¯m giá»¯.")
    generation: int = Field(..., description="Cáº¥p tháº¿ há»‡ ngÆ°á»£c (1 = LÃ´ máº¹ trá»±c tiáº¿p, 2 = LÃ´ bÃ ...).")


class BatchAncestorsResponse(BaseModel):
    """Danh sÃ¡ch cÃ¡c lÃ´ tá»• tiÃªn cá»§a má»™t lÃ´ nÃ´ng sáº£n (T-59)."""

    model_config = ConfigDict(from_attributes=True)

    batch_id: int = Field(..., description="ID lÃ´ nÃ´ng sáº£n Ä‘Æ°á»£c truy váº¥n.")
    ancestors: list[BatchAncestorNodeResponse] = Field(
        default_factory=list,
        description="Danh sÃ¡ch cÃ¡c lÃ´ tá»• tiÃªn theo thá»© tá»± tá»« LÃ´ máº¹ trá»±c tiáº¿p tá»›i LÃ´ gá»‘c.",
    )


# ----------------------------------------------------------------- Chung ---
class DeleteResponse(BaseModel):
    """Káº¿t quáº£ má»™t láº§n xoÃ¡ thÃ nh cÃ´ng (``DELETE /farms/{id}``, ``DELETE /batches/{id}``).

    Cá»‘ tÃ¬nh tráº£ **200 OK kÃ¨m ná»™i dung** (thay vÃ¬ ``204 No Content``) Ä‘á»ƒ giao diá»‡n
    hiá»ƒn thá»‹ Ä‘Æ°á»£c thÃ´ng bÃ¡o "Ä‘Ã£ xoÃ¡ cÃ¡i gÃ¬" cho ngÆ°á»i dÃ¹ng.

    VÃ­ dá»¥::

        {"message": "ÄÃ£ xoÃ¡ vÃ¹ng trá»“ng #2 vÃ  2 lÃ´ nÃ´ng sáº£n thuá»™c vÃ¹ng Ä‘Ã³.",
         "deleted_id": 2, "deleted_batches": 2}
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "message": "ÄÃ£ xoÃ¡ vÃ¹ng trá»“ng #2 vÃ  2 lÃ´ nÃ´ng sáº£n thuá»™c vÃ¹ng Ä‘Ã³.",
                "deleted_id": 2,
                "deleted_batches": 2,
            }
        },
    )

    message: str = Field(
        ...,
        description="ThÃ´ng bÃ¡o káº¿t quáº£ xoÃ¡ (hiá»ƒn thá»‹ trá»±c tiáº¿p trÃªn giao diá»‡n).",
        examples=["ÄÃ£ xoÃ¡ vÃ¹ng trá»“ng #2 vÃ  2 lÃ´ nÃ´ng sáº£n thuá»™c vÃ¹ng Ä‘Ã³."],
    )
    deleted_id: int = Field(
        ...,
        description="ID cá»§a báº£n ghi vá»«a bá»‹ xoÃ¡.",
        examples=[2],
    )
    deleted_batches: int | None = Field(
        default=None,
        description=(
            "Sá»‘ lÃ´ nÃ´ng sáº£n bá»‹ xoÃ¡ kÃ¨m - chá»‰ cÃ³ giÃ¡ trá»‹ khi gá»i "
            "`DELETE /farms/{farm_id}` (xoÃ¡ vÃ¹ng trá»“ng sáº½ xoÃ¡ theo má»i lÃ´ thuá»™c "
            "vÃ¹ng Ä‘Ã³). `null` khi xoÃ¡ má»™t lÃ´ nÃ´ng sáº£n."
        ),
        examples=[2],
    )


# ------------------------------------------------------------ Audit log ---
# Sprint 7: lá»‹ch sá»­ thao tÃ¡c ("ai Ä‘Ã£ lÃ m gÃ¬"). Chá»‰ admin xem Ä‘Æ°á»£c
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
    """Má»™t dÃ²ng lá»‹ch sá»­ thao tÃ¡c trong response cá»§a ``GET /audit-logs``.

    Má»—i dÃ²ng cho biáº¿t **ai** (``user_id`` / ``username``) Ä‘Ã£ **lÃ m gÃ¬**
    (``action``) trÃªn **dá»¯ liá»‡u nÃ o** (``entity`` + ``entity_id``) vÃ  **lÃºc nÃ o**
    (``created_at``, UTC -> ``null`` `timezone`).

    VÃ­ dá»¥::

        {"id": 3, "user_id": 1, "username": "admin", "action": "update",
         "entity": "farm", "entity_id": 2, "created_at": "2026-01-20T03:15:42.123456"}
    """

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"example": _AUDIT_LOG_EXAMPLE},
    )

    id: int = Field(..., description="MÃ£ dÃ²ng log.", examples=[3])
    user_id: int = Field(
        ...,
        description="ID tÃ i khoáº£n Ä‘Ã£ thá»±c hiá»‡n thao tÃ¡c (khoÃ¡ ngoáº¡i tá»›i báº£ng `users`).",
        examples=[1],
    )
    username: str = Field(
        ...,
        description=(
            "TÃªn Ä‘Äƒng nháº­p cá»§a ngÆ°á»i thá»±c hiá»‡n - tiá»‡n hiá»ƒn thá»‹, suy ra tá»« "
            "`user_id` (khÃ´ng pháº£i cá»™t riÃªng trong báº£ng `audit_logs`)."
        ),
        examples=["admin", "farmer"],
    )
    action: str = Field(
        ...,
        description="HÃ nh Ä‘á»™ng Ä‘Ã£ xáº£y ra: `create` (táº¡o), `update` (sá»­a), `delete` (xoÃ¡).",
        examples=["create", "update", "delete"],
    )
    entity: str = Field(
        ...,
        description="Loáº¡i dá»¯ liá»‡u bá»‹ tÃ¡c Ä‘á»™ng: `farm` (vÃ¹ng trá»“ng) hoáº·c `batch` (lÃ´ nÃ´ng sáº£n).",
        examples=["farm", "batch"],
    )
    entity_id: int = Field(
        ...,
        description="ID báº£n ghi bá»‹ tÃ¡c Ä‘á»™ng (trong báº£ng `farms` hoáº·c `batches`).",
        examples=[2],
    )
    created_at: datetime = Field(
        ...,
        description="Thá»i Ä‘iá»ƒm ghi log (UTC, ISO 8601).",
        examples=["2026-01-20T03:15:42.123456"],
    )


# ------------------------------------------------------------- Handover ---
class HandoverCreate(BaseModel):
    """Dá»¯ liá»‡u gá»­i lÃªn khi táº¡o yÃªu cáº§u bÃ n giao lÃ´ nÃ´ng sáº£n (POST /batches/{id}/handover)."""

    to_org_id: int = Field(
        ...,
        gt=0,
        description="ID tá»• chá»©c tiáº¿p nháº­n lÃ´ hÃ ng (pháº£i khÃ¡c tá»• chá»©c hiá»‡n táº¡i).",
        examples=[2],
    )
    note: str | None = Field(
        default=None,
        max_length=500,
        description="Ghi chÃº kÃ¨m theo khi bÃ n giao (tÃ¹y chá»n).",
        examples=["BÃ n giao Ä‘á»£t 1 Ä‘á»ƒ sÆ¡ cháº¿ vÃ  Ä‘Ã³ng gÃ³i xuáº¥t kháº©u"],
    )


class HandoverRespond(BaseModel):
    """Dá»¯ liá»‡u pháº£n há»“i yÃªu cáº§u bÃ n giao (POST /handovers/{id}/respond)."""

    action: str = Field(
        ...,
        description="HÃ nh Ä‘á»™ng xá»­ lÃ½: 'ACCEPT' (nháº­n lÃ´) hoáº·c 'REJECT' (tá»« chá»‘i).",
        examples=["ACCEPT", "REJECT"],
    )
    reject_reason: str | None = Field(
        default=None,
        max_length=500,
        description="LÃ½ do tá»« chá»‘i (báº¯t buá»™c khi action='REJECT', tá»‘i thiá»ƒu 10 kÃ½ tá»±).",
        examples=["NÃ´ng sáº£n khÃ´ng Ä‘áº¡t Ä‘á»™ chÃ­n theo tiÃªu chuáº©n quy Ä‘á»‹nh"],
    )

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        upper = v.strip().upper()
        if upper not in ("ACCEPT", "REJECT"):
            raise ValueError("HÃ nh Ä‘á»™ng pháº£i lÃ  'ACCEPT' hoáº·c 'REJECT'.")
        return upper

    @model_validator(mode="after")
    def validate_reject_reason(self) -> "HandoverRespond":
        if self.action == "REJECT":
            if not self.reject_reason or len(self.reject_reason.strip()) < 10:
                raise ValueError("LÃ½ do tá»« chá»‘i lÃ  báº¯t buá»™c vÃ  pháº£i cÃ³ tá»‘i thiá»ƒu 10 kÃ½ tá»±.")
        return self


class HandoverOut(BaseModel):
    """Dá»¯ liá»‡u tráº£ vá» cho má»™t yÃªu cáº§u bÃ n giao."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="MÃ£ Ä‘á»‹nh danh bÃ n giao.")
    batch_id: int = Field(..., description="MÃ£ lÃ´ nÃ´ng sáº£n.")
    from_org_id: int = Field(..., description="ID tá»• chá»©c gá»­i.")
    to_org_id: int = Field(..., description="ID tá»• chá»©c nháº­n.")
    status: str = Field(..., description="Tráº¡ng thÃ¡i: PENDING, ACCEPTED, REJECTED.")
    reject_reason: str | None = Field(default=None, description="LÃ½ do tá»« chá»‘i (náº¿u cÃ³).")
    created_at: datetime = Field(..., description="Thá»i Ä‘iá»ƒm gá»­i yÃªu cáº§u.")
    updated_at: datetime = Field(..., description="Thá»i Ä‘iá»ƒm cáº­p nháº­t má»›i nháº¥t.")

    # ThÃ´ng tin má»Ÿ rá»™ng há»— trá»£ frontend
    batch_product_name: str | None = Field(default=None, description="TÃªn sáº£n pháº©m cá»§a lÃ´.")
    batch_quantity: float | None = Field(default=None, description="Khá»‘i lÆ°á»£ng cá»§a lÃ´ (kg).")
    from_org_name: str | None = Field(default=None, description="TÃªn tá»• chá»©c gá»­i.")
    to_org_name: str | None = Field(default=None, description="TÃªn tá»• chá»©c nháº­n.")


class BatchEventOut(BaseModel):
    """Dá»¯ liá»‡u tráº£ vá» cho má»™t sá»± kiá»‡n vÃ²ng Ä‘á»i lÃ´ nÃ´ng sáº£n."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="MÃ£ Ä‘á»‹nh danh sá»± kiá»‡n.")
    batch_id: int = Field(..., description="MÃ£ lÃ´ nÃ´ng sáº£n.")
    event_type: str = Field(..., description="Loáº¡i sá»± kiá»‡n (HANDOVER_PENDING, HANDOVER_ACCEPTED, HANDOVER_REJECTED,...).")
    user_id: int | None = Field(default=None, description="ID tÃ i khoáº£n thá»±c hiá»‡n.")
    from_org_id: int | None = Field(default=None, description="ID tá»• chá»©c gá»­i (náº¿u cÃ³).")
    to_org_id: int | None = Field(default=None, description="ID tá»• chá»©c nháº­n (náº¿u cÃ³).")
    notes: str | None = Field(default=None, description="Ghi chÃº chi tiáº¿t sá»± kiá»‡n.")
    created_at: datetime = Field(..., description="Thá»i Ä‘iá»ƒm ghi nháº­n sá»± kiá»‡n.")


class BatchEventCreate(BaseModel):
    """Dá»¯ liá»‡u client gá»­i lÃªn khi táº¡o sá»± kiá»‡n má»›i cho lÃ´ (``POST /batches/{batch_id}/events``)."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "event_type": "HARVEST",
                "event_data": "Thu hoáº¡ch xoÃ i cÃ¡t Chu Ä‘á»£t 1, nhiá»‡t Ä‘á»™ báº£o quáº£n 15Â°C.",
            }
        }
    )

    event_type: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Loáº¡i sá»± kiá»‡n (VD: BATCH_CREATED, HARVEST, PROCESSING, TEMP_CHECK, TRANSPORT, QUALITY_INSPECTION...).",
        examples=["HARVEST"],
    )
    event_data: str | None = Field(
        default=None,
        max_length=2000,
        description="Dá»¯ liá»‡u / thÃ´ng tin mÃ´ táº£ chi tiáº¿t cá»§a sá»± kiá»‡n.",
        examples=["Thu hoáº¡ch xoÃ i cÃ¡t Chu Ä‘á»£t 1, nhiá»‡t Ä‘á»™ báº£o quáº£n 15Â°C."],
    )


class BatchEventResponse(BaseModel):
    """Dá»¯ liá»‡u tráº£ vá» cho má»™t sá»± kiá»‡n lÃ´ nÃ´ng sáº£n (append-only log)."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="ID sá»± kiá»‡n.", examples=[1])
    batch_id: int = Field(..., description="ID lÃ´ nÃ´ng sáº£n.", examples=[1])
    event_type: str = Field(..., description="Loáº¡i sá»± kiá»‡n.", examples=["HARVEST"])
    event_data: str | None = Field(default=None, description="ThÃ´ng tin dá»¯ liá»‡u sá»± kiá»‡n.")
    user_id: int | None = Field(default=None, description="ID ngÆ°á»i thá»±c hiá»‡n.")
    from_org_id: int | None = Field(default=None, description="ID tá»• chá»©c tá»«.")
    to_org_id: int | None = Field(default=None, description="ID tá»• chá»©c Ä‘áº¿n.")
    notes: str | None = Field(default=None, description="Ghi chÃº.")
    created_at: datetime = Field(..., description="Thá»i Ä‘iá»ƒm ghi nháº­n sá»± kiá»‡n (UTC).")
    prev_hash: str = Field(..., description="Hash SHA-256 cá»§a sá»± kiá»‡n liá»n trÆ°á»›c cá»§a lÃ´.")
    record_hash: str = Field(..., description="Hash SHA-256 cá»§a báº£n ghi hiá»‡n táº¡i.")


class BatchIntegrityResponse(BaseModel):
    """Káº¿t quáº£ kiá»ƒm tra toÃ n váº¹n chuá»—i sá»± kiá»‡n cá»§a má»™t lÃ´ nÃ´ng sáº£n (Sprint S-12)."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "valid": True,
                "batch_id": 1,
                "total_events": 3,
                "message": "ToÃ n bá»™ 3 sá»± kiá»‡n cá»§a lÃ´ #1 Ä‘á»u há»£p lá»‡ vÃ  Ä‘áº£m báº£o tÃ­nh toÃ n váº¹n dá»¯ liá»‡u.",
            }
        }
    )

    valid: bool = Field(..., description="`true` náº¿u chuá»—i sá»± kiá»‡n toÃ n váº¹n, `false` náº¿u bá»‹ Ä‘á»©t máº¡ch/sai bÄƒm.")
    batch_id: int = Field(..., description="ID lÃ´ nÃ´ng sáº£n.")
    total_events: int | None = Field(default=None, description="Tá»•ng sá»‘ sá»± kiá»‡n (khi valid = true).")
    event_id: int | None = Field(default=None, description="ID cá»§a sá»± kiá»‡n bá»‹ lá»—i/Ä‘á»©t máº¡ch Ä‘áº§u tiÃªn (khi valid = false).")
    index: int | None = Field(default=None, description="Vá»‹ trÃ­ (index 0-based) cá»§a sá»± kiá»‡n bá»‹ lá»—i trong chuá»—i.")
    error_type: str | None = Field(
        default=None,
        description="Loáº¡i lá»—i phÃ¡t hiá»‡n (`PREV_HASH_MISMATCH`, `RECORD_HASH_MISMATCH`).",
    )
    expected_hash: str | None = Field(default=None, description="MÃ£ bÄƒm ká»³ vá»ng theo cÃ´ng thá»©c hash chain.")
    actual_hash: str | None = Field(default=None, description="MÃ£ bÄƒm thá»±c táº¿ ghi trong cÆ¡ sá»Ÿ dá»¯ liá»‡u / prev_hash.")
    message: str | None = Field(default=None, description="ThÃ´ng bÃ¡o chi tiáº¿t giáº£i thÃ­ch vá»‹ trÃ­ Ä‘á»©t máº¡ch.")



