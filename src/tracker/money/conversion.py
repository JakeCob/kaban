"""Currency conversion helpers.

Two flavors:
  - `to_php(amount, currency, rate)` — pure arithmetic, caller supplies the rate.
  - `convert_to_php(session, amount, currency)` — looks up the FX rate itself.

`py-moneyed` is used for the immutable `Money` type in application code; here we
work in `Decimal` because the whole DB layer stores decimals and Money would just
add an unwrap on every read.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from tracker.money.fx import FxStatus, get_fx_rate

_PHP_QUANT = Decimal("0.0001")
PHP = "PHP"


def quantize_php(amount: Decimal) -> Decimal:
    return amount.quantize(_PHP_QUANT, rounding=ROUND_HALF_UP)


def to_php(amount: Decimal, currency: str, rate: Decimal) -> Decimal:
    """Convert `amount` in `currency` to PHP using `rate` (amount_in_currency * rate == amount_in_php).

    PHP-native amounts pass through unchanged.
    """
    if currency == PHP:
        return quantize_php(amount)
    return quantize_php(amount * rate)


async def convert_to_php(
    session: AsyncSession, amount: Decimal, currency: str
) -> tuple[Decimal, FxStatus]:
    """Look up the FX rate and convert. Raises FxUnavailable via get_fx_rate."""
    rate, status = await get_fx_rate(session, currency, PHP)
    return to_php(amount, currency, rate), status
