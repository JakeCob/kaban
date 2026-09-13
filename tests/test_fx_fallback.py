"""FX fallback chain — integration test against Postgres.

Proves the three cases from SPEC §9:
  1. Today's rate found → stale=False, days_stale=0.
  2. Today missing, yesterday found → stale=True, days_stale=1.
  3. Nothing within max_stale_days → FxUnavailable.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from tests.conftest import requires_docker

pytestmark = [pytest.mark.asyncio, requires_docker]


async def _seed(session, as_of: date, base: str, quote: str, rate: str) -> None:
    from tracker.money.fx import upsert_fx_rate

    await upsert_fx_rate(session, as_of, base, quote, Decimal(rate))
    await session.commit()


async def test_todays_rate_wins(db_session) -> None:
    from tracker.money.fx import get_fx_rate

    anchor = date(2026, 9, 13)
    await _seed(db_session, anchor, "PHP", "USD", "0.0177")

    rate, status = await get_fx_rate(db_session, "USD", "PHP", today=anchor)

    # 1 PHP = 0.0177 USD  →  1 USD = 1/0.0177 ≈ 56.4972 PHP
    assert rate == Decimal("1") / Decimal("0.0177")
    assert status.stale is False
    assert status.days_stale == 0
    assert status.as_of_date == anchor


async def test_falls_back_to_yesterday(db_session) -> None:
    from tracker.money.fx import get_fx_rate

    anchor = date(2026, 9, 13)
    yesterday = anchor - timedelta(days=1)
    await _seed(db_session, yesterday, "PHP", "USD", "0.0180")

    rate, status = await get_fx_rate(db_session, "USD", "PHP", today=anchor)

    assert rate == Decimal("1") / Decimal("0.0180")
    assert status.stale is True
    assert status.days_stale == 1
    assert status.as_of_date == yesterday


async def test_raises_when_nothing_in_window(db_session) -> None:
    from tracker.money.fx import FxUnavailable, get_fx_rate

    with pytest.raises(FxUnavailable):
        await get_fx_rate(
            db_session, "USD", "PHP", today=date(2026, 9, 13), max_stale_days=14
        )


async def test_php_to_php_is_identity(db_session) -> None:
    from tracker.money.fx import get_fx_rate

    rate, status = await get_fx_rate(db_session, "PHP", "PHP")
    assert rate == Decimal("1")
    assert status.stale is False


async def test_direct_pair_preferred_over_inverse(db_session) -> None:
    """If both (USD, PHP) and (PHP, USD) exist for the same day, direct wins."""
    from tracker.money.fx import get_fx_rate

    anchor = date(2026, 9, 13)
    await _seed(db_session, anchor, "USD", "PHP", "56.5")
    await _seed(db_session, anchor, "PHP", "USD", "0.0180")

    rate, status = await get_fx_rate(db_session, "USD", "PHP", today=anchor)
    assert rate == Decimal("56.5")
    assert status.as_of_date == anchor
