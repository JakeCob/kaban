"""Carousell PH pricing via scrapesage/carousell-scraper (pure HTTP, no browser)."""

from __future__ import annotations

from typing import Any

from tracker.db.enums import ProductSource
from tracker.sources.apify import _BaseApifySource
from tracker.sources.base import PriceQuery


class ApifyCarousellPHSource(_BaseApifySource):
    slug = "apify_carousell_ph"
    actor_id = "scrapesage/carousell-scraper"
    price_field = "price"
    currency_field = "currency"
    default_currency = "PHP"

    def can_handle(
        self, query: PriceQuery, product: dict[str, Any] | None = None
    ) -> bool:
        if query.product_source != ProductSource.LOCAL:
            return False
        cat = (product or {}).get("category_slug")
        return cat in {"gadget", "sneaker", "generic", "tcg_single"} or bool(
            self._build_input(query)
        )
