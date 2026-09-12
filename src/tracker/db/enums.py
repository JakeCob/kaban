"""Python-side mirrors of the PostgreSQL enum types declared in the initial migration.

StrEnum (Python 3.11+) means each member IS a str, so it round-trips cleanly through
SQLAlchemy's native Enum type and through Pydantic's JSON serialization.
"""

from __future__ import annotations

from enum import StrEnum


class CategoryType(StrEnum):
    COLLECTIBLE = "collectible"
    ASSET = "asset"


class ProductSource(StrEnum):
    METAGROSS = "metagross"
    LOCAL = "local"


class PreOrderStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    ALLOCATED = "allocated"
    RECEIVED = "received"
    CANCELLED = "cancelled"


class ConditionType(StrEnum):
    SEALED = "SEALED"
    NM = "NM"
    LP = "LP"
    MP = "MP"
    HP = "HP"
    DMG = "DMG"
    USED = "USED"
    NEW = "NEW"
    FOR_PARTS = "FOR_PARTS"
