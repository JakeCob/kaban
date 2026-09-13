"""Metagross pricing source — the API-backed TCG data provider.

Overrides `fetch_latest_batch` so a refresh over N products issues one upstream
call (the Metagross batch endpoint), not N. `fetch_latest` is a batch-of-one for
symmetry.
"""

from __future__ import annotations

from typing import Any

from tracker.clients.metagross import (
    MetagrossClient,
    MetagrossPriceBatchEntry,
    MetagrossPriceRequest,
)
from tracker.db.enums import ConditionType, ProductSource
from tracker.sources.base import PriceQuery, PriceResult, PriceSource


class MetagrossSource(PriceSource):
    slug = "metagross"

    def __init__(self, client: MetagrossClient) -> None:
        self._client = client

    def can_handle(
        self, query: PriceQuery, product: dict[str, Any] | None = None  # noqa: ARG002
    ) -> bool:
        return (
            query.product_source == ProductSource.METAGROSS
            and query.external_product_id is not None
        )

    async def fetch_latest(self, query: PriceQuery) -> PriceResult | None:
        results = await self.fetch_latest_batch([query])
        return results[0]

    async def fetch_latest_batch(
        self, queries: list[PriceQuery]
    ) -> list[PriceResult | None]:
        # Any query this source can't handle short-circuits to None; the client
        # only gets asked about queries that are actually Metagross-shaped.
        handleable_indexes: list[int] = []
        requests: list[MetagrossPriceRequest] = []
        for i, q in enumerate(queries):
            if not self.can_handle(q):
                continue
            # Type checker: can_handle guarantees external_product_id is not None.
            assert q.external_product_id is not None
            requests.append(
                MetagrossPriceRequest(
                    product_id=q.external_product_id,
                    condition=q.condition.value if q.condition else None,
                    grader=q.grader,
                    grade=q.grade_value,
                )
            )
            handleable_indexes.append(i)

        out: list[PriceResult | None] = [None] * len(queries)
        if not requests:
            return out

        entries = await self._client.prices_batch(requests)
        for idx, entry in zip(handleable_indexes, entries, strict=True):
            out[idx] = _entry_to_result(entry)
        return out


def _entry_to_result(entry: MetagrossPriceBatchEntry) -> PriceResult | None:
    if entry.price is None:
        return None
    snap = entry.price
    grade = snap.grade or {}
    return PriceResult(
        amount=snap.price,
        currency=snap.currency,
        condition=ConditionType(snap.condition) if snap.condition else None,
        grader=grade.get("grader"),
        grade_value=grade.get("grade"),
        raw={**snap.raw, "source": snap.source, "captured_at": snap.captured_at},
        source_slug="metagross",
    )
