"""Philkotse pricing via rainminer/philkotse-scraper."""

from __future__ import annotations

from typing import Any

from tracker.db.enums import ProductSource
from tracker.sources.apify import _BaseApifySource
from tracker.sources.base import PriceQuery


class ApifyPhilkotseSource(_BaseApifySource):
    slug = "apify_philkotse"
    actor_id = "rainminer/philkotse-scraper"
    price_field = "price"
    currency_field = "currency"
    default_currency = "PHP"

    def can_handle(
        self, query: PriceQuery, product: dict[str, Any] | None = None
    ) -> bool:
        if query.product_source != ProductSource.LOCAL:
            return False
        cat = (product or {}).get("category_slug")
        return cat == "car" or bool(self._build_input(query))
