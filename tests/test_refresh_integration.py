"""Phase 4 acceptance: per-source refresh writes snapshots, failures stay isolated.

Runs against a real Postgres (testcontainers). Apify itself is stubbed with an
in-process ApifyClient that returns fixture data — nothing hits the network.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from tests.conftest import requires_docker
from tracker.sources.apify import ApifyClient, ApifyRunError

pytestmark = [pytest.mark.asyncio, requires_docker]


class _StubApifyClient(ApifyClient):
    """Returns per-actor canned items. Raise ApifyRunError to simulate a total blowout."""

    def __init__(self, items_by_actor: dict[str, list[dict[str, Any]] | Exception]) -> None:
        self.items_by_actor = items_by_actor
        self.calls: list[str] = []

    async def run_actor(  # type: ignore[override]
        self, actor_id: str, run_input: dict[str, Any], timeout_secs: int | None = 300
    ) -> list[dict[str, Any]]:
        self.calls.append(actor_id)
        val = self.items_by_actor.get(actor_id, [])
        if isinstance(val, Exception):
            raise val
        return val


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


async def _watch_category_id(session) -> int:
    return (
        await session.execute(text("SELECT id FROM categories WHERE slug = 'watch'"))
    ).scalar_one()


async def _install_stub_registry(items_by_actor: dict[str, Any]) -> _StubApifyClient:
    """Swap the app's source registry for one whose Apify sources use a stub client."""
    from tracker.sources.apify_carousell import ApifyCarousellPHSource
    from tracker.sources.apify_chrono24 import ApifyChrono24Source
    from tracker.sources.apify_lamudi import ApifyLamudiSource
    from tracker.sources.apify_philkotse import ApifyPhilkotseSource
    from tracker.sources.apify_shopee import ApifyShopeePHSource
    from tracker.sources.manual import ManualSource
    from tracker.sources.registry import SourceRegistry, get_source_registry

    stub = _StubApifyClient(items_by_actor)
    registry = SourceRegistry(
        [
            ApifyChrono24Source(stub),
            ApifyCarousellPHSource(stub),
            ApifyShopeePHSource(stub),
            ApifyLamudiSource(stub),
            ApifyPhilkotseSource(stub),
            ManualSource(),
        ]
    )
    # FastAPI dependency override — cheaper than clearing the lru_cache.
    from tracker.main import app

    app.dependency_overrides[get_source_registry] = lambda: registry
    return stub


async def _create_watch_with_hint(client: AsyncClient, hint_url: str) -> dict:
    from tracker.db.session import SessionLocal

    async with SessionLocal() as s:
        watch_id = await _watch_category_id(s)

    r = await client.post(
        "/api/v1/products",
        json={
            "category_id": watch_id,
            "name": "Rolex Submariner",
            "brand": "Rolex",
            "attributes": {"apify_chrono24_url": hint_url},
        },
    )
    product = r.json()

    await client.post(
        "/api/v1/inventory",
        json={
            "product_source": "local",
            "local_product_id": product["id"],
            "cost_amount": "9000.00",
            "cost_currency": "USD",
            "cost_fx_to_php": "56.5",
            "purchase_date": "2026-06-15",
            "condition": "NEW",
        },
    )
    return product


async def test_chrono24_refresh_writes_snapshots_for_all_watches(
    client: AsyncClient,
) -> None:
    """Acceptance: seed 3 watches, POST /jobs/refresh-prices/apify_chrono24,
    every watch gets a snapshot."""
    from tracker.main import app

    try:
        stub = await _install_stub_registry(
            {"memo23/chrono24-scraper": [{"price": 9500, "currency": "USD"}]}
        )

        for i in range(3):
            await _create_watch_with_hint(client, f"https://chrono24.example/w/{i}")

        r = await client.post("/api/v1/jobs/refresh-prices/apify_chrono24")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["candidates"] == 3
        assert body["snapshots_written"] == 3
        assert body["warnings"] == []
        assert stub.calls == ["memo23/chrono24-scraper"] * 3
    finally:
        app.dependency_overrides.clear()


async def test_source_batch_failure_returns_summary_not_500(
    client: AsyncClient,
) -> None:
    """Acceptance: even if the actor blows up entirely, the endpoint returns a
    RefreshSummary listing what failed. No 500."""
    from tracker.main import app

    try:
        await _install_stub_registry(
            {"memo23/chrono24-scraper": ApifyRunError("upstream 500")}
        )
        await _create_watch_with_hint(client, "https://chrono24.example/one")

        r = await client.post("/api/v1/jobs/refresh-prices/apify_chrono24")
        assert r.status_code == 200
        body = r.json()
        # Actor error becomes None per item → 0 snapshots, 1 warning.
        assert body["snapshots_written"] == 0
        assert len(body["warnings"]) == 1
        assert "no price returned" in body["warnings"][0]
    finally:
        app.dependency_overrides.clear()


async def test_one_source_failing_leaves_others_alone(client: AsyncClient) -> None:
    """Acceptance: cron entries are separate, so this is really about the fan-out.
    Chrono24 fails; Shopee still writes a snapshot for its gadget."""
    from tracker.db.session import SessionLocal
    from tracker.main import app

    try:
        await _install_stub_registry(
            {
                "memo23/chrono24-scraper": ApifyRunError("boom"),
                "gio21/shopee-scraper": [{"price": 4500, "currency": "PHP"}],
            }
        )

        async with SessionLocal() as s:
            watch_id = await _watch_category_id(s)
            gadget_id = (
                await s.execute(text("SELECT id FROM categories WHERE slug = 'gadget'"))
            ).scalar_one()

        # A watch → routed to Chrono24 (fails).
        watch = (
            await client.post(
                "/api/v1/products",
                json={
                    "category_id": watch_id,
                    "name": "Speedy",
                    "attributes": {"apify_chrono24_url": "https://chrono24.example/w"},
                },
            )
        ).json()
        await client.post(
            "/api/v1/inventory",
            json={
                "product_source": "local",
                "local_product_id": watch["id"],
                "cost_amount": "3500.00",
                "cost_currency": "USD",
                "cost_fx_to_php": "56.5",
                "purchase_date": "2026-01-01",
            },
        )

        # A gadget → routed to Shopee.
        gadget = (
            await client.post(
                "/api/v1/products",
                json={
                    "category_id": gadget_id,
                    "name": "Steam Deck",
                    "attributes": {"apify_shopee_ph_url": "https://shopee.ph/x"},
                },
            )
        ).json()
        await client.post(
            "/api/v1/inventory",
            json={
                "product_source": "local",
                "local_product_id": gadget["id"],
                "cost_amount": "4000.00",
                "cost_currency": "PHP",
                "cost_fx_to_php": "1",
                "purchase_date": "2026-01-01",
            },
        )

        r = await client.post("/api/v1/jobs/refresh-prices")
        assert r.status_code == 200
        summaries = {s["source"]: s for s in r.json()}
        assert summaries["apify_chrono24"]["snapshots_written"] == 0
        assert summaries["apify_shopee_ph"]["snapshots_written"] == 1

        # Confirm the Shopee snapshot actually landed.
        r = await client.get(
            "/api/v1/prices/latest",
            params={"product_source": "local", "local_product_id": gadget["id"]},
        )
        assert r.status_code == 200
        assert Decimal(r.json()["price_amount"]) == Decimal("4500")
    finally:
        app.dependency_overrides.clear()
