"""FastAPI dependencies: API key auth."""

from __future__ import annotations

import hmac

from fastapi import HTTPException, Security, status
from fastapi.security.api_key import APIKeyHeader

from tracker.config import get_settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(header: str | None = Security(_api_key_header)) -> None:
    """Reject any request that does not present the configured X-API-Key value.

    Uses hmac.compare_digest so a mismatch cost is constant-time — cheap defense
    against timing oracles even though this is a single-user app.
    """
    expected = get_settings().api_key
    if header is None or not hmac.compare_digest(header, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "unauthorized", "message": "Invalid or missing API key."}},
        )
