"""Frankfurter (frankfurter.dev) FX rates client.

Public API, no key required. Rates are ECB-backed and updated once per business day.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any

import httpx
from pydantic import BaseModel
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

DEFAULT_BASE_URL = "https://api.frankfurter.dev/v1"


class FrankfurterLatest(BaseModel):
    amount: Decimal
    base: str
    date: date
    rates: dict[str, Decimal]


class FrankfurterClient:
    """Small typed wrapper. Frankfurter is free and cheap; the client just needs to
    stay out of the way when it works and fail cleanly when it doesn't."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        client: httpx.AsyncClient | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._own_client = client is None
        self._client = client or httpx.AsyncClient(base_url=self._base_url, timeout=timeout)

    async def __aenter__(self) -> FrankfurterClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._own_client:
            await self._client.aclose()

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
    )
    async def _get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        r = await self._client.get(path, params=params or {})
        if r.status_code >= 500 or r.status_code == 429:
            r.raise_for_status()
        return r

    async def latest_rates(
        self, base: str, symbols: Sequence[str]
    ) -> FrankfurterLatest:
        r = await self._get("/latest", params={"base": base, "symbols": ",".join(symbols)})
        r.raise_for_status()
        return FrankfurterLatest.model_validate(r.json())
