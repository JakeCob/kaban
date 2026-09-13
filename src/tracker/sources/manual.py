"""Manual source — a placeholder for user-submitted prices.

Manual prices are inserted directly via POST /prices/manual. This source only
exists so the /prices/refresh dispatch code can look every source up by slug;
`can_handle` always returns False, so the refresh loop never picks it.
"""

from __future__ import annotations

from typing import Any

from tracker.sources.base import PriceQuery, PriceResult, PriceSource


class ManualSource(PriceSource):
    slug = "manual"

    async def fetch_latest(self, query: PriceQuery) -> PriceResult | None:  # noqa: ARG002
        return None

    def can_handle(
        self, query: PriceQuery, product: dict[str, Any] | None = None  # noqa: ARG002
    ) -> bool:
        return False
