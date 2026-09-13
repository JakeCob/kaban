"""Allocation predict + outcome record."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import AllocationOutcome, AllocationRule
from tracker.schemas.allocation import (
    AllocationOutcomeCreate,
    AllocationPredictRequest,
    AllocationPredictResponse,
)
from tracker.strategies import registry as strategy_registry


class AllocationError(Exception):
    """No rule / strategy for the release_code."""


async def predict(
    session: AsyncSession, payload: AllocationPredictRequest
) -> AllocationPredictResponse:
    stmt = select(AllocationRule).where(
        AllocationRule.release_code == payload.release_code, AllocationRule.active.is_(True)
    )
    rule = (await session.execute(stmt)).scalar_one_or_none()
    if rule is None:
        raise AllocationError(
            f"No active allocation rule for release_code={payload.release_code!r}"
        )

    try:
        cls = strategy_registry.get(rule.strategy_slug)
    except LookupError as exc:
        raise AllocationError(str(exc)) from exc

    strategy = cls()
    if strategy.store != payload.store:
        raise AllocationError(
            f"Strategy {rule.strategy_slug!r} is bound to store {strategy.store!r}, "
            f"not {payload.store!r}"
        )
    prediction = strategy.predict(payload.inputs, rule.params or {})

    return AllocationPredictResponse(
        release_code=payload.release_code,
        store=payload.store,
        strategy_slug=rule.strategy_slug,
        **prediction.model_dump(),
    )


async def record_outcome(
    session: AsyncSession, payload: AllocationOutcomeCreate
) -> AllocationOutcome:
    row = AllocationOutcome(**payload.model_dump())
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row
