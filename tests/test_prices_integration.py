"""End-to-end price flow — proves the Phase 2 acceptance path.

  1. POST inventory referencing a Metagross product_id.
  2. POST /prices/refresh for it (mocked upstream).
  3. GET /prices/latest returns the correct snapshot.
  4. POST /prices/manual works for a local product.

Skipped when Docker is unreachable.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import requires_docker

pytestmark = [pytest.mark.asyncio, requires_docker]


def _snap(product_id: str, price: float) -> dict:
    return {
        "product_id": product_id,
        "source": "tcgplayer",
        "price": price,
        "currency": "USD",
        "condition": "SEALED",
        "grade": None,
        "captured_at": "2026-09-12T14:30:00Z",
        "raw": {},
    }


@pytest.fixture
async def client(db_session) -> Any:  # noqa: ARG001 — bootstraps schema
    from tracker.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": "test-key"},
    ) as ac:
        yield ac


async def test_metagross_refresh_then_latest(client: AsyncClient, httpx_mock) -> None:
    # Point the Metagross client at the mocked host — the source registry
    # is cached, so blow it away first.
    import os

    os.environ["METAGROSS_BASE_URL"] = "https://metagross.test/v1"
    from tracker.config import get_settings
    from tracker.sources.registry import reset_source_registry

    get_settings.cache_clear()
    reset_source_registry()

    # Inventory needs a real external_product_id.
    r = await client.post(
        "/api/v1/inventory",
        json={
            "product_source": "metagross",
            "external_product_id": "01JAA",
            "cost_amount": "180.00",
            "cost_currency": "USD",
            "cost_fx_to_php": "56.5",
            "purchase_date": "2026-06-15",
            "condition": "SEALED",
        },
    )
    assert r.status_code == 201, r.text

    httpx_mock.add_response(
        method="POST",
        url="https://metagross.test/v1/products/prices/batch",
        json={"results": [{"product_id": "01JAA", "price": _snap("01JAA", 245.0)}]},
    )

    r = await client.post(
        "/api/v1/prices/refresh",
        json={
            "product_source": "metagross",
            "external_product_id": "01JAA",
            "condition": "SEALED",
        },
    )
    assert r.status_code == 201, r.text

    r = await client.get(
        "/api/v1/prices/latest",
        params={
            "product_source": "metagross",
            "external_product_id": "01JAA",
            "condition": "SEALED",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert Decimal(body["price_amount"]) == Decimal("245.0")
    assert body["price_currency"] == "USD"


async def test_manual_price_for_local_product(client: AsyncClient) -> None:
    from sqlalchemy import text

    from tracker.db.session import SessionLocal

    async with SessionLocal() as s:
        watch_id = (
            await s.execute(text("SELECT id FROM categories WHERE slug = 'watch'"))
        ).scalar_one()

    r = await client.post(
        "/api/v1/products",
        json={
            "category_id": watch_id,
            "name": "Rolex Submariner 124060",
            "brand": "Rolex",
        },
    )
    assert r.status_code == 201
    product = r.json()

    r = await client.post(
        "/api/v1/prices/manual",
        json={
            "product_source": "local",
            "local_product_id": product["id"],
            "condition": "NEW",
            "price_amount": "9250.00",
            "price_currency": "USD",
            "raw": {"note": "as sold, Christie's 09-2026"},
        },
    )
    assert r.status_code == 201, r.text

    r = await client.get(
        "/api/v1/prices/latest",
        params={
            "product_source": "local",
            "local_product_id": product["id"],
            "condition": "NEW",
        },
    )
    assert r.status_code == 200
    assert Decimal(r.json()["price_amount"]) == Decimal("9250.00")


async def test_history_returns_series_in_order(client: AsyncClient) -> None:
    from sqlalchemy import text

    from tracker.db.session import SessionLocal

    async with SessionLocal() as s:
        watch_id = (
            await s.execute(text("SELECT id FROM categories WHERE slug = 'watch'"))
        ).scalar_one()

    r = await client.post(
        "/api/v1/products",
        json={"category_id": watch_id, "name": "AP RO 15400ST", "brand": "AP"},
    )
    product = r.json()

    for price in ("10000.00", "10500.00", "11000.00"):
        await client.post(
            "/api/v1/prices/manual",
            json={
                "product_source": "local",
                "local_product_id": product["id"],
                "condition": "NEW",
                "price_amount": price,
                "price_currency": "USD",
            },
        )

    r = await client.get(
        "/api/v1/prices/history",
        params={
            "product_source": "local",
            "local_product_id": product["id"],
            "condition": "NEW",
        },
    )
    assert r.status_code == 200
    series = r.json()["series"]
    assert len(series) == 3
    assert [Decimal(p["price_amount"]) for p in series] == [
        Decimal("10000.00"),
        Decimal("10500.00"),
        Decimal("11000.00"),
    ]
