"""/api/v1/allocations — predict + record outcomes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.session import get_session
from tracker.deps import require_api_key
from tracker.schemas.allocation import (
    AllocationOutcomeCreate,
    AllocationOutcomeRead,
    AllocationPredictRequest,
    AllocationPredictResponse,
)
from tracker.services import allocations as service

router = APIRouter(
    prefix="/allocations",
    tags=["allocations"],
    dependencies=[Depends(require_api_key)],
)


@router.post("/predict", response_model=AllocationPredictResponse)
async def predict(
    payload: AllocationPredictRequest,
    session: AsyncSession = Depends(get_session),
) -> AllocationPredictResponse:
    try:
        return await service.predict(session, payload)
    except service.AllocationError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "no_strategy", "message": str(exc)}},
        ) from exc


@router.post(
    "/outcomes",
    response_model=AllocationOutcomeRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_outcome(
    payload: AllocationOutcomeCreate,
    session: AsyncSession = Depends(get_session),
) -> AllocationOutcomeRead:
    row = await service.record_outcome(session, payload)
    await session.commit()
    return AllocationOutcomeRead.model_validate(row)
