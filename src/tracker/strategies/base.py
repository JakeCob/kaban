"""Allocation prediction contract.

Each concrete strategy is bound to one (release_code, store) pair and turns a bag
of inputs — customer tier, deposit timing, oversubscription ratio — into a
distribution over "how many units will I actually get." SPEC §10 documents the
approach; the ML layer is deliberately out of scope for v1 (closed-form heuristics
first, fit models later once we have real allocation_outcomes data to learn from).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AllocationInputs(BaseModel):
    model_config = ConfigDict(extra="ignore")

    quantity_requested: int = Field(gt=0)
    customer_tier: str | None = None
    prior_spend_php: Decimal | None = None
    deposit_amount_php: Decimal | None = None
    deposit_timestamp: datetime | None = None
    cutoff_timestamp: datetime | None = None
    known_oversubscription_ratio: float | None = None
    store_specific: dict[str, Any] = Field(default_factory=dict)


class AllocationPrediction(BaseModel):
    """A distribution summarised as three quantiles + a confidence.

    All unit counts are non-negative and never exceed quantity_requested; the
    caller can trust them as-is for planning.
    """

    expected_units: float
    p50_units: int = Field(ge=0)
    p90_units: int = Field(ge=0)
    p10_units: int = Field(ge=0)
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: list[str] = []


class AllocationStrategy(ABC):
    """Base class for a per-release, per-store predictor. Subclasses declare slug +
    release_code + store; the registry looks them up by slug."""

    slug: str
    release_code: str
    store: str

    @abstractmethod
    def predict(
        self, inputs: AllocationInputs, params: dict[str, Any]
    ) -> AllocationPrediction:
        """Return an AllocationPrediction. `params` comes from allocation_rules.params
        so per-release tuning (e.g. tier caps) lives in DB, not code."""
