"""Seed reference data — categories, price_sources, platform_fees.

Revision ID: 20260912_0002
Revises: 20260912_0001
Create Date: 2026-09-12

Platform fee rates for Carousell PH need re-verification before v1 (SPEC §18).
The seed value below is a placeholder — a comment on the row flags it.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260912_0002"
down_revision: str | None = "20260912_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CATEGORIES = [
    ("tcg_sealed", "TCG Sealed", "collectible",
     {"pre_orders": True, "allocations": True, "resale": True, "high_freq_pricing": True}),
    ("tcg_single", "TCG Single", "collectible",
     {"resale": True, "high_freq_pricing": True}),
    ("watch", "Watch", "collectible",
     {"resale": True, "med_freq_pricing": True}),
    ("gadget", "Gadget", "collectible",
     {"resale": True, "med_freq_pricing": True}),
    ("sneaker", "Sneaker", "collectible",
     {"pre_orders": True, "resale": True, "med_freq_pricing": True}),
    ("car", "Car", "asset",
     {"maintenance": True, "low_freq_revaluation": True}),
    ("property", "Property", "asset",
     {"maintenance": True, "low_freq_revaluation": True}),
    ("generic", "Generic", "collectible",
     {"resale": True}),
]

PRICE_SOURCES = [
    ("metagross", "Metagross", "api"),
    ("apify_chrono24", "Apify — Chrono24", "scrape"),
    ("apify_carousell_ph", "Apify — Carousell PH", "scrape"),
    ("apify_shopee_ph", "Apify — Shopee PH", "scrape"),
    ("apify_lamudi", "Apify — Lamudi", "scrape"),
    ("apify_philkotse", "Apify — Philkotse", "scrape"),
    ("firecrawl", "Firecrawl", "firecrawl"),
    ("manual", "Manual entry", "manual"),
]

# Rates as of research §2. Carousell PH deliberately flagged for re-verification (SPEC §18).
PLATFORM_FEES = [
    ("ebay", {"platform_pct": 0.1325, "payment_pct": 0.03, "listing_flat": 0}),
    ("tcgplayer", {"platform_pct": 0.1025, "payment_pct": 0.0, "listing_flat": 0}),
    ("shopee_ph", {"platform_pct": 0.0524, "payment_pct": 0.02, "listing_flat": 0}),
    # placeholder — verify current Carousell PH fee schedule during Phase 1
    ("carousell_ph", {"platform_pct": 0.0, "payment_pct": 0.0, "listing_flat": 0,
                      "_verify": "SPEC §18"}),
    ("chrono24", {"platform_pct": 0.065, "payment_pct": 0.0, "listing_flat": 0}),
    ("lamudi", {"platform_pct": 0.0, "payment_pct": 0.0, "listing_flat": 0,
                "_note": "agent fees vary; per-listing edit expected"}),
]


def upgrade() -> None:
    categories_table = sa.table(
        "categories",
        sa.column("slug", sa.Text()),
        sa.column("name", sa.Text()),
        sa.column("category_type", sa.Text()),
        sa.column("modules", sa.Text()),
    )
    op.bulk_insert(
        categories_table,
        [
            {"slug": s, "name": n, "category_type": t, "modules": json.dumps(m)}
            for s, n, t, m in CATEGORIES
        ],
    )

    price_sources_table = sa.table(
        "price_sources",
        sa.column("slug", sa.Text()),
        sa.column("name", sa.Text()),
        sa.column("kind", sa.Text()),
    )
    op.bulk_insert(
        price_sources_table,
        [{"slug": s, "name": n, "kind": k} for s, n, k in PRICE_SOURCES],
    )

    platform_fees_table = sa.table(
        "platform_fees",
        sa.column("platform", sa.Text()),
        sa.column("fee_structure", sa.Text()),
    )
    op.bulk_insert(
        platform_fees_table,
        [{"platform": p, "fee_structure": json.dumps(f)} for p, f in PLATFORM_FEES],
    )


def downgrade() -> None:
    op.execute("DELETE FROM platform_fees")
    op.execute("DELETE FROM price_sources")
    op.execute("DELETE FROM categories")
