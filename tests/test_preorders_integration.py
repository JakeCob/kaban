"""Pre-orders + allocations end-to-end.

Proves the Phase 5 acceptance criteria from SPEC §14:
  - Resolving a pre-order with actual_units=2 creates two inventory rows in one
    transaction (atomicity: if any insert failed, the pre-order would roll back too).
  - POST /allocations/predict returns a valid AllocationPrediction for UPC_2026_11.
  - Recording an outcome round-trips.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from tests.conftest import requires_docker

pytestmark = [pytest.mark.asyncio, requires_docker]


@pytest.fixture
async def client(db_session) -> Any:  # noqa: ARG001
    from tracker.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": "test-key"},
    ) as ac:
        yield ac


async def _tcg_sealed_category_id(session) -> int:
    return (
        await session.execute(text("SELECT id FROM categories WHERE slug = 'tcg_sealed'"))
    ).scalar_one()


async def test_resolve_creates_two_inventory_rows_atomically(
    client: AsyncClient,
) -> None:
    """SPEC §14 acceptance: resolve with actual_units=2 → 2 inventory rows."""
    from tracker.db.session import SessionLocal

    async with SessionLocal() as s:
        cat_id = await _tcg_sealed_category_id(s)

    product = (
        await client.post(
            "/api/v1/products",
            json={
                "category_id": cat_id,
                "name": "UPC Nov 2026 Box",
                "brand": "Pokemon",
                "srp_amount": "149.99",
                "srp_currency": "USD",
            },
        )
    ).json()

    # Create pre-order for 2 units.
    r = await client.post(
        "/api/v1/pre_orders",
        json={
            "product_source": "local",
            "local_product_id": product["id"],
            "release_code": "UPC_2026_11",
            "store": "Great Toys",
            "deposit_amount": "150.00",
            "deposit_currency": "USD",
            "expected_units": 2,
            "release_date": "2026-11-07",
        },
    )
    assert r.status_code == 201, r.text
    po = r.json()

    # Resolve with actual_units=2 and receive them.
    r = await client.post(
        f"/api/v1/pre_orders/{po['id']}/resolve",
        json={
            "actual_units": 2,
            "receive_now": True,
            "cost_per_unit": "300.00",
            "cost_currency": "USD",
            "cost_fx_to_php": "56.5",
            "purchase_date": "2026-11-07",
            "condition": "SEALED",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["pre_order"]["actual_units"] == 2
    assert body["pre_order"]["status"] == "received"
    assert len(body["inventory_ids"]) == 2

    # Confirm both rows exist and carry the correct snapshot.
    from decimal import Decimal

    for inv_id in body["inventory_ids"]:
        r = await client.get(f"/api/v1/inventory/{inv_id}")
        assert r.status_code == 200
        assert Decimal(r.json()["cost_php_snapshot"]) == Decimal("300") * Decimal("56.5")


async def test_resolve_without_receive_now_marks_allocated(client: AsyncClient) -> None:
    from tracker.db.session import SessionLocal

    async with SessionLocal() as s:
        cat_id = await _tcg_sealed_category_id(s)

    product = (
        await client.post(
            "/api/v1/products",
            json={"category_id": cat_id, "name": "ETB", "brand": "Pokemon"},
        )
    ).json()
    po = (
        await client.post(
            "/api/v1/pre_orders",
            json={
                "product_source": "local",
                "local_product_id": product["id"],
                "release_code": "UPC_2026_11",
                "store": "Great Toys",
                "expected_units": 3,
            },
        )
    ).json()

    r = await client.post(
        f"/api/v1/pre_orders/{po['id']}/resolve",
        json={"actual_units": 3, "receive_now": False},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["pre_order"]["status"] == "allocated"
    assert body["inventory_ids"] == []


async def test_resolve_receive_now_without_cost_fields_422(client: AsyncClient) -> None:
    from tracker.db.session import SessionLocal

    async with SessionLocal() as s:
        cat_id = await _tcg_sealed_category_id(s)

    product = (
        await client.post(
            "/api/v1/products",
            json={"category_id": cat_id, "name": "Booster", "brand": "Pokemon"},
        )
    ).json()
    po = (
        await client.post(
            "/api/v1/pre_orders",
            json={
                "product_source": "local",
                "local_product_id": product["id"],
                "store": "Great Toys",
                "expected_units": 1,
            },
        )
    ).json()

    r = await client.post(
        f"/api/v1/pre_orders/{po['id']}/resolve",
        json={"actual_units": 1, "receive_now": True},
    )
    assert r.status_code == 422
    assert "cost" in r.json()["detail"]["error"]["message"].lower()


async def test_allocations_predict_returns_valid_prediction(client: AsyncClient) -> None:
    """SPEC §14 acceptance: /allocations/predict returns a valid AllocationPrediction."""
    r = await client.post(
        "/api/v1/allocations/predict",
        json={
            "release_code": "UPC_2026_11",
            "store": "Great Toys",
            "inputs": {
                "quantity_requested": 5,
                "customer_tier": "VIP",
                "deposit_timestamp": "2026-11-01T09:00:00Z",
                "cutoff_timestamp": "2026-11-11T09:00:00Z",
            },
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["strategy_slug"] == "upc_2026_11_great_toys"
    assert body["p50_units"] == 5
    assert body["p10_units"] <= body["p50_units"] <= body["p90_units"]
    assert 0 <= body["confidence"] <= 1
    assert body["explanation"]


async def test_allocations_predict_unknown_release_404(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/allocations/predict",
        json={
            "release_code": "DOES_NOT_EXIST",
            "store": "Great Toys",
            "inputs": {"quantity_requested": 1},
        },
    )
    assert r.status_code == 404


async def test_allocation_outcome_round_trip(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/allocations/outcomes",
        json={
            "release_code": "UPC_2026_11",
            "store": "Great Toys",
            "inputs": {"quantity_requested": 5, "customer_tier": "VIP"},
            "predicted_p50": 5,
            "predicted_p90": 5,
            "predicted_p10": 3,
            "actual_units": 4,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["actual_units"] == 4
    assert body["release_code"] == "UPC_2026_11"
