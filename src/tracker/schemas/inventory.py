"""Inventory request/response schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tracker.db.enums import ConditionType, ProductSource


class InventoryBase(BaseModel):
    product_source: ProductSource
    external_product_id: str | None = None
    local_product_id: UUID | None = None
    quantity: int = Field(default=1, ge=0)
    cost_amount: Decimal
    cost_currency: str = Field(min_length=3, max_length=3)
    cost_fx_to_php: Decimal
    purchase_date: date
    source: str | None = None
    storage_location: str | None = None
    condition: ConditionType = ConditionType.SEALED
    grade: dict[str, Any] | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _exclusive_product_ref(self) -> Self:
        if self.product_source == ProductSource.METAGROSS:
            if not self.external_product_id or self.local_product_id is not None:
                raise ValueError(
                    "product_source=metagross requires external_product_id "
                    "and forbids local_product_id"
                )
        else:
            if not self.local_product_id or self.external_product_id is not None:
                raise ValueError(
                    "product_source=local requires local_product_id "
                    "and forbids external_product_id"
                )
        return self


class InventoryCreate(InventoryBase):
    pass


class InventoryUpdate(BaseModel):
    quantity: int | None = Field(default=None, ge=0)
    cost_amount: Decimal | None = None
    cost_currency: str | None = Field(default=None, min_length=3, max_length=3)
    cost_fx_to_php: Decimal | None = None
    purchase_date: date | None = None
    source: str | None = None
    storage_location: str | None = None
    condition: ConditionType | None = None
    grade: dict[str, Any] | None = None
    notes: str | None = None


class InventoryRead(InventoryBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    cost_php_snapshot: Decimal
    created_at: datetime
    updated_at: datetime
