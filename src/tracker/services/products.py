"""Local product service — thin CRUD wrapper over the Product model."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import Product
from tracker.schemas.product import ProductCreate, ProductUpdate


async def create_product(session: AsyncSession, payload: ProductCreate) -> Product:
    row = Product(**payload.model_dump())
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def get_product(session: AsyncSession, product_id: UUID) -> Product | None:
    return await session.get(Product, product_id)


async def update_product(
    session: AsyncSession, row: Product, payload: ProductUpdate
) -> Product:
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    await session.flush()
    await session.refresh(row)
    return row


async def list_products(
    session: AsyncSession,
    *,
    category_id: int | None = None,
    q: str | None = None,
    limit: int = 50,
) -> list[Product]:
    stmt = select(Product).order_by(Product.created_at.desc()).limit(limit)
    if category_id is not None:
        stmt = stmt.where(Product.category_id == category_id)
    if q:
        stmt = stmt.where(Product.name.ilike(f"%{q}%"))
    result = await session.execute(stmt)
    return list(result.scalars())
