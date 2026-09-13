"""Price snapshots — writes, latest lookup, history query, materialized-view refresh.

`/prices/latest` reads directly from `price_snapshots` with an ORDER BY … DESC
LIMIT 1, not from the materialized view. The MV is for the portfolio-wide sweep
(Phase 3+), where the cost of REFRESH MATERIALIZED VIEW pays for itself; a single
latest-price lookup does not need it.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import cast

from sqlalchemy import and_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import PriceSnapshot, PriceSource
from tracker.schemas.price import (
    PriceHistoryPoint,
    PriceHistoryResponse,
    PriceManualCreate,
    PriceQueryBody,
)
from tracker.sources.base import PriceQuery, PriceResult


async def _get_source_id(session: AsyncSession, slug: str) -> int:
    stmt = select(PriceSource.id).where(PriceSource.slug == slug)
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise LookupError(f"No price_source row with slug={slug!r}")
    return cast(int, row)


def _query_key_filters(query: PriceQuery | PriceQueryBody) -> list:
    filters = [PriceSnapshot.product_source == query.product_source]
    if query.external_product_id is not None:
        filters.append(PriceSnapshot.external_product_id == query.external_product_id)
    else:
        filters.append(PriceSnapshot.external_product_id.is_(None))
    if query.local_product_id is not None:
        filters.append(PriceSnapshot.local_product_id == query.local_product_id)
    else:
        filters.append(PriceSnapshot.local_product_id.is_(None))
    if query.condition is not None:
        filters.append(PriceSnapshot.condition == query.condition)
    else:
        filters.append(PriceSnapshot.condition.is_(None))
    if query.grader is not None:
        filters.append(PriceSnapshot.grader == query.grader)
    else:
        filters.append(PriceSnapshot.grader.is_(None))
    if query.grade_value is not None:
        filters.append(PriceSnapshot.grade_value == query.grade_value)
    else:
        filters.append(PriceSnapshot.grade_value.is_(None))
    return filters


async def insert_snapshot(
    session: AsyncSession,
    query: PriceQuery | PriceQueryBody,
    result: PriceResult,
    source_slug: str,
) -> PriceSnapshot:
    source_id = await _get_source_id(session, source_slug)
    snap = PriceSnapshot(
        product_source=query.product_source,
        external_product_id=query.external_product_id,
        local_product_id=query.local_product_id,
        source_id=source_id,
        price_amount=result.amount,
        price_currency=result.currency,
        condition=result.condition or query.condition,
        grader=result.grader or query.grader,
        grade_value=result.grade_value or query.grade_value,
        raw=result.raw or None,
    )
    session.add(snap)
    await session.flush()
    await session.refresh(snap)
    return snap


async def insert_manual_snapshot(
    session: AsyncSession, payload: PriceManualCreate
) -> PriceSnapshot:
    result = PriceResult(
        amount=payload.price_amount,
        currency=payload.price_currency,
        condition=payload.condition,
        grader=payload.grader,
        grade_value=payload.grade_value,
        raw=payload.raw or {},
        source_slug="manual",
    )
    return await insert_snapshot(session, payload, result, "manual")


async def get_latest_snapshot(
    session: AsyncSession, query: PriceQueryBody
) -> PriceSnapshot | None:
    stmt = (
        select(PriceSnapshot)
        .where(and_(*_query_key_filters(query)))
        .order_by(PriceSnapshot.captured_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_price_history(
    session: AsyncSession,
    query: PriceQueryBody,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
) -> PriceHistoryResponse:
    if to_date is None:
        to_date = date.today()
    if from_date is None:
        from_date = to_date - timedelta(days=90)

    stmt = (
        select(PriceSnapshot)
        .where(
            and_(
                *_query_key_filters(query),
                PriceSnapshot.captured_at >= datetime.combine(from_date, datetime.min.time()),
                PriceSnapshot.captured_at
                <= datetime.combine(to_date + timedelta(days=1), datetime.min.time()),
            )
        )
        .order_by(PriceSnapshot.captured_at.asc())
    )
    result = await session.execute(stmt)
    rows = list(result.scalars())
    series = [
        PriceHistoryPoint(
            date=r.captured_at.date(),
            price_amount=r.price_amount,
            price_currency=r.price_currency,
            source_id=r.source_id,
        )
        for r in rows
    ]
    return PriceHistoryResponse(
        product_source=query.product_source,
        external_product_id=query.external_product_id,
        local_product_id=query.local_product_id,
        condition=query.condition,
        grader=query.grader,
        grade_value=query.grade_value,
        series=series,
    )


async def refresh_latest_prices_view(session: AsyncSession) -> None:
    """REFRESH MATERIALIZED VIEW CONCURRENTLY. Safe to call any time; cheap enough.

    CONCURRENTLY requires a unique index on the MV — we created one in the initial
    migration (idx_latest_prices_unique) so this is safe under normal read traffic.
    """
    await session.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY latest_prices"))
