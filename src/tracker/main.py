"""FastAPI application entrypoint. Assembles routers under /api/v1."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI

from tracker import __version__
from tracker.routers.inventory import router as inventory_router
from tracker.routers.jobs import router as jobs_router
from tracker.routers.prices import router as prices_router
from tracker.routers.products import router as products_router
from tracker.routers.resale import router as resale_router

app = FastAPI(
    title="Portfolio Tracker API",
    version=__version__,
    docs_url="/docs",
    redoc_url=None,
    openapi_url="/api/v1/openapi.json",
)

api_v1 = APIRouter(prefix="/api/v1")


@api_v1.get("/jobs/health", tags=["jobs"])
async def health() -> dict[str, str]:
    """Liveness heartbeat. Not gated by the API key — used by Railway health checks."""
    return {"status": "ok", "version": __version__}


api_v1.include_router(products_router)
api_v1.include_router(inventory_router)
api_v1.include_router(prices_router)
api_v1.include_router(resale_router)
api_v1.include_router(jobs_router)

app.include_router(api_v1)
