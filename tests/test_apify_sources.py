"""Apify source tests — mock at the ApifyClient boundary so nothing hits the network.

For each source we prove three things:
  1. can_handle picks up its target category.
  2. fetch_latest turns a fixture actor response into a PriceResult with the
     expected currency and a median price.
  3. When the actor returns nothing / bad data, fetch_latest returns None.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from tracker.db.enums import ProductSource
from tracker.sources.apify import ApifyClient, _BaseApifySource
from tracker.sources.apify_carousell import ApifyCarousellPHSource
from tracker.sources.apify_chrono24 import ApifyChrono24Source
from tracker.sources.apify_lamudi import ApifyLamudiSource
from tracker.sources.apify_philkotse import ApifyPhilkotseSource
from tracker.sources.apify_shopee import ApifyShopeePHSource
from tracker.sources.base import PriceQuery

# Some tests below are sync (parametrized can_handle), so mark async ones per-function.


class _StubApifyClient(ApifyClient):
    """Records call arguments and returns canned dataset items."""

    def __init__(self, items: list[dict[str, Any]] | Exception) -> None:
        self._items = items
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def run_actor(  # type: ignore[override]
        self, actor_id: str, run_input: dict[str, Any], timeout_secs: int | None = 300
    ) -> list[dict[str, Any]]:
        self.calls.append((actor_id, run_input))
        if isinstance(self._items, Exception):
            raise self._items
        return self._items


def _local_query(**hints: Any) -> PriceQuery:
    return PriceQuery(
        product_source=ProductSource.LOCAL,
        local_product_id=uuid4(),
        hints=hints,
    )


@pytest.mark.parametrize(
    "cls,slug,target_category,default_currency",
    [
        (ApifyChrono24Source, "apify_chrono24", "watch", "USD"),
        (ApifyCarousellPHSource, "apify_carousell_ph", "gadget", "PHP"),
        (ApifyShopeePHSource, "apify_shopee_ph", "gadget", "PHP"),
        (ApifyLamudiSource, "apify_lamudi", "property", "PHP"),
        (ApifyPhilkotseSource, "apify_philkotse", "car", "PHP"),
    ],
)
def test_can_handle_matches_target_category(
    cls: type[_BaseApifySource],
    slug: str,
    target_category: str,
    default_currency: str,  # noqa: ARG001 — parametrized alongside for clarity
) -> None:
    source = cls(_StubApifyClient([]))
    query = _local_query()
    assert source.can_handle(query, {"category_slug": target_category})
    # Different category with no hint → not this source's problem.
    assert not source.can_handle(query, {"category_slug": "unrelated"})


@pytest.mark.asyncio
async def test_chrono24_fetches_median_price() -> None:
    """Five listings → median (sorted middle) is 300."""
    items = [
        {"price": 250, "currency": "USD"},
        {"price": 275, "currency": "USD"},
        {"price": 300, "currency": "USD"},
        {"price": 400, "currency": "USD"},
        {"price": 500, "currency": "USD"},
    ]
    stub = _StubApifyClient(items)
    source = ApifyChrono24Source(stub)

    result = await source.fetch_latest(_local_query(apify_chrono24_url="https://example/watch/1"))

    assert result is not None
    assert result.amount == Decimal("300")
    assert result.currency == "USD"
    assert result.source_slug == "apify_chrono24"
    assert result.raw == {"sample_size": 5}
    assert len(stub.calls) == 1
    assert stub.calls[0][0] == "memo23/chrono24-scraper"
    assert stub.calls[0][1] == {"startUrls": [{"url": "https://example/watch/1"}]}


@pytest.mark.asyncio
async def test_returns_none_when_actor_yields_no_prices() -> None:
    source = ApifyChrono24Source(_StubApifyClient([]))
    assert (
        await source.fetch_latest(_local_query(apify_chrono24_url="https://example/x"))
    ) is None


@pytest.mark.asyncio
async def test_returns_none_when_no_hint_and_no_url() -> None:
    """Without a URL/search hint the source can't build actor input; returns None."""
    source = ApifyCarousellPHSource(_StubApifyClient([]))
    # No hint at all — nothing to route.
    assert await source.fetch_latest(_local_query()) is None


@pytest.mark.asyncio
async def test_batch_calls_actor_once_per_query() -> None:
    """fetch_latest_batch fans out — 3 queries → 3 actor calls (semaphore-throttled)."""
    stub = _StubApifyClient([{"price": 100, "currency": "USD"}])
    source = ApifyChrono24Source(stub)
    queries = [
        _local_query(apify_chrono24_url=f"https://example/watch/{i}") for i in range(3)
    ]

    results = await source.fetch_latest_batch(queries)

    assert len(results) == 3
    assert all(r is not None and r.amount == Decimal("100") for r in results)
    assert len(stub.calls) == 3


@pytest.mark.asyncio
async def test_actor_failure_becomes_none_not_exception() -> None:
    """A blown-up actor call surfaces as None, so one bad query never kills a batch."""
    from tracker.sources.apify import ApifyRunError

    source = ApifyChrono24Source(_StubApifyClient(ApifyRunError("actor timed out")))
    assert (
        await source.fetch_latest(_local_query(apify_chrono24_url="https://example/x"))
    ) is None
