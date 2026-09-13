"""Great Toys allocation for the Nov 2026 UPC release.

Great Toys tiers by past purchase volume × deposit timing (research doc §6).
This implementation is a closed-form heuristic; it composes three multipliers
against `quantity_requested` and projects the mean into three quantiles so the
UI can show a "expected 3, likely 2-4" range instead of a single guess.

The three multipliers, each ∈ [0, 1]:
  - tier_multiplier    — how strong is this customer's standing at the store
  - timing_multiplier  — how early did the deposit land vs the cutoff
  - oversub_multiplier — how oversubscribed is the release overall

expected = quantity_requested × tier × timing × oversub
p50 = round(expected)
p90 = min(quantity_requested, ceil(expected × 1.30))
p10 = max(0, floor(expected × 0.60))
confidence = fraction of the four discriminators that were supplied

Params (from allocation_rules.params) can override the multipliers:
  {
    "tier_multipliers": {"VIP": 1.0, "Regular": 0.7, "New": 0.4},
    "early_deposit_days": 7,
    "timing_multipliers": {"early": 1.0, "on_time": 0.7, "late": 0.3}
  }
Missing keys fall back to the defaults below.
"""

from __future__ import annotations

import math
from typing import Any

from tracker.strategies.base import (
    AllocationInputs,
    AllocationPrediction,
    AllocationStrategy,
)
from tracker.strategies.registry import register

_DEFAULT_TIER_MULTIPLIERS = {"VIP": 1.0, "Regular": 0.7, "New": 0.4}
_DEFAULT_TIMING_MULTIPLIERS = {"early": 1.0, "on_time": 0.7, "late": 0.3}
_DEFAULT_EARLY_DEPOSIT_DAYS = 7


@register
class UPC_2026_11_GreatToys(AllocationStrategy):  # noqa: N801 — encodes release + store readably
    slug = "upc_2026_11_great_toys"
    release_code = "UPC_2026_11"
    store = "Great Toys"

    def predict(
        self, inputs: AllocationInputs, params: dict[str, Any]
    ) -> AllocationPrediction:
        tier_map = params.get("tier_multipliers", _DEFAULT_TIER_MULTIPLIERS)
        timing_map = params.get("timing_multipliers", _DEFAULT_TIMING_MULTIPLIERS)
        early_days = int(params.get("early_deposit_days", _DEFAULT_EARLY_DEPOSIT_DAYS))

        explanation: list[str] = []
        signals = 0
        total_signals = 4  # tier, timing, oversub, prior_spend

        # 1. Tier multiplier.
        tier = inputs.customer_tier or "Regular"
        tier_mult = float(tier_map.get(tier, 0.5))
        if inputs.customer_tier is not None:
            signals += 1
            explanation.append(f"customer_tier={tier!r} → ×{tier_mult:.2f}")
        else:
            explanation.append("customer_tier unknown → assumed Regular")

        # 2. Timing multiplier.
        timing_mult = float(timing_map.get("on_time", 0.7))
        timing_label = "on_time (assumed — no deposit/cutoff timestamps)"
        if inputs.deposit_timestamp and inputs.cutoff_timestamp:
            days_before = (inputs.cutoff_timestamp - inputs.deposit_timestamp).days
            if days_before >= early_days:
                timing_mult, timing_label = float(timing_map.get("early", 1.0)), "early"
            elif days_before >= 0:
                timing_mult, timing_label = float(timing_map.get("on_time", 0.7)), "on_time"
            else:
                timing_mult, timing_label = float(timing_map.get("late", 0.3)), "late"
            signals += 1
        explanation.append(f"deposit timing={timing_label} → ×{timing_mult:.2f}")

        # 3. Oversubscription penalty.
        oversub_mult = 1.0
        if inputs.known_oversubscription_ratio and inputs.known_oversubscription_ratio > 0:
            oversub_mult = 1.0 / max(1.0, inputs.known_oversubscription_ratio)
            signals += 1
            explanation.append(
                f"oversubscription×{inputs.known_oversubscription_ratio:.2f} → ×{oversub_mult:.2f}"
            )
        else:
            explanation.append("oversubscription unknown → no penalty")

        # 4. Prior-spend nudge on top of tier (unattributed bonus for whales).
        prior_bonus = 1.0
        if inputs.prior_spend_php and inputs.prior_spend_php > 0:
            signals += 1
            # +5% per PHP 50k of prior spend, capped at +25%.
            bonus = min(0.25, float(inputs.prior_spend_php) / 50_000 * 0.05)
            prior_bonus = 1.0 + bonus
            explanation.append(
                f"prior_spend_php={inputs.prior_spend_php} → ×{prior_bonus:.2f}"
            )

        expected = (
            inputs.quantity_requested
            * tier_mult
            * timing_mult
            * oversub_mult
            * prior_bonus
        )
        expected = max(0.0, min(float(inputs.quantity_requested), expected))

        p50 = _clamp(round(expected), 0, inputs.quantity_requested)
        p90 = _clamp(math.ceil(expected * 1.30), 0, inputs.quantity_requested)
        p10 = _clamp(math.floor(expected * 0.60), 0, inputs.quantity_requested)
        # Ensure the quantiles are ordered even in edge cases.
        p10 = min(p10, p50)
        p90 = max(p90, p50)

        confidence = signals / total_signals

        return AllocationPrediction(
            expected_units=round(expected, 4),
            p50_units=p50,
            p90_units=p90,
            p10_units=p10,
            confidence=round(confidence, 2),
            explanation=explanation,
        )


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))
