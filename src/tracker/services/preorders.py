"""Pre-order service — CRUD and the resolve → inventory flow.

Resolve is the interesting bit: setting actual_units=N and (optionally) creating N
inventory rows must be atomic. If any inventory insert fails, the pre-order
mutation is rolled back too — the router-level `session.commit()` is the barrier.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.enums import PreOrderStatus
from tracker.db.models import Inventory, PreOrder
from tracker.schemas.preorder import (
    PreOrderCreate,
    PreOrderResolveRequest,
    PreOrderUpdate,
)

_PHP_QUANT = Decimal("0.0001")


async def create_preorder(session: AsyncSession, payload: PreOrderCreate) -> PreOrder:
    row = PreOrder(**payload.model_dump())
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def get_preorder(session: AsyncSession, preorder_id: UUID) -> PreOrder | None:
    return await session.get(PreOrder, preorder_id)


async def update_preorder(
    session: AsyncSession, row: PreOrder, payload: PreOrderUpdate
) -> PreOrder:
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    await session.flush()
    await session.refresh(row)
    return row


async def delete_preorder(session: AsyncSession, row: PreOrder) -> None:
    await session.delete(row)
    await session.flush()


async def list_preorders(
    session: AsyncSession,
    *,
    status: PreOrderStatus | None = None,
    release_date_before: date | None = None,
    release_date_after: date | None = None,
    limit: int = 50,
) -> list[PreOrder]:
    stmt = select(PreOrder).order_by(PreOrder.created_at.desc()).limit(limit)
    if status is not None:
        stmt = stmt.where(PreOrder.status == status)
    if release_date_before is not None:
        stmt = stmt.where(PreOrder.release_date < release_date_before)
    if release_date_after is not None:
        stmt = stmt.where(PreOrder.release_date > release_date_after)
    result = await session.execute(stmt)
    return list(result.scalars())


async def resolve_preorder(
    session: AsyncSession, row: PreOrder, payload: PreOrderResolveRequest
) -> tuple[PreOrder, list[UUID]]:
    """Set actual_units, update status, and optionally create inventory rows.

    Atomic: any inventory insert failure rolls back the whole thing, including
    the pre-order mutation, because we haven't committed yet.
    """
    row.actual_units = payload.actual_units

    inventory_ids: list[UUID] = []
    if payload.receive_now:
        _require_cost_fields(payload)
        # Type checker: _require_cost_fields ensured these are not None.
        assert payload.cost_per_unit is not None
        assert payload.cost_currency is not None
        assert payload.cost_fx_to_php is not None

        cost_php_snapshot = (payload.cost_per_unit * payload.cost_fx_to_php).quantize(
            _PHP_QUANT, rounding=ROUND_HALF_UP
        )
        purchase_date = payload.purchase_date or date.today()

        common: dict[str, Any] = {
            "product_source": row.product_source,
            "external_product_id": row.external_product_id,
            "local_product_id": row.local_product_id,
            "quantity": 1,
            "cost_amount": payload.cost_per_unit,
            "cost_currency": payload.cost_currency,
            "cost_fx_to_php": payload.cost_fx_to_php,
            "cost_php_snapshot": cost_php_snapshot,
            "purchase_date": purchase_date,
            "source": row.store,
            "storage_location": payload.storage_location,
            "condition": payload.condition,
            "notes": payload.notes,
        }
        for _ in range(payload.actual_units):
            inv = Inventory(**common)
            session.add(inv)
            await session.flush()
            inventory_ids.append(inv.id)

        row.status = PreOrderStatus.RECEIVED
    else:
        row.status = PreOrderStatus.ALLOCATED

    await session.flush()
    await session.refresh(row)
    return row, inventory_ids


def _require_cost_fields(payload: PreOrderResolveRequest) -> None:
    missing = [
        name
        for name, val in (
            ("cost_per_unit", payload.cost_per_unit),
            ("cost_currency", payload.cost_currency),
            ("cost_fx_to_php", payload.cost_fx_to_php),
        )
        if val is None
    ]
    if missing:
        raise ValueError(
            "receive_now=True requires cost fields, missing: " + ", ".join(missing)
        )
