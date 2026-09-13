"""/api/v1/resale — preview and persist "if I sold this today" scenarios."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.session import get_session
from tracker.deps import require_api_key
from tracker.schemas.resale import (
    ResalePreviewRequest,
    ResalePreviewResponse,
    ResaleScenarioCreate,
    ResaleScenarioRead,
)
from tracker.services.resale import ResaleError, create_scenario, preview_resale

router = APIRouter(
    prefix="/resale",
    tags=["resale"],
    dependencies=[Depends(require_api_key)],
)


def _error_response(exc: ResaleError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"error": {"code": "resale_error", "message": str(exc)}},
    )


@router.post("/preview", response_model=ResalePreviewResponse)
async def preview(
    payload: ResalePreviewRequest,
    session: AsyncSession = Depends(get_session),
) -> ResalePreviewResponse:
    try:
        return await preview_resale(session, payload)
    except ResaleError as exc:
        raise _error_response(exc) from exc


@router.post(
    "/scenarios",
    response_model=ResaleScenarioRead,
    status_code=status.HTTP_201_CREATED,
)
async def create(
    payload: ResaleScenarioCreate,
    session: AsyncSession = Depends(get_session),
) -> ResaleScenarioRead:
    try:
        result = await create_scenario(session, payload)
    except ResaleError as exc:
        raise _error_response(exc) from exc
    await session.commit()
    return result
