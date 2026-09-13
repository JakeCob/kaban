"""Allocation predict/outcome schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from tracker.strategies.base import AllocationInputs, AllocationPrediction


class AllocationPredictRequest(BaseModel):
    release_code: str
    store: str
    inputs: AllocationInputs


class AllocationPredictResponse(AllocationPrediction):
    release_code: str
    store: str
    strategy_slug: str


class AllocationOutcomeCreate(BaseModel):
    release_code: str
    store: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    predicted_p50: int | None = None
    predicted_p90: int | None = None
    predicted_p10: int | None = None
    actual_units: int = Field(ge=0)


class AllocationOutcomeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    release_code: str
    store: str
    inputs: dict[str, Any]
    predicted_p50: int | None
    predicted_p90: int | None
    predicted_p10: int | None
    actual_units: int | None
    recorded_at: datetime
