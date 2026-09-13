"""Frankfurter client — mocked HTTP contract test."""

from __future__ import annotations

from decimal import Decimal

import pytest

from tracker.clients.frankfurter import FrankfurterClient

pytestmark = pytest.mark.asyncio


async def test_latest_rates_parses_response(httpx_mock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.frankfurter.dev/v1/latest?base=PHP&symbols=USD,JPY,TWD,EUR,GBP",
        json={
            "amount": 1.0,
            "base": "PHP",
            "date": "2026-09-12",
            "rates": {
                "USD": 0.0177,
                "JPY": 2.6180,
                "TWD": 0.5620,
                "EUR": 0.0162,
                "GBP": 0.0139,
            },
        },
    )
    async with FrankfurterClient() as c:
        latest = await c.latest_rates("PHP", ["USD", "JPY", "TWD", "EUR", "GBP"])

    assert latest.base == "PHP"
    assert latest.rates["USD"] == Decimal("0.0177")
    assert latest.rates["JPY"] == Decimal("2.618")
