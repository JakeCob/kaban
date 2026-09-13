"""MetagrossSource — proves the batch-of-N acceptance path (SPEC Phase 2).

The key assertion: given 3 Metagross queries, fetch_latest_batch issues exactly
ONE upstream HTTP call to /products/prices/batch, not three.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from tracker.clients.metagross import MetagrossClient
from tracker.db.enums import ConditionType, ProductSource
from tracker.sources.base import PriceQuery
from tracker.sources.metagross import MetagrossSource

pytestmark = pytest.mark.asyncio


def _snap(product_id: str, price: float, condition: str = "NM") -> dict:
    return {
        "product_id": product_id,
        "source": "tcgplayer",
        "price": price,
        "currency": "USD",
        "condition": condition,
        "grade": None,
        "captured_at": "2026-09-12T14:30:00Z",
        "raw": {},
    }


async def test_batch_of_three_issues_one_upstream_call(httpx_mock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="https://metagross.test/v1/products/prices/batch",
        json={
            "results": [
                {"product_id": "01JAA", "price": _snap("01JAA", 100)},
                {"product_id": "01JBB", "price": _snap("01JBB", 200)},
                {"product_id": "01JCC", "price": _snap("01JCC", 300)},
            ]
        },
    )

    async with MetagrossClient(base_url="https://metagross.test/v1", token="t") as client:
        source = MetagrossSource(client)
        results = await source.fetch_latest_batch(
            [
                PriceQuery(
                    product_source=ProductSource.METAGROSS,
                    external_product_id=pid,
                    condition=ConditionType.NM,
                )
                for pid in ("01JAA", "01JBB", "01JCC")
            ]
        )

    # THE assertion for the Phase 2 acceptance criteria.
    assert len(httpx_mock.get_requests()) == 1

    assert [r.amount for r in results] == [Decimal("100"), Decimal("200"), Decimal("300")]
    assert results[0].source_slug == "metagross"


async def test_can_handle_rejects_local_queries() -> None:
    from uuid import uuid4

    async with MetagrossClient(base_url="https://x/v1", token="t") as client:
        source = MetagrossSource(client)
    assert source.can_handle(
        PriceQuery(product_source=ProductSource.METAGROSS, external_product_id="01JXX")
    )
    assert not source.can_handle(
        PriceQuery(product_source=ProductSource.LOCAL, local_product_id=uuid4())
    )


async def test_batch_preserves_order_and_maps_no_price_to_none(httpx_mock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="https://metagross.test/v1/products/prices/batch",
        json={
            "results": [
                {"product_id": "01JAA", "price": _snap("01JAA", 100)},
                {"product_id": "01JBB", "error": {"code": "no_price_available"}},
            ]
        },
    )

    async with MetagrossClient(base_url="https://metagross.test/v1", token="t") as client:
        source = MetagrossSource(client)
        results = await source.fetch_latest_batch(
            [
                PriceQuery(
                    product_source=ProductSource.METAGROSS, external_product_id="01JAA"
                ),
                PriceQuery(
                    product_source=ProductSource.METAGROSS, external_product_id="01JBB"
                ),
            ]
        )
    assert results[0] is not None
    assert results[0].amount == Decimal("100")
    assert results[1] is None
