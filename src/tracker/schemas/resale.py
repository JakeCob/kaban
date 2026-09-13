"""Resale request/response schemas."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from tracker.schemas.portfolio import FxStatusPayload


class ResalePreviewRequest(BaseModel):
    """POST /resale/preview.

    If gross_amount is omitted, the calculator uses the latest price snapshot for
    the inventory item (matched by product ref + condition + grader/grade_value).
    """

    inventory_id: UUID
    platform: str
    gross_amount: Decimal | None = None
    gross_currency: str | None = Field(default=None, min_length=3, max_length=3)


class ResalePreviewResponse(BaseModel):
    inventory_id: UUID
    platform: str
    gross_amount: Decimal
    gross_currency: str
    fees: dict[str, Any]
    net_native: Decimal          # after platform + payment + native listing_flat
    net_php: Decimal             # net_native converted + PHP shipping subtracted
    fx_status: FxStatusPayload
    based_on_snapshot_id: int | None = None
    warnings: list[str] = []


class ResaleScenarioCreate(ResalePreviewRequest):
    """POST /resale/scenarios — persist a preview so we can flag it stale later."""


class ResaleScenarioRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    inventory_id: UUID
    price_snapshot_id: int | None
    platform: str
    gross_amount: Decimal
    gross_currency: str
    fees: dict[str, Any]
    net_php: Decimal
    calculated_at: datetime
    # Live flag — true if a newer snapshot has landed for the same product key.
    stale: bool = False
