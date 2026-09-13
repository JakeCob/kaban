"""Resale calculator.

Fee model (see docs/SPEC.md §5 platform_fees):
  {
    "platform_pct": 0.1325,     # multiplicative, in gross_currency
    "payment_pct":  0.03,       # multiplicative, in gross_currency
    "listing_flat": 0,          # subtracted in gross_currency
    "shipping_flat_php": 200    # subtracted in PHP after conversion
  }

Order of operations:
  1. net_native = gross * (1 - platform_pct - payment_pct) - listing_flat
  2. net_php    = to_php(net_native, gross_currency, rate) - shipping_flat_php

Fee keys are optional; a missing key is treated as zero.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import Inventory, PlatformFee, ResaleScenario
from tracker.money.conversion import PHP, quantize_php, to_php
from tracker.money.fx import FxUnavailable, get_fx_rate
from tracker.schemas.portfolio import FxStatusPayload
from tracker.schemas.price import PriceQueryBody
from tracker.schemas.resale import (
    ResalePreviewRequest,
    ResalePreviewResponse,
    ResaleScenarioCreate,
    ResaleScenarioRead,
)
from tracker.services.prices import get_latest_snapshot


class ResaleError(Exception):
    """Signals a resale request cannot be priced (missing inventory / fee row / FX)."""


async def _get_platform_fees(session: AsyncSession, platform: str) -> dict[str, Any]:
    stmt = select(PlatformFee.fee_structure).where(PlatformFee.platform == platform)
    result = await session.execute(stmt)
    fees = result.scalar_one_or_none()
    if fees is None:
        raise ResaleError(f"No platform_fees row for {platform!r}")
    return fees


def _dec(fees: dict[str, Any], key: str) -> Decimal:
    """Fee lookup that treats missing keys and internal `_verify`/`_note` markers as zero."""
    value = fees.get(key, 0)
    if value in (None, ""):
        return Decimal(0)
    return Decimal(str(value))


def apply_fees(gross: Decimal, fees: dict[str, Any]) -> Decimal:
    """Native-currency net after platform + payment + listing_flat.

    Returned value may be negative if fees exceed the gross price; the caller
    decides how to render that.
    """
    total_pct = _dec(fees, "platform_pct") + _dec(fees, "payment_pct")
    return gross * (Decimal(1) - total_pct) - _dec(fees, "listing_flat")


async def _price_from_snapshot(
    session: AsyncSession, inv: Inventory
) -> tuple[Decimal | None, str | None, int | None]:
    """Look up the latest price snapshot for this inventory row's product+condition."""
    query = PriceQueryBody(
        product_source=inv.product_source,
        external_product_id=inv.external_product_id,
        local_product_id=inv.local_product_id,
        condition=inv.condition,
        grader=(inv.grade or {}).get("grader"),
        grade_value=(inv.grade or {}).get("grade"),
    )
    snap = await get_latest_snapshot(session, query)
    if snap is None:
        return None, None, None
    return snap.price_amount, snap.price_currency, snap.id


async def preview_resale(
    session: AsyncSession, payload: ResalePreviewRequest
) -> ResalePreviewResponse:
    inv = await session.get(Inventory, payload.inventory_id)
    if inv is None:
        raise ResaleError(f"No inventory row with id={payload.inventory_id}")

    fees = await _get_platform_fees(session, payload.platform)

    gross_amount = payload.gross_amount
    gross_currency = payload.gross_currency
    snapshot_id: int | None = None

    if gross_amount is None:
        gross_amount, gross_currency, snapshot_id = await _price_from_snapshot(session, inv)
        if gross_amount is None:
            raise ResaleError(
                "No price provided and no snapshot on record for this inventory row"
            )
    if gross_currency is None:
        raise ResaleError("gross_amount without gross_currency")

    net_native = apply_fees(gross_amount, fees)

    warnings: list[str] = []
    try:
        rate, fx_status = await get_fx_rate(session, gross_currency, PHP)
    except FxUnavailable as exc:
        raise ResaleError(str(exc)) from exc

    if fx_status.stale:
        warnings.append(
            f"FX rate for {gross_currency}->PHP is {fx_status.days_stale} day(s) stale"
        )

    net_php = to_php(net_native, gross_currency, rate)
    net_php = quantize_php(net_php - _dec(fees, "shipping_flat_php"))

    return ResalePreviewResponse(
        inventory_id=inv.id,
        platform=payload.platform,
        gross_amount=gross_amount,
        gross_currency=gross_currency,
        fees=fees,
        net_native=net_native,
        net_php=net_php,
        fx_status=FxStatusPayload(**fx_status.model_dump()),
        based_on_snapshot_id=snapshot_id,
        warnings=warnings,
    )


async def create_scenario(
    session: AsyncSession, payload: ResaleScenarioCreate
) -> ResaleScenarioRead:
    """Persist a preview. Later reads decide staleness against the current latest snapshot."""
    preview = await preview_resale(session, payload)
    row = ResaleScenario(
        inventory_id=preview.inventory_id,
        price_snapshot_id=preview.based_on_snapshot_id,
        platform=preview.platform,
        gross_amount=preview.gross_amount,
        gross_currency=preview.gross_currency,
        fees=preview.fees,
        net_php=preview.net_php,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return ResaleScenarioRead.model_validate(row)


async def _scenario_is_stale(session: AsyncSession, row: ResaleScenario) -> bool:
    if row.price_snapshot_id is None:
        return False
    inv = await session.get(Inventory, row.inventory_id)
    if inv is None:
        return False
    _, _, current_snap_id = await _price_from_snapshot(session, inv)
    return current_snap_id is not None and current_snap_id != row.price_snapshot_id


async def get_scenario(
    session: AsyncSession, scenario_id: UUID
) -> ResaleScenarioRead | None:
    row = await session.get(ResaleScenario, scenario_id)
    if row is None:
        return None
    stale = await _scenario_is_stale(session, row)
    out = ResaleScenarioRead.model_validate(row)
    out.stale = stale
    return out
