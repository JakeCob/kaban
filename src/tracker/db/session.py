"""Async SQLAlchemy engine, session factory, and FastAPI dependency.

Engine and sessionmaker are constructed lazily so importing this module does not
require psycopg or a valid DATABASE_URL — tests that only touch schemas or pure
services can import from tracker.db.* without booting the DB layer.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tracker.config import get_settings


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(settings.database_url, future=True, pool_pre_ping=True)


@lru_cache(maxsize=1)
def _get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False, autoflush=False)


class _SessionLocalProxy:
    """Callable proxy so `SessionLocal()` still works and the engine builds on first use."""

    def __call__(self) -> AsyncSession:
        return _get_sessionmaker()()


SessionLocal = _SessionLocalProxy()


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a scoped async session."""
    async with _get_sessionmaker()() as session:
        yield session


def reset_engine_cache() -> None:
    """Testing hook: forget the cached engine so a new DATABASE_URL takes effect."""
    get_engine.cache_clear()
    _get_sessionmaker.cache_clear()
