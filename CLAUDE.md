# CLAUDE.md — Portfolio Tracker

Context for Claude Code sessions working on this repository.

## What this project is

Single-user portfolio tracker for Jacob's collectibles and assets. Backend-only in v1 (FastAPI + Supabase Postgres). See `docs/SPEC.md` for the full specification.

Product identity in one sentence: the back office for Jacob's collection — TCG (Pokemon + One Piece), watches, gadgets, cars, and property — with TCG data supplied by the external **Metagross** service and everything else pulled from Apify actors.

## Where things live

- **Specification** — `docs/SPEC.md` (v1.1). Read before making design changes.
- **Metagross API contract** — `docs/METAGROSS_API_CONTRACT.md`. The external TCG data service.
- **Research background** — `docs/RESEARCH_FINDINGS.md`. Why we chose the tools we did.
- **Application code** — `src/tracker/` (src layout).
- **Migrations** — `alembic/versions/`.
- **Tests** — `tests/`.

## Conventions

- Python 3.12, FastAPI + Pydantic v2 + SQLAlchemy 2.0.
- `Decimal` for money, never `float`.
- Async-first (`async def` endpoints, `httpx.AsyncClient`, `asyncio.gather`).
- One test file per service or router (`tests/test_<name>.py`).
- Migrations named `<timestamp>_<snake_case_description>.py`.
- Ruff for lint + format, Mypy strict.

## When making changes

1. If touching schema or interfaces, update `docs/SPEC.md` in the same commit.
2. Run `ruff check .`, `mypy src`, and `pytest` before pushing.
3. Never bypass the `product_ref_exclusive` constraints — they encode a real invariant.
4. Money fields always carry a currency; cross-currency math needs a dated FX rate. See SPEC §9.

## What NOT to add (see SPEC §17)

- UI code — v1 is API-only.
- Auth beyond the static `X-API-Key` header.
- Multi-user / RLS — SPEC §3 documents the deferred-migration plan.
- Self-hosted scrapers — Apify covers it.
- Redis or an external task queue — pg_cron is enough for v1.

## Branch conventions

- `main` — deployed via Railway on merge.
- `claude/<slug>` — Claude Code working branches (this branch: `claude/document-analysis-2gd4dr`).
