"""Source registry: maps slug → PriceSource instance and picks the source for a query.

Kept deliberately tiny — just a dict lookup and a `for source in sources: can_handle`
scan. Adding a new source is one import + one line in `_build_default_sources`.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from tracker.clients.metagross import MetagrossClient
from tracker.sources.apify import ApifyClient
from tracker.sources.apify_carousell import ApifyCarousellPHSource
from tracker.sources.apify_chrono24 import ApifyChrono24Source
from tracker.sources.apify_lamudi import ApifyLamudiSource
from tracker.sources.apify_philkotse import ApifyPhilkotseSource
from tracker.sources.apify_shopee import ApifyShopeePHSource
from tracker.sources.base import PriceQuery, PriceSource
from tracker.sources.manual import ManualSource
from tracker.sources.metagross import MetagrossSource


class SourceRegistry:
    def __init__(self, sources: list[PriceSource]) -> None:
        self._by_slug = {s.slug: s for s in sources}
        self._ordered = list(sources)

    def get(self, slug: str) -> PriceSource:
        return self._by_slug[slug]

    def pick(
        self, query: PriceQuery, product: dict[str, Any] | None = None
    ) -> PriceSource | None:
        for source in self._ordered:
            if source.can_handle(query, product):
                return source
        return None

    def all(self) -> list[PriceSource]:
        return list(self._ordered)

    def __contains__(self, slug: str) -> bool:
        return slug in self._by_slug


def _build_default_sources() -> list[PriceSource]:
    apify = ApifyClient()
    return [
        MetagrossSource(MetagrossClient()),
        ApifyChrono24Source(apify),
        ApifyCarousellPHSource(apify),
        ApifyShopeePHSource(apify),
        ApifyLamudiSource(apify),
        ApifyPhilkotseSource(apify),
        ManualSource(),
    ]


@lru_cache(maxsize=1)
def get_source_registry() -> SourceRegistry:
    """Application-scoped source registry. Rebuilt on cache clear (for tests)."""
    return SourceRegistry(_build_default_sources())


def reset_source_registry() -> None:
    """Testing hook — drop the cached registry so overrides take effect."""
    get_source_registry.cache_clear()
