"""Pre-order request/response schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tracker.db.enums import ConditionType, PreOrderStatus, ProductSource


class PreOrderBase(BaseModel):
    product_source: ProductSource
    external_product_id: str | None = None
    local_product_id: UUID | None = None
    release_code: str | None = None
    store: str
    deposit_amount: Decimal | None = None
    deposit_currency: str | None = Field(default=None, min_length=3, max_length=3)
    expected_units: int | None = None
    actual_units: int | None = None
    release_date: date | None = None
    status: PreOrderStatus = PreOrderStatus.PENDING
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


class PreOrderCreate(PreOrderBase):
    pass


class PreOrderUpdate(BaseModel):
    release_code: str | None = None
    store: str | None = None
    deposit_amount: Decimal | None = None
    deposit_currency: str | None = Field(default=None, min_length=3, max_length=3)
    expected_units: int | None = None
    actual_units: int | None = None
    release_date: date | None = None
    status: PreOrderStatus | None = None
    notes: str | None = None


class PreOrderRead(PreOrderBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime


class PreOrderResolveRequest(BaseModel):
    """Body for POST /pre_orders/{id}/resolve.

    Sets `actual_units`, updates status, and (if `receive_now`) creates that many
    inventory rows in a single transaction using the cost fields supplied here.
    """

    actual_units: int = Field(ge=0)
    receive_now: bool = True

    # Only required when receive_now=True.
    cost_per_unit: Decimal | None = None
    cost_currency: str | None = Field(default=None, min_length=3, max_length=3)
    cost_fx_to_php: Decimal | None = None
    purchase_date: date | None = None
    condition: ConditionType = ConditionType.SEALED
    storage_location: str | None = None
    notes: str | None = None


class PreOrderResolveResponse(BaseModel):
    pre_order: PreOrderRead
    inventory_ids: list[UUID]
