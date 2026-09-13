"""Refresh orchestration — the glue between the source registry and the DB writes.

Two entry points:
  - `refresh_price_for_query` — single-item refresh from POST /prices/refresh.
  - `refresh_prices_for_source` — bulk refresh for one source (per-source cron
    endpoint from SPEC §11); walks inventory, filters by can_handle, calls
    fetch_latest_batch on the winners, inserts snapshots. Per-item failures are
    caught and logged as warnings so one bad item never poisons the whole batch,
    and one failing source never affects the others (they have their own cron
    entries and their own request lifecycles).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.enums import ProductSource
from tracker.db.models import Category, Inventory, PreOrder, PriceSnapshot, Product
from tracker.schemas.price import PriceQueryBody
from tracker.services.prices import insert_snapshot, refresh_latest_prices_view
from tracker.sources.base import PriceQuery
from tracker.sources.registry import SourceRegistry

log = logging.getLogger(__name__)


class RefreshSummary(BaseModel):
    """Response shape for POST /jobs/refresh-prices/{slug}."""

    source: str
    candidates: int
    snapshots_written: int
    warnings: list[str] = []


@dataclass
class _WalkedItem:
    query: PriceQuery
    body: PriceQueryBody          # for insert_snapshot (carries the same key)
    product: dict[str, Any] | None
    label: str                    # for warning messages


# --- single-item (used by POST /prices/refresh) --------------------------

async def refresh_price_for_query(
    session: AsyncSession,
    registry: SourceRegistry,
    body: PriceQueryBody,
) -> PriceSnapshot | None:
    """Route a query to its source, fetch, insert. Returns the snapshot row or
    None when the picked source returned no price."""
    query = PriceQuery(
        product_source=body.product_source,
        external_product_id=body.external_product_id,
        local_product_id=body.local_product_id,
        condition=body.condition,
        grader=body.grader,
        grade_value=body.grade_value,
    )
    source = registry.pick(query)
    if source is None:
        return None
    result = await source.fetch_latest(query)
    if result is None:
        return None
    return await insert_snapshot(session, body, result, source.slug)


# --- bulk per-source (used by cron) --------------------------------------

async def _walk_inventory_and_preorders(
    session: AsyncSession,
) -> list[_WalkedItem]:
    """Build (query, product_dict) pairs for every priceable row.

    Products are joined once and cached so the Apify sources can inspect
    category slug and attributes without additional round-trips.
    """
    items: list[_WalkedItem] = []

    # Local products with category slugs for can_handle.
    prod_rows = await session.execute(
        select(Product, Category.slug).outerjoin(Category, Category.id == Product.category_id)
    )
    products_by_id = {
        prod.id: {
            "id": str(prod.id),
            "category_slug": cat_slug or "unknown",
            "attributes": prod.attributes or {},
        }
        for prod, cat_slug in prod_rows
    }

    inv_rows = (await session.execute(select(Inventory))).scalars().all()
    for inv in inv_rows:
        product = (
            products_by_id.get(inv.local_product_id)
            if inv.product_source == ProductSource.LOCAL
            else None
        )
        hints = (product or {}).get("attributes") or {}
        query = PriceQuery(
            product_source=inv.product_source,
            external_product_id=inv.external_product_id,
            local_product_id=inv.local_product_id,
            condition=inv.condition,
            grader=(inv.grade or {}).get("grader"),
            grade_value=(inv.grade or {}).get("grade"),
            hints=hints,
        )
        body = PriceQueryBody(
            product_source=inv.product_source,
            external_product_id=inv.external_product_id,
            local_product_id=inv.local_product_id,
            condition=inv.condition,
            grader=(inv.grade or {}).get("grader"),
            grade_value=(inv.grade or {}).get("grade"),
        )
        items.append(
            _WalkedItem(
                query=query, body=body, product=product, label=f"inventory:{inv.id}"
            )
        )

    # Open pre-orders that reference Metagross-side products get priced too.
    po_rows = (
        await session.execute(select(PreOrder).where(PreOrder.status.in_(["pending", "paid"])))
    ).scalars().all()
    for po in po_rows:
        product = (
            products_by_id.get(po.local_product_id)
            if po.product_source == ProductSource.LOCAL
            else None
        )
        hints = (product or {}).get("attributes") or {}
        query = PriceQuery(
            product_source=po.product_source,
            external_product_id=po.external_product_id,
            local_product_id=po.local_product_id,
            hints=hints,
        )
        body = PriceQueryBody(
            product_source=po.product_source,
            external_product_id=po.external_product_id,
            local_product_id=po.local_product_id,
        )
        items.append(
            _WalkedItem(query=query, body=body, product=product, label=f"pre_order:{po.id}")
        )

    return items


@dataclass
class _Bucket:
    snapshots_written: int = 0
    warnings: list[str] = field(default_factory=list)


async def refresh_prices_for_source(
    session: AsyncSession,
    registry: SourceRegistry,
    source_slug: str,
) -> RefreshSummary:
    """Refresh every priceable row that `source_slug` claims via can_handle."""
    if source_slug not in registry:
        raise LookupError(f"Unknown source slug: {source_slug!r}")

    source = registry.get(source_slug)
    all_items = await _walk_inventory_and_preorders(session)
    handleable = [it for it in all_items if source.can_handle(it.query, it.product)]

    bucket = _Bucket()
    if not handleable:
        return RefreshSummary(
            source=source_slug, candidates=0, snapshots_written=0, warnings=[]
        )

    # Fan out to the source. Whole batch is wrapped so a total blow-up shows
    # up as one warning, not an unhandled 500.
    try:
        results = await source.fetch_latest_batch([it.query for it in handleable])
    except Exception as exc:  # pragma: no cover — hard fault path
        log.exception("source %s batch failed", source_slug)
        return RefreshSummary(
            source=source_slug,
            candidates=len(handleable),
            snapshots_written=0,
            warnings=[f"source batch call failed: {exc}"],
        )

    for item, result in zip(handleable, results, strict=True):
        if result is None:
            bucket.warnings.append(f"{item.label}: no price returned")
            continue
        try:
            await insert_snapshot(session, item.body, result, source.slug)
            bucket.snapshots_written += 1
        except Exception as exc:  # noqa: BLE001 — per-item isolation is the point
            log.warning("insert_snapshot failed for %s: %s", item.label, exc)
            bucket.warnings.append(f"{item.label}: insert failed ({exc})")

    if bucket.snapshots_written > 0:
        try:
            await refresh_latest_prices_view(session)
        except Exception as exc:  # noqa: BLE001
            log.warning("MV refresh failed: %s", exc)
            bucket.warnings.append(f"MV refresh failed: {exc}")

    return RefreshSummary(
        source=source_slug,
        candidates=len(handleable),
        snapshots_written=bucket.snapshots_written,
        warnings=bucket.warnings,
    )


async def refresh_prices_all(
    session: AsyncSession, registry: SourceRegistry
) -> list[RefreshSummary]:
    """Fan out to every source in the registry (convenience — cron uses per-source)."""
    summaries: list[RefreshSummary] = []
    for source in registry.all():
        try:
            summaries.append(await refresh_prices_for_source(session, registry, source.slug))
        except Exception as exc:  # noqa: BLE001 — one source's blow-up must not kill the rest
            log.exception("source %s crashed", source.slug)
            summaries.append(
                RefreshSummary(
                    source=source.slug,
                    candidates=0,
                    snapshots_written=0,
                    warnings=[f"source crashed: {exc}"],
                )
            )
    return summaries
