"""Unit tests for pure resale math (no DB, no FX lookup)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from tracker.money.conversion import to_php
from tracker.services.resale import apply_fees


class TestApplyFees:
    def test_percentage_and_flat_stack(self) -> None:
        # 2000 USD on eBay: 13.25% platform + 3% payment + $0 listing.
        fees = {"platform_pct": 0.1325, "payment_pct": 0.03, "listing_flat": 0}
        # 2000 * (1 - 0.1625) = 2000 * 0.8375 = 1675
        assert apply_fees(Decimal("2000"), fees) == Decimal("1675.0000")

    def test_missing_keys_treated_as_zero(self) -> None:
        # Carousell PH placeholder: all-zero fee structure returns gross unchanged.
        fees = {"platform_pct": 0.0, "payment_pct": 0.0, "listing_flat": 0}
        assert apply_fees(Decimal("5000"), fees) == Decimal("5000")

    def test_verify_and_note_keys_are_ignored(self) -> None:
        # Seed rows include _verify / _note markers — must not blow up.
        fees = {"platform_pct": 0.0, "_verify": "SPEC §18"}
        assert apply_fees(Decimal("1000"), fees) == Decimal("1000")

    def test_flat_listing_deducted_in_native_currency(self) -> None:
        fees = {"platform_pct": 0.1, "payment_pct": 0.0, "listing_flat": 50}
        # 1000 * 0.9 = 900, then - 50 = 850
        assert apply_fees(Decimal("1000"), fees) == Decimal("850.0")


class TestToPhp:
    def test_php_native_pass_through(self) -> None:
        assert to_php(Decimal("1234.56"), "PHP", Decimal("1")) == Decimal("1234.5600")

    def test_usd_to_php_multiplies(self) -> None:
        assert to_php(Decimal("100"), "USD", Decimal("56.5")) == Decimal("5650.0000")

    @pytest.mark.parametrize(
        "amount,currency,rate,expected",
        [
            ("2000", "USD", "56.5", "113000.0000"),
            ("50000", "JPY", "0.3821", "19105.0000"),
            ("0", "USD", "56.5", "0.0000"),
        ],
    )
    def test_table(
        self, amount: str, currency: str, rate: str, expected: str
    ) -> None:
        assert to_php(Decimal(amount), currency, Decimal(rate)) == Decimal(expected)
