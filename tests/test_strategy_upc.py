"""Golden-file test for the UPC_2026_11_GreatToys strategy.

Fixtures live in tests/fixtures/allocations/upc_2026_11_great_toys.json. If the
strategy math changes, either update the fixture (deliberate) or the change is
a regression (unintentional). No mocks — the strategy is pure.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tracker.strategies.base import AllocationInputs
from tracker.strategies.upc_2026_11_great_toys import UPC_2026_11_GreatToys

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "allocations"
    / "upc_2026_11_great_toys.json"
)


def _cases() -> list[dict]:
    return json.loads(FIXTURE.read_text())


@pytest.mark.parametrize("case", _cases(), ids=lambda c: c["name"])
def test_prediction_matches_golden(case: dict) -> None:
    inputs = AllocationInputs.model_validate(case["inputs"])
    prediction = UPC_2026_11_GreatToys().predict(inputs, params={})
    expected = case["expected"]

    assert prediction.p50_units == expected["p50_units"], "p50 drift"
    assert prediction.p90_units == expected["p90_units"], "p90 drift"
    assert prediction.p10_units == expected["p10_units"], "p10 drift"
    assert prediction.confidence == expected["confidence"], "confidence drift"
    # expected_units is a float — allow a tiny slop for accumulated fp error.
    assert abs(prediction.expected_units - expected["expected_units"]) < 0.02, (
        f"expected_units drift: got {prediction.expected_units}, want {expected['expected_units']}"
    )
    # Sanity checks that don't depend on the fixture.
    assert prediction.p10_units <= prediction.p50_units <= prediction.p90_units
    assert 0 <= prediction.p90_units <= inputs.quantity_requested


def test_registry_finds_it() -> None:
    from tracker.strategies import registry

    cls = registry.get("upc_2026_11_great_toys")
    assert cls is UPC_2026_11_GreatToys
