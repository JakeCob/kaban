"""HTTP client for the Metagross API (see docs/METAGROSS_API_CONTRACT.md).

Only the methods used by Phase 2 are implemented: product lookup, single-product
latest price, and the batch endpoint that powers refresh jobs. Search/history/
identify get added when they are actually needed.

The batch endpoint accepts up to 500 requests per call. This client chunks longer
lists automatically and preserves input order in the returned list.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

import httpx
from pydantic import BaseModel, Field
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from tracker.config import get_settings

BATCH_MAX = 500


class MetagrossPriceRequest(BaseModel):
    """One entry in a POST /products/prices/batch request."""

    product_id: str
    condition: str | None = None
    grader: str | None = None
    grade: str | None = None


class MetagrossPriceSnapshot(BaseModel):
    """PriceSnapshot as returned by Metagross. Extra fields (raw, source-native) live in `raw`."""

    product_id: str
    source: str
    price: Decimal
    currency: str
    condition: str | None = None
    grade: dict[str, Any] | None = None
    captured_at: str
    raw: dict[str, Any] = Field(default_factory=dict)


class MetagrossPriceBatchEntry(BaseModel):
    """One entry in a POST /products/prices/batch response.

    Either `price` or `error` is set. The client keeps the raw error shape so callers
    can distinguish `no_price_available` from `product_not_found`.
    """

    product_id: str
    price: MetagrossPriceSnapshot | None = None
    error: dict[str, Any] | None = None


def _retryable_status(response: httpx.Response) -> bool:
    """5xx and 429 are worth retrying; 4xx (except 429) is a real error."""
    return response.status_code >= 500 or response.status_code == 429


class MetagrossClient:
    """Small typed wrapper around httpx.AsyncClient."""

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        settings = get_settings()
        self._base_url = (base_url or settings.metagross_base_url).rstrip("/")
        self._token = token or settings.metagross_token
        self._timeout = timeout
        self._own_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=timeout,
        )

    async def aclose(self) -> None:
        if self._own_client:
            await self._client.aclose()

    async def __aenter__(self) -> MetagrossClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
    )
    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        r = await self._client.request(method, path, **kwargs)
        if _retryable_status(r):
            r.raise_for_status()
        return r

    async def get_product(self, product_id: str) -> dict[str, Any]:
        r = await self._request("GET", f"/products/{product_id}")
        r.raise_for_status()
        return r.json()

    async def price_latest(
        self,
        product_id: str,
        *,
        condition: str | None = None,
        grader: str | None = None,
        grade: str | None = None,
    ) -> MetagrossPriceSnapshot | None:
        params: dict[str, Any] = {}
        if condition is not None:
            params["condition"] = condition
        if grader is not None:
            params["grader"] = grader
        if grade is not None:
            params["grade"] = grade
        r = await self._request(
            "GET", f"/products/{product_id}/price/latest", params=params
        )
        if r.status_code == 404:
            # 404 body distinguishes product_not_found from no_price_available.
            return None
        r.raise_for_status()
        return MetagrossPriceSnapshot.model_validate(r.json())

    async def prices_batch(
        self, requests: Sequence[MetagrossPriceRequest]
    ) -> list[MetagrossPriceBatchEntry]:
        """POST /products/prices/batch with automatic chunking at BATCH_MAX.

        Returns entries in the same order as the input.
        """
        out: list[MetagrossPriceBatchEntry] = []
        for start in range(0, len(requests), BATCH_MAX):
            chunk = requests[start : start + BATCH_MAX]
            body = {"requests": [req.model_dump(exclude_none=True) for req in chunk]}
            r = await self._request("POST", "/products/prices/batch", json=body)
            r.raise_for_status()
            payload = r.json()
            out.extend(
                MetagrossPriceBatchEntry.model_validate(entry)
                for entry in payload["results"]
            )
        return out
