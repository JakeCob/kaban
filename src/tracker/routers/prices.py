"""/api/v1/prices — latest lookups, history, manual entry, and refresh."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.enums import ConditionType, ProductSource
from tracker.db.session import get_session
from tracker.deps import require_api_key
from tracker.schemas.price import (
    PriceHistoryResponse,
    PriceManualCreate,
    PriceQueryBody,
    PriceSnapshotRead,
)
from tracker.services import prices as service
from tracker.services.refresh import refresh_price_for_query
from tracker.sources.registry import SourceRegistry, get_source_registry

router = APIRouter(
    prefix="/prices",
    tags=["prices"],
    dependencies=[Depends(require_api_key)],
)


def _build_query(
    product_source: ProductSource,
    external_product_id: str | None,
    local_product_id: UUID | None,
    condition: ConditionType | None,
    grader: str | None,
    grade_value: str | None,
) -> PriceQueryBody:
    try:
        return PriceQueryBody(
            product_source=product_source,
            external_product_id=external_product_id,
            local_product_id=local_product_id,
            condition=condition,
            grader=grader,
            grade_value=grade_value,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": {"code": "invalid_query", "message": str(exc)}},
        ) from exc


@router.get("/latest", response_model=PriceSnapshotRead)
async def latest(
    product_source: ProductSource = Query(...),
    external_product_id: str | None = None,
    local_product_id: UUID | None = None,
    condition: ConditionType | None = None,
    grader: str | None = None,
    grade_value: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> PriceSnapshotRead:
    query = _build_query(
        product_source, external_product_id, local_product_id, condition, grader, grade_value
    )
    row = await service.get_latest_snapshot(session, query)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "no_price_available", "message": "No snapshot yet."}},
        )
    return PriceSnapshotRead.model_validate(row)


@router.get("/history", response_model=PriceHistoryResponse)
async def history(
    product_source: ProductSource = Query(...),
    external_product_id: str | None = None,
    local_product_id: UUID | None = None,
    condition: ConditionType | None = None,
    grader: str | None = None,
    grade_value: str | None = None,
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = None,
    session: AsyncSession = Depends(get_session),
) -> PriceHistoryResponse:
    query = _build_query(
        product_source, external_product_id, local_product_id, condition, grader, grade_value
    )
    return await service.get_price_history(session, query, from_date=from_, to_date=to)


@router.post("/manual", response_model=PriceSnapshotRead, status_code=status.HTTP_201_CREATED)
async def manual(
    payload: PriceManualCreate,
    session: AsyncSession = Depends(get_session),
) -> PriceSnapshotRead:
    snap = await service.insert_manual_snapshot(session, payload)
    await session.commit()
    return PriceSnapshotRead.model_validate(snap)


@router.post("/refresh", response_model=PriceSnapshotRead, status_code=status.HTTP_201_CREATED)
async def refresh(
    payload: PriceQueryBody,
    session: AsyncSession = Depends(get_session),
    registry: SourceRegistry = Depends(get_source_registry),
) -> PriceSnapshotRead:
    snap = await refresh_price_for_query(session, registry, payload)
    if snap is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "no_price_available",
                    "message": "Source could not price this query.",
                }
            },
        )
    await session.commit()
    return PriceSnapshotRead.model_validate(snap)
