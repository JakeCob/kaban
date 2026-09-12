"""Schema-level validation tests. No DB — these prove the Pydantic constraints."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from tracker.db.enums import ConditionType, ProductSource
from tracker.schemas.inventory import InventoryCreate


def _valid_local(**overrides: object) -> dict:
    base = {
        "product_source": ProductSource.LOCAL,
        "local_product_id": uuid4(),
        "cost_amount": Decimal("100"),
        "cost_currency": "PHP",
        "cost_fx_to_php": Decimal("1"),
        "purchase_date": date(2026, 1, 1),
    }
    base.update(overrides)
    return base


def test_local_source_requires_local_product_id() -> None:
    with pytest.raises(ValidationError, match="local_product_id"):
        InventoryCreate.model_validate(
            _valid_local(local_product_id=None, product_source=ProductSource.LOCAL)
        )


def test_local_source_forbids_external_product_id() -> None:
    with pytest.raises(ValidationError, match="external_product_id"):
        InventoryCreate.model_validate(
            _valid_local(external_product_id="01JXX...")
        )


def test_metagross_source_requires_external_product_id() -> None:
    with pytest.raises(ValidationError, match="external_product_id"):
        InventoryCreate.model_validate(
            _valid_local(product_source=ProductSource.METAGROSS, local_product_id=None)
        )


def test_metagross_source_forbids_local_product_id() -> None:
    with pytest.raises(ValidationError, match="local_product_id"):
        InventoryCreate.model_validate(
            _valid_local(
                product_source=ProductSource.METAGROSS,
                external_product_id="01JXX",
                # local_product_id kept from _valid_local
            )
        )


def test_valid_local_payload_parses() -> None:
    parsed = InventoryCreate.model_validate(_valid_local())
    assert parsed.product_source == ProductSource.LOCAL
    assert parsed.condition == ConditionType.SEALED
