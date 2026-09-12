# kaban — Portfolio Tracker

Single-user portfolio tracker for collectibles and assets. Tracks pre-orders, current market value, cost basis, storage, resale scenarios, and predicts store allocations for TCG releases.

Backend-only in v1. See [`docs/SPEC.md`](docs/SPEC.md) for the specification.

## Documents

| File | What it is |
|------|-----------|
| [`docs/SPEC.md`](docs/SPEC.md) | Full technical spec (v1.1) |
| [`docs/METAGROSS_API_CONTRACT.md`](docs/METAGROSS_API_CONTRACT.md) | External TCG service contract |
| [`docs/RESEARCH_FINDINGS.md`](docs/RESEARCH_FINDINGS.md) | Background research and trade-off notes |
| [`CLAUDE.md`](CLAUDE.md) | Context for Claude Code sessions |

## Quickstart (once Phase 1 lands)

```bash
uv sync --extra dev            # install deps
cp .env.example .env           # fill in secrets
alembic upgrade head           # create schema
uvicorn tracker.main:app --reload
```

Open http://localhost:8000/docs for the OpenAPI UI.

## Tech stack

- Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2.0 · Alembic
- Postgres (Supabase) with pg_cron for scheduling
- Apify SDK for scraping, Metagross API for TCG pricing
- Railway for backend deployment

## Layout

```
kaban/
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── Dockerfile
├── railway.json
├── alembic.ini
├── alembic/                   # database migrations
├── docs/                      # spec, contracts, research
├── src/tracker/               # application code (src layout)
│   ├── main.py                # FastAPI entrypoint
│   ├── config.py              # pydantic-settings
│   ├── db/                    # SQLAlchemy models, session, view helpers
│   ├── schemas/               # Pydantic v2 request/response
│   ├── routers/               # FastAPI routers
│   ├── services/              # business logic
│   ├── sources/               # pricing adapters (Metagross, Apify, …)
│   ├── strategies/            # allocation prediction strategies
│   ├── money/                 # FX + currency conversion
│   └── clients/               # HTTP clients for external APIs
└── tests/
```
