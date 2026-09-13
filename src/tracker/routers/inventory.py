"""/api/v1/inventory — CRUD for owned items."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.session import get_session
from tracker.deps import require_api_key
from tracker.schemas.inventory import InventoryCreate, InventoryRead, InventoryUpdate
from tracker.schemas.portfolio import PortfolioResponse
from tracker.services import inventory as service
from tracker.services.portfolio import compute_portfolio

router = APIRouter(
    prefix="/inventory",
    tags=["inventory"],
    dependencies=[Depends(require_api_key)],
)


@router.get("/portfolio", response_model=PortfolioResponse)
async def portfolio(session: AsyncSession = Depends(get_session)) -> PortfolioResponse:
    """Grand totals in PHP + per-category breakdown. See SPEC §9 for FX semantics."""
    return await compute_portfolio(session)


@router.post("", response_model=InventoryRead, status_code=status.HTTP_201_CREATED)
async def create(
    payload: InventoryCreate,
    session: AsyncSession = Depends(get_session),
) -> InventoryRead:
    row = await service.create_inventory(session, payload)
    await session.commit()
    return InventoryRead.model_validate(row)


@router.get("/{inventory_id}", response_model=InventoryRead)
async def read(
    inventory_id: UUID, session: AsyncSession = Depends(get_session)
) -> InventoryRead:
    row = await service.get_inventory(session, inventory_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "inventory_not_found", "message": "No inventory row with that id."}},
        )
    return InventoryRead.model_validate(row)


@router.patch("/{inventory_id}", response_model=InventoryRead)
async def update(
    inventory_id: UUID,
    payload: InventoryUpdate,
    session: AsyncSession = Depends(get_session),
) -> InventoryRead:
    row = await service.get_inventory(session, inventory_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "inventory_not_found", "message": "No inventory row with that id."}},
        )
    row = await service.update_inventory(session, row, payload)
    await session.commit()
    return InventoryRead.model_validate(row)


@router.delete("/{inventory_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete(
    inventory_id: UUID, session: AsyncSession = Depends(get_session)
) -> Response:
    row = await service.get_inventory(session, inventory_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "inventory_not_found", "message": "No inventory row with that id."}},
        )
    await service.delete_inventory(session, row)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("", response_model=list[InventoryRead])
async def search(
    session: AsyncSession = Depends(get_session),
    storage_location: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[InventoryRead]:
    rows = await service.list_inventory(
        session, storage_location=storage_location, limit=limit
    )
    return [InventoryRead.model_validate(r) for r in rows]
