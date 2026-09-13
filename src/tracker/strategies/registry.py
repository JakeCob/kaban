"""Tiny module-level registry for allocation strategies.

Concrete strategy modules `@register` themselves at import time. The registry
is populated by importing every strategy module in the package (see
`tracker.strategies` package `__init__`).
"""

from __future__ import annotations

from tracker.strategies.base import AllocationStrategy

_STRATEGIES: dict[str, type[AllocationStrategy]] = {}


def register(cls: type[AllocationStrategy]) -> type[AllocationStrategy]:
    _STRATEGIES[cls.slug] = cls
    return cls


def get(slug: str) -> type[AllocationStrategy]:
    if slug not in _STRATEGIES:
        raise LookupError(f"No strategy registered under slug {slug!r}")
    return _STRATEGIES[slug]


def known_slugs() -> list[str]:
    return sorted(_STRATEGIES)
