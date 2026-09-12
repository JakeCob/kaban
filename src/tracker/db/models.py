"""SQLAlchemy 2.0 models mirroring the tables from docs/SPEC.md §5."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    func,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from tracker.db.base import Base
from tracker.db.enums import CategoryType, ConditionType, PreOrderStatus, ProductSource


def _pg_enum(python_enum: type, name: str) -> SAEnum:
    """Native Postgres enum bound to a Python Enum, using the SQL values."""
    return SAEnum(
        python_enum,
        name=name,
        native_enum=True,
        create_type=False,
        values_callable=lambda e: [m.value for m in e],
    )


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    category_type: Mapped[CategoryType] = mapped_column(
        _pg_enum(CategoryType, "category_type"), nullable=False
    )
    attribute_schema: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    modules: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Product(Base):
    __tablename__ = "products"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    category_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("categories.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    brand: Mapped[str | None] = mapped_column(Text, nullable=True)
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    srp_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    srp_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class Inventory(Base):
    __tablename__ = "inventory"
    __table_args__ = (
        CheckConstraint(
            "(product_source = 'metagross' "
            "  AND external_product_id IS NOT NULL AND local_product_id IS NULL)"
            " OR "
            "(product_source = 'local' "
            "  AND local_product_id IS NOT NULL AND external_product_id IS NULL)",
            name="product_ref_exclusive",
        ),
        CheckConstraint("quantity >= 0", name="quantity_non_negative"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    product_source: Mapped[ProductSource] = mapped_column(
        _pg_enum(ProductSource, "product_source"), nullable=False
    )
    external_product_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    local_product_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("products.id"), nullable=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    cost_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    cost_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    cost_fx_to_php: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    cost_php_snapshot: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    purchase_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_location: Mapped[str | None] = mapped_column(Text, nullable=True)
    condition: Mapped[ConditionType] = mapped_column(
        _pg_enum(ConditionType, "condition_type"),
        nullable=False,
        server_default=ConditionType.SEALED.value,
    )
    grade: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class PreOrder(Base):
    __tablename__ = "pre_orders"
    __table_args__ = (
        CheckConstraint(
            "(product_source = 'metagross' "
            "  AND external_product_id IS NOT NULL AND local_product_id IS NULL)"
            " OR "
            "(product_source = 'local' "
            "  AND local_product_id IS NOT NULL AND external_product_id IS NULL)",
            name="preorder_product_ref_exclusive",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    product_source: Mapped[ProductSource] = mapped_column(
        _pg_enum(ProductSource, "product_source"), nullable=False
    )
    external_product_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    local_product_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("products.id"), nullable=True
    )
    release_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    store: Mapped[str] = mapped_column(Text, nullable=False)
    deposit_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    deposit_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    expected_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    release_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[PreOrderStatus] = mapped_column(
        _pg_enum(PreOrderStatus, "pre_order_status"),
        nullable=False,
        server_default=PreOrderStatus.PENDING.value,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class PriceSource(Base):
    __tablename__ = "price_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default="true")


class PriceSnapshot(Base):
    __tablename__ = "price_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    product_source: Mapped[ProductSource] = mapped_column(
        _pg_enum(ProductSource, "product_source"), nullable=False
    )
    external_product_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    local_product_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("products.id"), nullable=True
    )
    source_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("price_sources.id"), nullable=False
    )
    price_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    price_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    condition: Mapped[ConditionType | None] = mapped_column(
        _pg_enum(ConditionType, "condition_type"), nullable=True
    )
    grader: Mapped[str | None] = mapped_column(Text, nullable=True)
    grade_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class FxRate(Base):
    __tablename__ = "fx_rates"
    __table_args__ = (PrimaryKeyConstraint("as_of_date", "base", "quote"),)

    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    base: Mapped[str] = mapped_column(String(3), nullable=False)
    quote: Mapped[str] = mapped_column(String(3), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default="frankfurter")


class ResaleScenario(Base):
    __tablename__ = "resale_scenarios"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    inventory_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("inventory.id", ondelete="CASCADE"),
        nullable=False,
    )
    price_snapshot_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("price_snapshots.id", ondelete="SET NULL"),
        nullable=True,
    )
    platform: Mapped[str] = mapped_column(Text, nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    gross_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    fees: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    net_php: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AllocationRule(Base):
    __tablename__ = "allocation_rules"

    release_code: Mapped[str] = mapped_column(Text, primary_key=True)
    strategy_slug: Mapped[str] = mapped_column(Text, nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    active: Mapped[bool] = mapped_column(nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AllocationOutcome(Base):
    __tablename__ = "allocation_outcomes"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    release_code: Mapped[str] = mapped_column(Text, nullable=False)
    store: Mapped[str] = mapped_column(Text, nullable=False)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    predicted_p50: Mapped[int | None] = mapped_column(Integer, nullable=True)
    predicted_p90: Mapped[int | None] = mapped_column(Integer, nullable=True)
    predicted_p10: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PlatformFee(Base):
    __tablename__ = "platform_fees"

    platform: Mapped[str] = mapped_column(Text, primary_key=True)
    fee_structure: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
