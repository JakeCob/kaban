"""/api/v1/jobs — scheduled-work endpoints called by pg_cron (SPEC §11)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.clients.frankfurter import FrankfurterClient
from tracker.db.session import get_session
from tracker.deps import require_api_key
from tracker.money.fx import upsert_fx_rate

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
