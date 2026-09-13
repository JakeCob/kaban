"""Seed allocation_rules with the first strategy binding.

Revision ID: 20260913_0004
Revises: 20260913_0003
Create Date: 2026-09-13

One row per release. Additional stores for the same release get their own
release_code (e.g. UPC_2026_11_TC for Toys Cave) or the strategy's `store`
attribute disambiguates. See docs/SPEC.md §10.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260913_0004"
down_revision: str | None = "20260913_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_RULES = [
    (
        "UPC_2026_11",
        "upc_2026_11_great_toys",
        {
            # Overrides for the strategy's defaults; empty = use defaults from code.
        },
    ),
]


def upgrade() -> None:
    table = sa.table(
        "allocation_rules",
        sa.column("release_code", sa.Text()),
        sa.column("strategy_slug", sa.Text()),
        sa.column("params", sa.Text()),
    )
    op.bulk_insert(
        table,
        [
            {"release_code": code, "strategy_slug": slug, "params": json.dumps(params)}
            for code, slug, params in _RULES
        ],
    )


def downgrade() -> None:
    op.execute("DELETE FROM allocation_rules WHERE release_code IN ('UPC_2026_11')")
