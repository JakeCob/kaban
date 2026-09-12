"""Shared pytest fixtures.

Integration tests spin up a real Postgres via testcontainers so the check constraints
and the materialized-view unique index (which are the whole point of a schema test)
are actually exercised. Tests are skipped automatically if Docker is unavailable.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator, Generator

import pytest
import pytest_asyncio

try:
    # testcontainers 4.x moved this into the .community namespace but keeps a
    # deprecation shim at the old path; either works.
    from testcontainers.postgres import PostgresContainer  # type: ignore[import-not-found]

    _TESTCONTAINERS_AVAILABLE = True
except ImportError:  # pragma: no cover — dev extra not installed
    _TESTCONTAINERS_AVAILABLE = False


requires_docker = pytest.mark.skipif(
    not _TESTCONTAINERS_AVAILABLE, reason="testcontainers not available"
)


@pytest.fixture(scope="session")
def postgres_url() -> Generator[str, None, None]:
    """Boot a Postgres container for the whole test session.

    Yields a psycopg-compatible URL. Skips if Docker isn't reachable.
    """
    if not _TESTCONTAINERS_AVAILABLE:
        pytest.skip("testcontainers not available")

    try:
        with PostgresContainer("postgres:16-alpine") as pg:
            url = pg.get_connection_url().replace("postgresql+psycopg2", "postgresql+psycopg")
            os.environ["DATABASE_URL"] = url
            os.environ.setdefault("API_KEY", "test-key")
            os.environ.setdefault("METAGROSS_BASE_URL", "https://metagross.test/v1")
            os.environ.setdefault("METAGROSS_TOKEN", "test-token")
            os.environ.setdefault("APIFY_TOKEN", "test-token")
            yield url
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"could not start Postgres container: {exc}")


@pytest_asyncio.fixture
async def db_session(postgres_url: str) -> AsyncGenerator:
    """Run migrations against the container and yield a session for the test."""
    from alembic import command
    from alembic.config import Config

    from tracker.db.session import SessionLocal, engine

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", postgres_url)
    command.upgrade(cfg, "head")

    async with SessionLocal() as session:
        yield session

    await engine.dispose()
