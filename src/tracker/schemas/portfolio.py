"""Portfolio response schema — grand totals in PHP + per-category breakdown."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class FxStatusPayload(BaseModel):
    as_of_date: date
    stale: bool
    days_stale: int


class CategoryTotal(BaseModel):
    """Aggregated numbers for one category. `category_slug` is 'tcg_metagross' for
    inventory that references the Metagross catalog (its category is unknown to us
    since Metagross owns the taxonomy)."""

    category_slug: str
    item_count: int
    cost_php: Decimal
    market_php: Decimal
    unrealized_pnl_php: Decimal


class PortfolioResponse(BaseModel):
    total_cost_php: Decimal
    total_market_php: Decimal
    unrealized_pnl_php: Decimal
    by_category: list[CategoryTotal]
    fx_status: FxStatusPayload
    # Non-fatal warnings — inventory rows without a price snapshot, missing FX
    # pairs that fell back to a stale rate, etc.
    warnings: list[str] = []
