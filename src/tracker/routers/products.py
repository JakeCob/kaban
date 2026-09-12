"""/api/v1/products — CRUD for local products."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.session import get_session
from tracker.deps import require_api_key
from tracker.schemas.product import ProductCreate, ProductRead, ProductUpdate
from tracker.services import products as service

router = APIRouter(
    prefix="/products",
    tags=["products"],
    dependencies=[Depends(require_api_key)],
)


@router.post("", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
async def create(
    payload: ProductCreate,
    session: AsyncSession = Depends(get_session),
) -> ProductRead:
    row = await service.create_product(session, payload)
    await session.commit()
    return ProductRead.model_validate(row)


@router.get("/{product_id}", response_model=ProductRead)
async def read(product_id: UUID, session: AsyncSession = Depends(get_session)) -> ProductRead:
    row = await service.get_product(session, product_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "product_not_found", "message": "No product with that id."}},
        )
    return ProductRead.model_validate(row)


@router.patch("/{product_id}", response_model=ProductRead)
async def update(
    product_id: UUID,
    payload: ProductUpdate,
    session: AsyncSession = Depends(get_session),
) -> ProductRead:
    row = await service.get_product(session, product_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "product_not_found", "message": "No product with that id."}},
        )
    row = await service.update_product(session, row, payload)
    await session.commit()
    return ProductRead.model_validate(row)


@router.get("", response_model=list[ProductRead])
async def search(
    session: AsyncSession = Depends(get_session),
    category_id: int | None = Query(default=None, alias="category"),
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ProductRead]:
    rows = await service.list_products(session, category_id=category_id, q=q, limit=limit)
    return [ProductRead.model_validate(r) for r in rows]
