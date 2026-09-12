"""Unit tests for pure inventory-service logic (no DB required)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from tracker.services.inventory import compute_cost_php_snapshot


class TestComputeCostPhpSnapshot:
    def test_multiplies_and_quantizes_to_four_decimal_places(self) -> None:
        # 1000 USD * 56.5 PHP/USD = 56 500 PHP
        assert compute_cost_php_snapshot(Decimal("1000"), Decimal("56.5")) == Decimal("56500.0000")

    def test_preserves_precision_below_one_php(self) -> None:
        # A tiny cost still quantizes cleanly.
        result = compute_cost_php_snapshot(Decimal("0.12"), Decimal("0.5"))
        assert result == Decimal("0.0600")

    def test_rounds_half_up_at_the_fifth_decimal(self) -> None:
        # 1 * 1.23456789 = 1.23456789 → quantizes to 1.2346 (half-up on 5th place).
        result = compute_cost_php_snapshot(Decimal("1"), Decimal("1.23456789"))
        assert result == Decimal("1.2346")

    @pytest.mark.parametrize(
        "amount,fx,expected",
        [
            ("100", "1", "100.0000"),
            ("0", "56.5", "0.0000"),
            ("2500.50", "56.4321", "141108.4661"),
        ],
    )
    def test_table(self, amount: str, fx: str, expected: str) -> None:
        result = compute_cost_php_snapshot(Decimal(amount), Decimal(fx))
        assert result == Decimal(expected)
