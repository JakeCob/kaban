"""Chrono24 pricing via memo23/chrono24-scraper (uses Chrono24's mobile JSON API)."""

from __future__ import annotations

from typing import Any

from tracker.db.enums import ProductSource
from tracker.sources.apify import _BaseApifySource
from tracker.sources.base import PriceQuery


class ApifyChrono24Source(_BaseApifySource):
    slug = "apify_chrono24"
    actor_id = "memo23/chrono24-scraper"
    price_field = "price"
    currency_field = "currency"
    default_currency = "USD"

    def can_handle(
        self, query: PriceQuery, product: dict[str, Any] | None = None
    ) -> bool:
        if query.product_source != ProductSource.LOCAL:
            return False
        # Handles watches or any product with a chrono24_url hint.
        cat = (product or {}).get("category_slug")
        return cat == "watch" or bool(self._build_input(query))
