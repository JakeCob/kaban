"""FX rate lookup with the fallback chain from docs/SPEC.md §9.

Semantics of a stored rate:
  fx_rates(base=B, quote=Q, rate=r) means "1 B = r Q".

The refresh_fx job stores rows with base='PHP' (matching the SPEC), so a
row like (PHP, USD, 0.0177) means "1 PHP = 0.0177 USD". To convert USD → PHP
we invert: `amount_usd / 0.0177`. This module hides that arithmetic behind
`get_fx_rate(from_currency, to_currency)` which returns the multiplier such
that `amount_in_from * rate = amount_in_to`.

The lookup order per query:
  1. Try today's row for either the direct pair or its inverse.
  2. Walk back one day at a time, up to `max_stale_days` (default 14).
  3. Raise FxUnavailable if nothing lands inside the window.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import FxRate

DEFAULT_MAX_STALE_DAYS = 14
_PHP = "PHP"


class FxUnavailable(Exception):  # noqa: N818 — "Unavailable" reads better than "Error" here
    """Raised when no FX rate is available within the fallback window."""


class FxStatus(BaseModel):
    """Freshness of an FX rate as served to a caller."""

    as_of_date: date
    stale: bool
    days_stale: int


async def _rate_on(
    session: AsyncSession, on: date, base: str, quote: str
) -> Decimal | None:
    stmt = select(FxRate.rate).where(
        FxRate.as_of_date == on, FxRate.base == base, FxRate.quote == quote
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_fx_rate(
    session: AsyncSession,
    from_currency: str,
    to_currency: str,
    *,
    today: date | None = None,
    max_stale_days: int = DEFAULT_MAX_STALE_DAYS,
) -> tuple[Decimal, FxStatus]:
    """Return (multiplier, status) such that ``amount_in_from * multiplier == amount_in_to``.

    Raises FxUnavailable if no rate is found within the fallback window.
    """
    if from_currency == to_currency:
        anchor = today or date.today()
        return Decimal("1"), FxStatus(as_of_date=anchor, stale=False, days_stale=0)

    anchor = today or date.today()
    for days_back in range(max_stale_days + 1):
        on = anchor - timedelta(days=days_back)

        direct = await _rate_on(session, on, from_currency, to_currency)
        if direct is not None:
            return direct, FxStatus(
                as_of_date=on, stale=days_back > 0, days_stale=days_back
            )

        inverse = await _rate_on(session, on, to_currency, from_currency)
        if inverse is not None and inverse != 0:
            return Decimal("1") / inverse, FxStatus(
                as_of_date=on, stale=days_back > 0, days_stale=days_back
            )

    raise FxUnavailable(
        f"No FX rate for {from_currency}->{to_currency} within {max_stale_days} days"
    )


async def upsert_fx_rate(
    session: AsyncSession,
    as_of: date,
    base: str,
    quote: str,
    rate: Decimal,
    source: str = "frankfurter",
) -> None:
    """Idempotent write for the daily refresh job."""
    from sqlalchemy.dialects.postgresql import insert

    stmt = insert(FxRate).values(
        as_of_date=as_of, base=base, quote=quote, rate=rate, source=source
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[FxRate.as_of_date, FxRate.base, FxRate.quote],
        set_={"rate": rate, "source": source},
    )
    await session.execute(stmt)


def php_currency() -> str:
    return _PHP
