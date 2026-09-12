"""End-to-end API test — hits the FastAPI app against a real Postgres.

Proves the Phase 1 acceptance criterion: create a local product, create inventory
for it, GET back the full record with cost_php_snapshot computed correctly, and
verify both product_ref_exclusive constraints reject invalid rows.

Skipped automatically when Docker (testcontainers) is unavailable.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import requires_docker

pytestmark = [pytest.mark.asyncio, requires_docker]


@pytest.fixture
async def client(db_session) -> Any:  # noqa: ARG001 — fixture bootstraps schema
    from tracker.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": "test-key"},
    ) as ac:
        yield ac


async def test_unauthorized_without_api_key(db_session) -> None:  # noqa: ARG001
    from tracker.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/products")
    assert r.status_code == 401


async def test_health_is_open(db_session) -> None:  # noqa: ARG001
    from tracker.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/jobs/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_create_product_and_inventory_happy_path(client: AsyncClient) -> None:
    # Seed categories are inserted by the seed migration; look up the watch category id.
    from sqlalchemy import text

    from tracker.db.session import SessionLocal

    async with SessionLocal() as s:
        watch_id = (
            await s.execute(text("SELECT id FROM categories WHERE slug = 'watch'"))
        ).scalar_one()

    # Create a Rolex Submariner as the Phase 1 acceptance example specifies.
    r = await client.post(
        "/api/v1/products",
        json={
            "category_id": watch_id,
            "name": "Rolex Submariner 124060",
            "brand": "Rolex",
            "srp_amount": "9100.00",
            "srp_currency": "USD",
        },
    )
    assert r.status_code == 201, r.text
    product = r.json()

    # Create inventory referencing that product. cost_amount * cost_fx_to_php should
    # yield exactly the snapshot we get back.
    r = await client.post(
        "/api/v1/inventory",
        json={
            "product_source": "local",
            "local_product_id": product["id"],
            "cost_amount": "9100.00",
            "cost_currency": "USD",
            "cost_fx_to_php": "56.5",
            "purchase_date": "2026-06-15",
            "storage_location": "Home safe",
        },
    )
    assert r.status_code == 201, r.text
    row = r.json()
    assert Decimal(row["cost_php_snapshot"]) == Decimal("9100") * Decimal("56.5")

    # GET back and make sure the snapshot survived.
    r = await client.get(f"/api/v1/inventory/{row['id']}")
    assert r.status_code == 200
    assert Decimal(r.json()["cost_php_snapshot"]) == Decimal("514150.0000")


async def test_inventory_local_rejects_external_product_id(client: AsyncClient) -> None:
    # This one fails at the Pydantic layer (schema validator), returning 422.
    r = await client.post(
        "/api/v1/inventory",
        json={
            "product_source": "local",
            "local_product_id": "11111111-1111-1111-1111-111111111111",
            "external_product_id": "01JXX",
            "cost_amount": "1",
            "cost_currency": "PHP",
            "cost_fx_to_php": "1",
            "purchase_date": "2026-01-01",
        },
    )
    assert r.status_code == 422


async def test_db_constraint_blocks_invalid_direct_insert(db_session) -> None:
    """The Pydantic layer catches most cases, but the DB check constraints are the
    real backstop. Insert an invalid row directly to prove the DB will reject it too."""
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(
                "INSERT INTO inventory (product_source, cost_amount, cost_currency, "
                "cost_fx_to_php, cost_php_snapshot, purchase_date, condition) "
                "VALUES ('local', 1, 'PHP', 1, 1, '2026-01-01', 'SEALED')"
            )
        )
        await db_session.commit()
    await db_session.rollback()


async def test_preorder_constraint_blocks_invalid_direct_insert(db_session) -> None:
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(
                "INSERT INTO pre_orders (product_source, store, external_product_id, "
                "local_product_id) "
                "VALUES ('metagross', 'Great Toys', '01JXX', "
                "'11111111-1111-1111-1111-111111111111')"
            )
        )
        await db_session.commit()
    await db_session.rollback()
