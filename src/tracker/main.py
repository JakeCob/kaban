"""FastAPI application entrypoint. Routers are wired in as they land in Phase 1+."""

from __future__ import annotations

from fastapi import FastAPI

from tracker import __version__

app = FastAPI(
    title="Portfolio Tracker API",
    version=__version__,
    docs_url="/docs",
    redoc_url=None,
    openapi_url="/api/v1/openapi.json",
)


@app.get("/api/v1/jobs/health", tags=["jobs"])
async def health() -> dict[str, str]:
    """Liveness heartbeat. Not gated by the API key — used by Railway health checks."""
    return {"status": "ok", "version": __version__}
