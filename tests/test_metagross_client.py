"""Metagross HTTP client contract tests (no real network)."""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest

from tracker.clients.metagross import (
    MetagrossClient,
    MetagrossPriceRequest,
    MetagrossPriceSnapshot,
)

pytestmark = pytest.mark.asyncio


def _sample_snapshot(product_id: str = "01JEXXX", price: float = 245.0) -> dict:
    return {
        "product_id": product_id,
        "source": "tcgplayer",
        "price": price,
        "currency": "USD",
        "condition": "NM",
        "grade": {"grader": "PSA", "grade": "10"},
        "captured_at": "2026-09-12T14:30:00Z",
        "raw": {"market": 245.0, "low": 210.0},
    }


async def test_get_product_returns_parsed_dict(httpx_mock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://metagross.test/v1/products/01JEXXX",
        json={"id": "01JEXXX", "game": "pokemon", "category": "single"},
    )
    async with MetagrossClient(base_url="https://metagross.test/v1", token="t") as c:
        product = await c.get_product("01JEXXX")
    assert product["id"] == "01JEXXX"


async def test_price_latest_returns_typed_snapshot(httpx_mock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://metagross.test/v1/products/01JEXXX/price/latest?condition=NM",
        json=_sample_snapshot(),
    )
    async with MetagrossClient(base_url="https://metagross.test/v1", token="t") as c:
        snap = await c.price_latest("01JEXXX", condition="NM")
    assert isinstance(snap, MetagrossPriceSnapshot)
    assert snap.price == Decimal("245.0")
    assert snap.grade == {"grader": "PSA", "grade": "10"}


async def test_price_latest_404_returns_none(httpx_mock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://metagross.test/v1/products/01JXX/price/latest",
        status_code=404,
        json={"error": {"code": "no_price_available", "message": "…"}},
    )
    async with MetagrossClient(base_url="https://metagross.test/v1", token="t") as c:
        assert await c.price_latest("01JXX") is None


async def test_prices_batch_issues_single_request_for_up_to_500(httpx_mock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="https://metagross.test/v1/products/prices/batch",
        json={
            "results": [
                {"product_id": "01JAA", "price": _sample_snapshot("01JAA", 100.0)},
                {"product_id": "01JBB", "price": _sample_snapshot("01JBB", 200.0)},
                {"product_id": "01JCC", "error": {"code": "no_price_available"}},
            ]
        },
    )
    async with MetagrossClient(base_url="https://metagross.test/v1", token="t") as c:
        entries = await c.prices_batch(
            [
                MetagrossPriceRequest(product_id="01JAA"),
                MetagrossPriceRequest(product_id="01JBB"),
                MetagrossPriceRequest(product_id="01JCC"),
            ]
        )
    assert len(httpx_mock.get_requests()) == 1
    assert entries[0].price is not None
    assert entries[0].price.price == Decimal("100.0")
    assert entries[2].price is None
    assert entries[2].error == {"code": "no_price_available"}


async def test_prices_batch_chunks_at_500(httpx_mock) -> None:
    def _chunk_response(request: httpx.Request) -> httpx.Response:
        body = request.read()
        # Parse to count how many product_ids were in this chunk.
        import json

        payload = json.loads(body)
        return httpx.Response(
            200,
            json={
                "results": [
                    {"product_id": r["product_id"], "price": _sample_snapshot(r["product_id"])}
                    for r in payload["requests"]
                ],
            },
        )

    # pytest-httpx 0.32 matches each callback once; register one per expected chunk.
    httpx_mock.add_callback(_chunk_response, method="POST")
    httpx_mock.add_callback(_chunk_response, method="POST")

    async with MetagrossClient(base_url="https://metagross.test/v1", token="t") as c:
        # 750 items → two chunks: 500 + 250.
        entries = await c.prices_batch(
            [MetagrossPriceRequest(product_id=f"ID{i}") for i in range(750)]
        )

    assert len(entries) == 750
    assert len(httpx_mock.get_requests()) == 2
