"""Refresh orchestration — the glue between the source registry and the DB writes.

Kept separate from services/prices.py because Phase 4's per-source cron endpoints
will land here too. Today it just knows how to refresh a single query.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import PriceSnapshot
from tracker.schemas.price import PriceQueryBody
from tracker.services.prices import insert_snapshot
from tracker.sources.base import PriceQuery
from tracker.sources.registry import SourceRegistry


async def refresh_price_for_query(
    session: AsyncSession,
    registry: SourceRegistry,
    body: PriceQueryBody,
) -> PriceSnapshot | None:
    """Route a query to its source, fetch, insert. Returns the snapshot row or None
    when the picked source returned no price."""
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
