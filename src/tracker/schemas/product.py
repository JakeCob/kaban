"""Product request/response schemas (local products only — Metagross products live remote)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProductBase(BaseModel):
    category_id: int
    name: str = Field(min_length=1, max_length=500)
    brand: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    srp_amount: Decimal | None = None
    srp_currency: str | None = Field(default=None, min_length=3, max_length=3)
    image_url: str | None = None


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    category_id: int | None = None
    name: str | None = Field(default=None, min_length=1, max_length=500)
    brand: str | None = None
    attributes: dict[str, Any] | None = None
    srp_amount: Decimal | None = None
    srp_currency: str | None = Field(default=None, min_length=3, max_length=3)
    image_url: str | None = None


class ProductRead(ProductBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime
