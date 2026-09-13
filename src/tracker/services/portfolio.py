"""Portfolio aggregation — cost basis and current market value in PHP, grouped by category.

Cost basis is already stored in PHP on every inventory row (cost_php_snapshot, frozen
at purchase per SPEC §9). Market value is computed live: latest snapshot × today's FX
× quantity, per row. If FX for a currency is stale, the top-level fx_status flags it
and the affected currencies show up in warnings.

Metagross-sourced inventory has no category on our side (Metagross owns the taxonomy),
so those rows collect under the pseudo-slug `tcg_metagross`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.enums import ProductSource
from tracker.db.models import Category, Inventory, Product
from tracker.money.conversion import PHP, quantize_php, to_php
from tracker.money.fx import FxStatus, FxUnavailable, get_fx_rate
from tracker.schemas.portfolio import (
    CategoryTotal,
    FxStatusPayload,
    PortfolioResponse,
)
from tracker.schemas.price import PriceQueryBody
from tracker.services.prices import get_latest_snapshot

METAGROSS_BUCKET = "tcg_metagross"


@dataclass
class _Bucket:
    slug: str
    item_count: int = 0
    cost_php: Decimal = Decimal("0")
    market_php: Decimal = Decimal("0")
    warnings: list[str] = field(default_factory=list)


async def _resolve_category_slug(
    session: AsyncSession, inv: Inventory, slug_cache: dict[int, str]
) -> str:
    if inv.product_source == ProductSource.METAGROSS:
        return METAGROSS_BUCKET
    assert inv.local_product_id is not None
    prod = await session.get(Product, inv.local_product_id)
    if prod is None:
        return "unknown"
    if prod.category_id in slug_cache:
        return slug_cache[prod.category_id]
    cat = await session.get(Category, prod.category_id)
    slug = cat.slug if cat else "unknown"
    slug_cache[prod.category_id] = slug
    return slug


async def _cached_fx(
    session: AsyncSession,
    cache: dict[str, tuple[Decimal, FxStatus]],
    currency: str,
    *,
    today: date | None = None,
) -> tuple[Decimal, FxStatus] | None:
    if currency in cache:
        return cache[currency]
    try:
        rate, status = await get_fx_rate(session, currency, PHP, today=today)
    except FxUnavailable:
        return None
    cache[currency] = (rate, status)
    return rate, status


async def compute_portfolio(
    session: AsyncSession, *, today: date | None = None
) -> PortfolioResponse:
    inventory_rows = (await session.execute(select(Inventory))).scalars().all()

    buckets: dict[str, _Bucket] = {}
    fx_cache: dict[str, tuple[Decimal, FxStatus]] = {}
    slug_cache: dict[int, str] = {}
    warnings: list[str] = []

    for inv in inventory_rows:
        slug = await _resolve_category_slug(session, inv, slug_cache)
        bucket = buckets.setdefault(slug, _Bucket(slug=slug))
        bucket.item_count += 1
        bucket.cost_php += inv.cost_php_snapshot * inv.quantity

        query = PriceQueryBody(
            product_source=inv.product_source,
            external_product_id=inv.external_product_id,
            local_product_id=inv.local_product_id,
            condition=inv.condition,
            grader=(inv.grade or {}).get("grader"),
            grade_value=(inv.grade or {}).get("grade"),
        )
        snap = await get_latest_snapshot(session, query)
        if snap is None:
            warnings.append(f"no price snapshot for inventory {inv.id}")
            continue

        fx = await _cached_fx(session, fx_cache, snap.price_currency, today=today)
        if fx is None:
            warnings.append(
                f"no FX rate for {snap.price_currency}->PHP within 14 days; "
                f"skipped market value for inventory {inv.id}"
            )
            continue
        rate, _ = fx
        market_native = snap.price_amount * inv.quantity
        bucket.market_php += to_php(market_native, snap.price_currency, rate)

    per_category = [
        CategoryTotal(
            category_slug=b.slug,
            item_count=b.item_count,
            cost_php=quantize_php(b.cost_php),
            market_php=quantize_php(b.market_php),
            unrealized_pnl_php=quantize_php(b.market_php - b.cost_php),
        )
        for b in sorted(buckets.values(), key=lambda b: b.slug)
    ]

    grand_cost = sum((b.cost_php for b in buckets.values()), Decimal("0"))
    grand_market = sum((b.market_php for b in buckets.values()), Decimal("0"))

    # Aggregate FX status across every currency we touched — the rate with the
    # most days_stale wins so callers see the worst freshness in one glance.
    if fx_cache:
        worst = max((s for _, s in fx_cache.values()), key=lambda s: s.days_stale)
    else:
        worst = FxStatus(as_of_date=today or date.today(), stale=False, days_stale=0)

    return PortfolioResponse(
        total_cost_php=quantize_php(grand_cost),
        total_market_php=quantize_php(grand_market),
        unrealized_pnl_php=quantize_php(grand_market - grand_cost),
        by_category=per_category,
        fx_status=FxStatusPayload(**worst.model_dump()),
        warnings=warnings,
    )
