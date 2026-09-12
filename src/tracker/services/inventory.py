"""Inventory service — cost_php_snapshot computation and CRUD helpers.

The cost_php_snapshot column is a materialized view of a two-column multiplication:
  cost_php_snapshot = cost_amount * cost_fx_to_php
It exists because portfolio queries hit it constantly and we do not want to do the
multiply in SQL every time. It is computed here, on write, and never recomputed on
read — SPEC §9 says cost basis is frozen at purchase time.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import Inventory
from tracker.schemas.inventory import InventoryCreate, InventoryUpdate

_PHP_QUANT = Decimal("0.0001")


def compute_cost_php_snapshot(cost_amount: Decimal, cost_fx_to_php: Decimal) -> Decimal:
    """Return cost_amount * cost_fx_to_php quantized to the NUMERIC(18,4) column scale."""
    return (cost_amount * cost_fx_to_php).quantize(_PHP_QUANT, rounding=ROUND_HALF_UP)


async def create_inventory(session: AsyncSession, payload: InventoryCreate) -> Inventory:
    row = Inventory(
        product_source=payload.product_source,
        external_product_id=payload.external_product_id,
        local_product_id=payload.local_product_id,
        quantity=payload.quantity,
        cost_amount=payload.cost_amount,
        cost_currency=payload.cost_currency,
        cost_fx_to_php=payload.cost_fx_to_php,
        cost_php_snapshot=compute_cost_php_snapshot(
            payload.cost_amount, payload.cost_fx_to_php
        ),
        purchase_date=payload.purchase_date,
        source=payload.source,
        storage_location=payload.storage_location,
        condition=payload.condition,
        grade=payload.grade,
        notes=payload.notes,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def get_inventory(session: AsyncSession, inventory_id: Any) -> Inventory | None:
    return await session.get(Inventory, inventory_id)


async def update_inventory(
    session: AsyncSession, row: Inventory, payload: InventoryUpdate
) -> Inventory:
    data = payload.model_dump(exclude_unset=True)

    # If cost_amount or cost_fx_to_php changed, recompute the snapshot from the
    # incoming values, defaulting to the row's current value for the other side.
    if "cost_amount" in data or "cost_fx_to_php" in data:
        new_amount = data.get("cost_amount", row.cost_amount)
        new_fx = data.get("cost_fx_to_php", row.cost_fx_to_php)
        data["cost_php_snapshot"] = compute_cost_php_snapshot(new_amount, new_fx)

    for key, value in data.items():
        setattr(row, key, value)

    await session.flush()
    await session.refresh(row)
    return row


async def delete_inventory(session: AsyncSession, row: Inventory) -> None:
    await session.delete(row)
    await session.flush()


async def list_inventory(
    session: AsyncSession,
    *,
    storage_location: str | None = None,
    limit: int = 50,
) -> list[Inventory]:
    stmt = select(Inventory).order_by(Inventory.created_at.desc()).limit(limit)
    if storage_location is not None:
        stmt = stmt.where(Inventory.storage_location == storage_location)
    result = await session.execute(stmt)
    return list(result.scalars())
