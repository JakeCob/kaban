"""/api/v1/pre_orders — CRUD plus resolve → inventory."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.enums import PreOrderStatus
from tracker.db.session import get_session
from tracker.deps import require_api_key
from tracker.schemas.preorder import (
    PreOrderCreate,
    PreOrderRead,
    PreOrderResolveRequest,
    PreOrderResolveResponse,
    PreOrderUpdate,
)
from tracker.services import preorders as service

router = APIRouter(
    prefix="/pre_orders",
    tags=["pre_orders"],
    dependencies=[Depends(require_api_key)],
)


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": {"code": "preorder_not_found", "message": "No pre-order with that id."}},
    )


@router.post("", response_model=PreOrderRead, status_code=status.HTTP_201_CREATED)
async def create(
    payload: PreOrderCreate,
    session: AsyncSession = Depends(get_session),
) -> PreOrderRead:
    row = await service.create_preorder(session, payload)
    await session.commit()
    return PreOrderRead.model_validate(row)


@router.get("/{preorder_id}", response_model=PreOrderRead)
async def read(preorder_id: UUID, session: AsyncSession = Depends(get_session)) -> PreOrderRead:
    row = await service.get_preorder(session, preorder_id)
    if row is None:
        raise _not_found()
    return PreOrderRead.model_validate(row)


@router.patch("/{preorder_id}", response_model=PreOrderRead)
async def update(
    preorder_id: UUID,
    payload: PreOrderUpdate,
    session: AsyncSession = Depends(get_session),
) -> PreOrderRead:
    row = await service.get_preorder(session, preorder_id)
    if row is None:
        raise _not_found()
    row = await service.update_preorder(session, row, payload)
    await session.commit()
    return PreOrderRead.model_validate(row)


@router.delete(
    "/{preorder_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete(preorder_id: UUID, session: AsyncSession = Depends(get_session)) -> Response:
    row = await service.get_preorder(session, preorder_id)
    if row is None:
        raise _not_found()
    await service.delete_preorder(session, row)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("", response_model=list[PreOrderRead])
async def search(
    session: AsyncSession = Depends(get_session),
    status_: PreOrderStatus | None = Query(default=None, alias="status"),
    release_date_before: date | None = None,
    release_date_after: date | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[PreOrderRead]:
    rows = await service.list_preorders(
        session,
        status=status_,
        release_date_before=release_date_before,
        release_date_after=release_date_after,
        limit=limit,
    )
    return [PreOrderRead.model_validate(r) for r in rows]


@router.post(
    "/{preorder_id}/resolve",
    response_model=PreOrderResolveResponse,
    status_code=status.HTTP_200_OK,
)
async def resolve(
    preorder_id: UUID,
    payload: PreOrderResolveRequest,
    session: AsyncSession = Depends(get_session),
) -> PreOrderResolveResponse:
    row = await service.get_preorder(session, preorder_id)
    if row is None:
        raise _not_found()
    try:
        row, inventory_ids = await service.resolve_preorder(session, row, payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": {"code": "invalid_resolve", "message": str(exc)}},
        ) from exc
    await session.commit()
    return PreOrderResolveResponse(
        pre_order=PreOrderRead.model_validate(row),
        inventory_ids=inventory_ids,
    )
