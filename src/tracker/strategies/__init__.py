"""Allocation prediction strategies — one class per (release, store) combo.

Importing this package triggers `@register` on every strategy module so the
registry is populated before any code looks a slug up. Add new strategies here
as they land.
"""

from tracker.strategies import upc_2026_11_great_toys  # noqa: F401

__all__: list[str] = []
