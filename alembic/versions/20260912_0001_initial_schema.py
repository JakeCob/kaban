"""Initial schema — all tables, enums, indexes, and the latest_prices materialized view.

Revision ID: 20260912_0001
Revises:
Create Date: 2026-09-12

Mirrors docs/SPEC.md §5 with the v1.1 revisions:
  - grader / grade_value as scalar columns on price_snapshots
  - preorder_product_ref_exclusive (both sides asserted)
  - resale_scenarios.price_snapshot_id FK
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260912_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CATEGORY_TYPE = postgresql.ENUM("collectible", "asset", name="category_type", create_type=False)
PRODUCT_SOURCE = postgresql.ENUM("metagross", "local", name="product_source", create_type=False)
PRE_ORDER_STATUS = postgresql.ENUM(
    "pending", "paid", "allocated", "received", "cancelled",
    name="pre_order_status", create_type=False,
)
CONDITION_TYPE = postgresql.ENUM(
    "SEALED", "NM", "LP", "MP", "HP", "DMG", "USED", "NEW", "FOR_PARTS",
    name="condition_type", create_type=False,
)


def upgrade() -> None:
    # Enums first — every table below references at least one.
    op.execute("CREATE TYPE category_type AS ENUM ('collectible', 'asset')")
    op.execute("CREATE TYPE product_source AS ENUM ('metagross', 'local')")
    op.execute(
        "CREATE TYPE pre_order_status AS ENUM "
        "('pending', 'paid', 'allocated', 'received', 'cancelled')"
    )
    op.execute(
        "CREATE TYPE condition_type AS ENUM "
        "('SEALED', 'NM', 'LP', 'MP', 'HP', 'DMG', 'USED', 'NEW', 'FOR_PARTS')"
    )

    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("category_type", CATEGORY_TYPE, nullable=False),
        sa.Column(
            "attribute_schema", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("modules", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "products",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "category_id",
            sa.Integer(),
            sa.ForeignKey("categories.id"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("brand", sa.Text(), nullable=True),
        sa.Column(
            "attributes", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("srp_amount", sa.Numeric(18, 4), nullable=True),
        sa.Column("srp_currency", sa.String(3), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("idx_products_category", "products", ["category_id"])
    op.execute("CREATE INDEX idx_products_attributes ON products USING GIN (attributes)")

    op.create_table(
        "inventory",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("product_source", PRODUCT_SOURCE, nullable=False),
        sa.Column("external_product_id", sa.Text(), nullable=True),
        sa.Column(
            "local_product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id"),
            nullable=True,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("cost_amount", sa.Numeric(18, 4), nullable=False),
        sa.Column("cost_currency", sa.String(3), nullable=False),
        sa.Column("cost_fx_to_php", sa.Numeric(18, 8), nullable=False),
        sa.Column("cost_php_snapshot", sa.Numeric(18, 4), nullable=False),
        sa.Column("purchase_date", sa.Date(), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("storage_location", sa.Text(), nullable=True),
        sa.Column(
            "condition", CONDITION_TYPE, nullable=False, server_default=sa.text("'SEALED'")
        ),
        sa.Column("grade", postgresql.JSONB(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("quantity >= 0", name="ck_inventory_quantity_non_negative"),
        sa.CheckConstraint(
            "(product_source = 'metagross' "
            "  AND external_product_id IS NOT NULL AND local_product_id IS NULL)"
            " OR "
            "(product_source = 'local' "
            "  AND local_product_id IS NOT NULL AND external_product_id IS NULL)",
            name="ck_inventory_product_ref_exclusive",
        ),
    )
    op.create_index("idx_inventory_source", "inventory", ["product_source"])
    op.execute(
        "CREATE INDEX idx_inventory_external ON inventory(external_product_id) "
        "WHERE external_product_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX idx_inventory_local ON inventory(local_product_id) "
        "WHERE local_product_id IS NOT NULL"
    )
    op.create_index("idx_inventory_storage", "inventory", ["storage_location"])

    op.create_table(
        "pre_orders",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("product_source", PRODUCT_SOURCE, nullable=False),
        sa.Column("external_product_id", sa.Text(), nullable=True),
        sa.Column(
            "local_product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id"),
            nullable=True,
        ),
        sa.Column("release_code", sa.Text(), nullable=True),
        sa.Column("store", sa.Text(), nullable=False),
        sa.Column("deposit_amount", sa.Numeric(18, 4), nullable=True),
        sa.Column("deposit_currency", sa.String(3), nullable=True),
        sa.Column("expected_units", sa.Integer(), nullable=True),
        sa.Column("actual_units", sa.Integer(), nullable=True),
        sa.Column("release_date", sa.Date(), nullable=True),
        sa.Column(
            "status", PRE_ORDER_STATUS, nullable=False, server_default=sa.text("'pending'")
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "(product_source = 'metagross' "
            "  AND external_product_id IS NOT NULL AND local_product_id IS NULL)"
            " OR "
            "(product_source = 'local' "
            "  AND local_product_id IS NOT NULL AND external_product_id IS NULL)",
            name="ck_pre_orders_preorder_product_ref_exclusive",
        ),
    )
    op.create_index("idx_preorders_status", "pre_orders", ["status"])
    op.create_index("idx_preorders_release_date", "pre_orders", ["release_date"])
    op.create_index("idx_preorders_release_code", "pre_orders", ["release_code"])

    op.create_table(
        "price_sources",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )

    op.create_table(
        "price_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("product_source", PRODUCT_SOURCE, nullable=False),
        sa.Column("external_product_id", sa.Text(), nullable=True),
        sa.Column(
            "local_product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id"),
            nullable=True,
        ),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("price_sources.id"),
            nullable=False,
        ),
        sa.Column("price_amount", sa.Numeric(18, 4), nullable=False),
        sa.Column("price_currency", sa.String(3), nullable=False),
        sa.Column("condition", CONDITION_TYPE, nullable=True),
        sa.Column("grader", sa.Text(), nullable=True),
        sa.Column("grade_value", sa.Text(), nullable=True),
        sa.Column("raw", postgresql.JSONB(), nullable=True),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.execute(
        "CREATE INDEX idx_snapshots_product_time "
        "ON price_snapshots(external_product_id, captured_at DESC) "
        "WHERE external_product_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX idx_snapshots_local_time "
        "ON price_snapshots(local_product_id, captured_at DESC) "
        "WHERE local_product_id IS NOT NULL"
    )

    op.execute(
        """
        CREATE MATERIALIZED VIEW latest_prices AS
        SELECT DISTINCT ON (
            product_source, external_product_id, local_product_id,
            condition, grader, grade_value
        )
          product_source, external_product_id, local_product_id,
          condition, grader, grade_value,
          price_amount, price_currency, source_id, captured_at,
          id AS snapshot_id
        FROM price_snapshots
        ORDER BY
          product_source, external_product_id, local_product_id,
          condition, grader, grade_value, captured_at DESC;
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX idx_latest_prices_unique ON latest_prices (
          product_source,
          COALESCE(external_product_id, ''),
          COALESCE(local_product_id::text, ''),
          COALESCE(condition::text, ''),
          COALESCE(grader, ''),
          COALESCE(grade_value, '')
        );
        """
    )

    op.create_table(
        "fx_rates",
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("base", sa.String(3), nullable=False),
        sa.Column("quote", sa.String(3), nullable=False),
        sa.Column("rate", sa.Numeric(18, 8), nullable=False),
        sa.Column("source", sa.Text(), nullable=False, server_default=sa.text("'frankfurter'")),
        sa.PrimaryKeyConstraint("as_of_date", "base", "quote", name="pk_fx_rates"),
    )

    op.create_table(
        "resale_scenarios",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "inventory_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("inventory.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "price_snapshot_id",
            sa.BigInteger(),
            sa.ForeignKey("price_snapshots.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("gross_amount", sa.Numeric(18, 4), nullable=False),
        sa.Column("gross_currency", sa.String(3), nullable=False),
        sa.Column("fees", postgresql.JSONB(), nullable=False),
        sa.Column("net_php", sa.Numeric(18, 4), nullable=False),
        sa.Column(
            "calculated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("idx_resale_scenarios_inventory", "resale_scenarios", ["inventory_id"])
    op.execute(
        "CREATE INDEX idx_resale_scenarios_snapshot ON resale_scenarios(price_snapshot_id) "
        "WHERE price_snapshot_id IS NOT NULL"
    )

    op.create_table(
        "allocation_rules",
        sa.Column("release_code", sa.Text(), primary_key=True),
        sa.Column("strategy_slug", sa.Text(), nullable=False),
        sa.Column("params", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "allocation_outcomes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("release_code", sa.Text(), nullable=False),
        sa.Column("store", sa.Text(), nullable=False),
        sa.Column("inputs", postgresql.JSONB(), nullable=False),
        sa.Column("predicted_p50", sa.Integer(), nullable=True),
        sa.Column("predicted_p90", sa.Integer(), nullable=True),
        sa.Column("predicted_p10", sa.Integer(), nullable=True),
        sa.Column("actual_units", sa.Integer(), nullable=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "platform_fees",
        sa.Column("platform", sa.Text(), primary_key=True),
        sa.Column("fee_structure", postgresql.JSONB(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS latest_prices")
    op.drop_table("platform_fees")
    op.drop_table("allocation_outcomes")
    op.drop_table("allocation_rules")
    op.drop_table("resale_scenarios")
    op.drop_table("fx_rates")
    op.drop_table("price_snapshots")
    op.drop_table("price_sources")
    op.drop_table("pre_orders")
    op.drop_table("inventory")
    op.drop_table("products")
    op.drop_table("categories")
    op.execute("DROP TYPE IF EXISTS condition_type")
    op.execute("DROP TYPE IF EXISTS pre_order_status")
    op.execute("DROP TYPE IF EXISTS product_source")
    op.execute("DROP TYPE IF EXISTS category_type")
