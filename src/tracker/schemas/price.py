"""Price snapshot request/response schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tracker.db.enums import ConditionType, ProductSource


class PriceQueryBody(BaseModel):
    """Body for POST /prices/refresh and used as a shared piece for /prices/manual."""

    product_source: ProductSource
    external_product_id: str | None = None
    local_product_id: UUID | None = None
    condition: ConditionType | None = None
    grader: str | None = None
    grade_value: str | None = None

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


class PriceManualCreate(PriceQueryBody):
    """Body for POST /prices/manual — everything a snapshot needs, hand-entered."""

    price_amount: Decimal = Field(gt=0)
    price_currency: str = Field(min_length=3, max_length=3)
    raw: dict[str, Any] | None = None


class PriceSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_source: ProductSource
    external_product_id: str | None = None
    local_product_id: UUID | None = None
    source_id: int
    price_amount: Decimal
    price_currency: str
    condition: ConditionType | None = None
    grader: str | None = None
    grade_value: str | None = None
    raw: dict[str, Any] | None = None
    captured_at: datetime


class PriceHistoryPoint(BaseModel):
    date: date
    price_amount: Decimal
    price_currency: str
    source_id: int


class PriceHistoryResponse(BaseModel):
    product_source: ProductSource
    external_product_id: str | None = None
    local_product_id: UUID | None = None
    condition: ConditionType | None = None
    grader: str | None = None
    grade_value: str | None = None
    series: list[PriceHistoryPoint]
