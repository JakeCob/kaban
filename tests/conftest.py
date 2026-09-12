"""Shared pytest fixtures. Populated during Phase 1."""

from __future__ import annotations

import pytest


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
