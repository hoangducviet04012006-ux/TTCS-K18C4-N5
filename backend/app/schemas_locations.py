from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.schemas import validate_quantity


class LocationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=255)
    address: str = Field(min_length=1, max_length=500)

    @field_validator("code", "name", "address")
    @classmethod
    def trim(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Không được để trống.")
        return value


class LocationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=255)
    address: str | None = Field(default=None, min_length=1, max_length=500)
    is_active: bool | None = None

    @field_validator("name", "address")
    @classmethod
    def trim(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Không được để trống.")
        return value.strip() if value is not None else None


class LocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    organization_id: int
    code: str
    name: str
    address: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class TransferLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    location_id: int = Field(gt=0)


class StoreItem(TransferLocation):
    quantity: Decimal = Field(gt=0)

    @field_validator("quantity")
    @classmethod
    def valid_qty(cls, value):
        return validate_quantity(value)


class StoreAllocation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[StoreItem] = Field(min_length=2, max_length=100)
