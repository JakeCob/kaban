"""Shared Apify machinery — a thin async wrapper + a template base class for
Apify-backed pricing sources.

Every Apify source follows the same shape:
  1. Read the search URL / query string from `query.hints`.
  2. Call one Apify actor with that input.
  3. Extract a list of prices from the actor's dataset.
  4. Reduce to a single representative price (median by default).

The base class does everything except step 1's input shape and step 3's field
names, which each concrete source declares. Semaphore-controlled fan-out lives
here too so 20 watches don't spawn 20 concurrent actor runs.
"""

from __future__ import annotations

import asyncio
import statistics
from decimal import Decimal
from typing import Any

from apify_client import ApifyClientAsync
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from tracker.config import get_settings
from tracker.sources.base import PriceQuery, PriceResult, PriceSource

DEFAULT_CONCURRENCY = 5


class ApifyRunError(Exception):
    """The actor call itself failed (network, auth, actor code) — retryable
    externally, but never raised across a batch."""


class ApifyClient:
    """Async wrapper around apify-client with typed methods and a semaphore."""

    def __init__(
        self,
        token: str | None = None,
        client: ApifyClientAsync | None = None,
        concurrency: int = DEFAULT_CONCURRENCY,
    ) -> None:
        settings = get_settings()
        self._token = token or settings.apify_token
        self._client = client or ApifyClientAsync(token=self._token)
        self._semaphore = asyncio.Semaphore(concurrency)

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
        retry=retry_if_exception_type((ApifyRunError,)),
    )
    async def run_actor(
        self, actor_id: str, run_input: dict[str, Any], timeout_secs: int | None = 300
    ) -> list[dict[str, Any]]:
        """Run an actor synchronously and return the dataset items.

        `actor.call()` blocks until the run finishes. Timeout controls the WHOLE
        run — for the 10-minute pg_cron cap, keep this well under it.
        """
        async with self._semaphore:
            try:
                run = await self._client.actor(actor_id).call(
                    run_input=run_input, timeout_secs=timeout_secs
                )
            except Exception as exc:  # apify-client raises many concrete types
                raise ApifyRunError(f"actor {actor_id} failed: {exc}") from exc
            if run is None:
                raise ApifyRunError(f"actor {actor_id} returned no run")
            dataset_id = run.get("defaultDatasetId")
            if not dataset_id:
                return []
            items_page = await self._client.dataset(dataset_id).list_items()
            return list(items_page.items)


class _BaseApifySource(PriceSource):
    """Template method base. Subclasses declare actor + field mappings + can_handle."""

    slug: str
    actor_id: str
    default_currency: str = "USD"
    price_field: str = "price"
    currency_field: str | None = None
    concurrency: int = DEFAULT_CONCURRENCY

    def __init__(self, client: ApifyClient) -> None:
        self._client = client

    # --- subclass hooks ---------------------------------------------------

    def _build_input(self, query: PriceQuery) -> dict[str, Any] | None:
        """Turn a query into actor input. Returns None if we can't route it.

        Default: read `query.hints[<slug>_url]` or `query.hints[<slug>_search]`
        and pass it as a startUrls / search input. Sources with more exotic
        shapes override this.
        """
        hints = query.hints or {}
        url = hints.get(f"{self.slug}_url") or hints.get("reference_url")
        if url:
            return {"startUrls": [{"url": url}]}
        search = hints.get(f"{self.slug}_search")
        if search:
            return {"searchQuery": search}
        return None

    # --- shared ----------------------------------------------------------

    async def fetch_latest(self, query: PriceQuery) -> PriceResult | None:
        run_input = self._build_input(query)
        if run_input is None:
            return None
        try:
            items = await self._client.run_actor(self.actor_id, run_input)
        except ApifyRunError:
            return None
        return self._items_to_result(items)

    async def fetch_latest_batch(
        self, queries: list[PriceQuery]
    ) -> list[PriceResult | None]:
        # Semaphore lives on the ApifyClient, so gather is safe.
        return await asyncio.gather(*(self.fetch_latest(q) for q in queries))

    def can_handle(
        self, query: PriceQuery, product: dict[str, Any] | None = None  # noqa: ARG002
    ) -> bool:
        # Default: only pick queries where the caller supplied a matching hint.
        return self._build_input(query) is not None

    # --- extraction ------------------------------------------------------

    def _items_to_result(self, items: list[dict[str, Any]]) -> PriceResult | None:
        prices = [self._price_of(i) for i in items]
        prices = [p for p in prices if p is not None]
        if not prices:
            return None
        median = statistics.median(prices)
        currency = self._currency_of(items) or self.default_currency
        return PriceResult(
            amount=Decimal(str(median)),
            currency=currency,
            source_slug=self.slug,
            raw={"sample_size": len(prices)},
        )

    def _price_of(self, item: dict[str, Any]) -> Decimal | None:
        value = item.get(self.price_field)
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except (ValueError, ArithmeticError):
            return None

    def _currency_of(self, items: list[dict[str, Any]]) -> str | None:
        if not self.currency_field:
            return None
        for item in items:
            val = item.get(self.currency_field)
            if val:
                return str(val)
        return None
