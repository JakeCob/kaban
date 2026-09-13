"""/api/v1/jobs — scheduled-work endpoints called by pg_cron (SPEC §11)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.clients.frankfurter import FrankfurterClient
from tracker.db.session import get_session
from tracker.deps import require_api_key
from tracker.money.fx import upsert_fx_rate
from tracker.services.refresh import (
    RefreshSummary,
    refresh_prices_all,
    refresh_prices_for_source,
)
from tracker.sources.registry import SourceRegistry, get_source_registry

router = APIRouter(prefix="/jobs", tags=["jobs"])

QUOTES = ("USD", "JPY", "TWD", "EUR", "GBP")


@router.post(
    "/refresh-fx",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_api_key)],
)
async def refresh_fx(session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    """Fetch today's rates from Frankfurter and upsert them.

    Base is PHP to match SPEC §9 exactly. Stored rate for (base=PHP, quote=USD, r=X)
    means "1 PHP = X USD"; conversion code handles the inversion.
    """
    base = "PHP"
    async with FrankfurterClient() as client:
        latest = await client.latest_rates(base, list(QUOTES))

    today = date.today()
    for quote, rate in latest.rates.items():
        await upsert_fx_rate(session, today, base, quote, Decimal(str(rate)))
    await session.commit()

    return {
        "as_of_date": today.isoformat(),
        "base": base,
        "rates": {q: str(r) for q, r in latest.rates.items()},
    }


@router.post(
    "/refresh-prices/{source_slug}",
    response_model=RefreshSummary,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_api_key)],
)
async def refresh_prices_one(
    source_slug: str,
    session: AsyncSession = Depends(get_session),
    registry: SourceRegistry = Depends(get_source_registry),
) -> RefreshSummary:
    """Per-source refresh — this is the endpoint pg_cron hits (SPEC §11)."""
    try:
        summary = await refresh_prices_for_source(session, registry, source_slug)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "unknown_source", "message": str(exc)}},
        ) from exc
    await session.commit()
    return summary


@router.post(
    "/refresh-prices",
    response_model=list[RefreshSummary],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_api_key)],
)
async def refresh_prices_fanout(
    session: AsyncSession = Depends(get_session),
    registry: SourceRegistry = Depends(get_source_registry),
) -> list[RefreshSummary]:
    """Convenience fan-out over every source. Not wired to cron — pg_cron uses the
    per-source endpoint (SPEC §11) so one slow source doesn't block the others."""
    summaries = await refresh_prices_all(session, registry)
    await session.commit()
    return summaries
