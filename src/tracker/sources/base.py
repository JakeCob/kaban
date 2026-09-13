"""Pricing-source contract.

A source knows how to fetch the current price for one product (or a batch of them)
from one upstream provider. The refresh job asks every registered source whether
it `can_handle` a query, then calls the winner. Sources with a native batch API
override `fetch_latest_batch`; the default fans out one call per query.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from tracker.db.enums import ConditionType, ProductSource


class PriceQuery(BaseModel):
    """What we want a price for.

    `hints` is an untyped bag used by adapters that need product context — a
    Chrono24 URL, a Carousell search string — populated by the refresh service
    from the product's `attributes` JSONB. Sources that don't need it ignore it.
    """

    product_source: ProductSource
    external_product_id: str | None = None
    local_product_id: UUID | None = None
    condition: ConditionType | None = None
    grader: str | None = None
    grade_value: str | None = None
    hints: dict[str, Any] = Field(default_factory=dict)


class PriceResult(BaseModel):
    """What a source returned for a query."""

    amount: Decimal
    currency: str
    condition: ConditionType | None = None
    grader: str | None = None
    grade_value: str | None = None
    raw: dict[str, Any] = {}
    source_slug: str


class PriceSource(ABC):
    """Base class for a pricing source. Subclasses must set ``slug``."""

    slug: str

    @abstractmethod
    async def fetch_latest(self, query: PriceQuery) -> PriceResult | None:
        """Fetch a single latest price. Returns None when no price is available."""

    async def fetch_latest_batch(
        self, queries: list[PriceQuery]
    ) -> list[PriceResult | None]:
        """Fetch prices for many queries. Overridden by sources with a real batch API.

        Default implementation is a serial fan-out over `fetch_latest`. Order and
        length of the returned list match the input.
        """
        return [await self.fetch_latest(q) for q in queries]

    @abstractmethod
    def can_handle(self, query: PriceQuery, product: dict[str, Any] | None = None) -> bool:
        """Return True if this source should be used for the given query.

        The optional ``product`` payload is a dict view of the product record so
        adapters that route based on product attributes (Firecrawl reading a
        `reference_url`) can inspect it. Most sources decide from the query alone.
        """
