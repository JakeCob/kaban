# Portfolio Tracker — Technical Specification

**Owner:** Jacob
**Version:** 1.1 (v1 scope, revised after design analysis)
**Status:** Ready for implementation
**Last updated:** September 2026

---

## Changelog from v1.0

Concrete deltas applied after the design review; every change is anchored to a real risk, not a preference.

1. **`price_snapshots` grade promoted to real columns.** JSONB in a `DISTINCT ON` / unique index is fragile (`{"a":1,"b":2}` and `{"b":2,"a":1}` are semantically equal but hash differently). `grader` and `grade_value` are now scalar columns; the `grade` JSONB stays on `inventory` where `cert` and provenance still live. §5, §7 updated.
2. **`pre_orders` product-ref constraint hardened.** Now mirrors `inventory.product_ref_exclusive` — both sides asserted, not just one.
3. **`price_snapshots` batch interface.** `PriceSource` ABC gains `fetch_latest_batch` with a default fan-out; `MetagrossSource` overrides it to use `POST /products/prices/batch` (500/call). §8 updated.
4. **Cron split into per-source jobs.** pg_cron caps at 10 minutes per job; Apify actor runs are minutes each, so a single monolithic refresh would flirt with the limit. Each source now has its own cron and its own `/jobs/refresh-prices/{source_slug}` endpoint. §7, §11 updated.
5. **FX fallback semantics defined.** Last-known-good, marked stale on the response. No more implicit "if the API is down, the portfolio breaks." §9 updated.
6. **`resale_scenarios` bound to the snapshot it was priced from.** New `price_snapshot_id` FK; scenarios that would go stale on refresh are flagged rather than silently rotting. §5 updated.
7. **Grade-shape mapping documented.** Metagross returns `{grader, grade}`; the tracker enriches with optional `cert` on inventory ingest. Called out in §5 and §8 so no one wonders later.
8. **Multi-user / RLS decision moved up.** From Section 18 (open item, decide later) to Section 3 (decision, made now). See §3.
9. **§18 refreshed** to reflect the above resolutions and add the new open items surfaced during review.

Sections not listed above are unchanged from v1.0.

---

## 1. Purpose

A single-user portfolio tracker for collectibles and assets. Tracks pre-orders, current market value, cost basis, storage location, resale scenarios, and predicts store allocations for TCG releases.

**Product identity in one sentence:** the "back office" for Jacob's collection, spanning TCG (Pokemon + One Piece), watches, gadgets, cars, and property, with TCG data supplied by Metagross and everything else pulled from Apify actors.

## 2. Non-goals for v1

- Multi-user, sharing, or public views
- Native mobile app (PWA later)
- Real-time price streaming
- Automated buying or listing
- Grading pop report ingestion (Metagross handles grading data)
- Currency FX auto-updating during the day (nightly snapshot only)
- Self-hosted scrapers
- Public API for third parties

## 3. Personas and auth

Single user: Jacob.

**Auth in v1:** static API key on all endpoints (`X-API-Key` header).

**Multi-user / RLS decision (moved from open item):** the schema is designed single-tenant. No `user_id` column, no Supabase RLS in v1. If a second user is ever needed, the migration path is (a) add nullable `owner_id UUID` to every user-scoped table with a default constant for backfill, (b) enable Supabase Auth, (c) enable RLS with the standard `auth.uid() = owner_id` policy. Retrofitting is not free but it is bounded, and the cost of prematurely adding RLS to a single-tenant app is more UI, more auth flows, and more test surface for zero present benefit. Decision: pay the retrofit cost if it ever comes.

## 4. Domain model

### Categories

The system uses a `category_type` discriminator to enable/disable feature modules per category:

| Category | Type | Modules enabled |
|----------|------|-----------------|
| `tcg_sealed` | collectible | pre_orders, allocations, resale, high_freq_pricing |
| `tcg_single` | collectible | resale, high_freq_pricing (no pre_orders / allocations) |
| `watch` | collectible | resale, med_freq_pricing |
| `gadget` | collectible | resale, med_freq_pricing |
| `sneaker` | collectible | pre_orders, resale, med_freq_pricing |
| `car` | asset | maintenance, low_freq_revaluation |
| `property` | asset | maintenance, low_freq_revaluation |
| `generic` | collectible | resale (catch-all) |

Feature module flags live on the `categories` table so UI can render conditionally.

### Product identity

Products live in two systems:

- **TCG products** (Pokemon + One Piece, sealed and singles) live in Metagross. The tracker references them via `external_product_id`.
- **Non-TCG products** live locally in the `products` table with JSONB `attributes`.

An `inventory` row references exactly one of the two via a discriminator field.

## 5. Data model

### Tables

```sql
-- Enum types
CREATE TYPE category_type AS ENUM ('collectible', 'asset');
CREATE TYPE product_source AS ENUM ('metagross', 'local');
CREATE TYPE pre_order_status AS ENUM ('pending', 'paid', 'allocated', 'received', 'cancelled');
-- SEALED covers TCG sealed product; NEW covers non-TCG unopened (gadgets, watches). Intentionally distinct.
CREATE TYPE condition_type AS ENUM ('SEALED', 'NM', 'LP', 'MP', 'HP', 'DMG', 'USED', 'NEW', 'FOR_PARTS');

-- Categories drive the UI feature modules
CREATE TABLE categories (
  id             SERIAL PRIMARY KEY,
  slug           TEXT UNIQUE NOT NULL,
  name           TEXT NOT NULL,
  category_type  category_type NOT NULL,
  attribute_schema JSONB NOT NULL DEFAULT '{}'::jsonb,
  modules        JSONB NOT NULL DEFAULT '{}'::jsonb,
  -- shape: {"pre_orders": true, "allocations": true, "resale": true, ...}
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Local products (non-TCG)
CREATE TABLE products (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  category_id    INT NOT NULL REFERENCES categories(id),
  name           TEXT NOT NULL,
  brand          TEXT,
  attributes     JSONB NOT NULL DEFAULT '{}'::jsonb,
  srp_amount     NUMERIC(18, 4),
  srp_currency   TEXT,  -- ISO 4217
  image_url      TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_products_category ON products(category_id);
CREATE INDEX idx_products_attributes ON products USING GIN (attributes);

-- Inventory: what Jacob owns
-- Note: inventory.grade stays JSONB because it carries provenance (cert #, grader, grade value together)
-- that is meaningful only at the inventory level, not at pricing time.
CREATE TABLE inventory (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  product_source        product_source NOT NULL,
  external_product_id   TEXT,   -- Metagross ULID when source = metagross
  local_product_id      UUID REFERENCES products(id),
  quantity              INT NOT NULL DEFAULT 1 CHECK (quantity >= 0),
  cost_amount           NUMERIC(18, 4) NOT NULL,
  cost_currency         TEXT NOT NULL,
  cost_fx_to_php        NUMERIC(18, 8) NOT NULL,   -- rate at purchase time
  cost_php_snapshot     NUMERIC(18, 4) NOT NULL,   -- denorm: cost_amount * cost_fx_to_php
  purchase_date         DATE NOT NULL,
  source                TEXT,  -- "Great Toys", "Chrono24 seller X", "Taiwan pickup"
  storage_location      TEXT,  -- freeform "Box A, shelf 2" (v1); locations table in v1.5 if it starts biting
  condition             condition_type NOT NULL DEFAULT 'SEALED',
  grade                 JSONB, -- {"grader": "PSA", "grade": "10", "cert": "12345"}
  notes                 TEXT,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT product_ref_exclusive CHECK (
    (product_source = 'metagross' AND external_product_id IS NOT NULL AND local_product_id IS NULL)
    OR
    (product_source = 'local' AND local_product_id IS NOT NULL AND external_product_id IS NULL)
  )
);
CREATE INDEX idx_inventory_source ON inventory(product_source);
CREATE INDEX idx_inventory_external ON inventory(external_product_id) WHERE external_product_id IS NOT NULL;
CREATE INDEX idx_inventory_local ON inventory(local_product_id) WHERE local_product_id IS NOT NULL;
CREATE INDEX idx_inventory_storage ON inventory(storage_location);

-- Pre-orders
-- Constraint now mirrors inventory's exclusive-ref shape (both sides asserted).
CREATE TABLE pre_orders (
  id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  product_source         product_source NOT NULL,
  external_product_id    TEXT,
  local_product_id       UUID REFERENCES products(id),
  release_code           TEXT,  -- "UPC_2026_11", used for allocation strategy lookup
  store                  TEXT NOT NULL,
  deposit_amount         NUMERIC(18, 4),
  deposit_currency       TEXT,
  expected_units         INT,
  actual_units           INT,   -- filled after allocation resolved
  release_date           DATE,
  status                 pre_order_status NOT NULL DEFAULT 'pending',
  notes                  TEXT,
  created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT preorder_product_ref_exclusive CHECK (
    (product_source = 'metagross' AND external_product_id IS NOT NULL AND local_product_id IS NULL)
    OR
    (product_source = 'local'     AND local_product_id    IS NOT NULL AND external_product_id IS NULL)
  )
);
CREATE INDEX idx_preorders_status ON pre_orders(status);
CREATE INDEX idx_preorders_release_date ON pre_orders(release_date);
CREATE INDEX idx_preorders_release_code ON pre_orders(release_code);

-- Price sources
CREATE TABLE price_sources (
  id           SERIAL PRIMARY KEY,
  slug         TEXT UNIQUE NOT NULL,  -- "metagross", "apify_chrono24", "manual", ...
  name         TEXT NOT NULL,
  kind         TEXT NOT NULL,  -- "api" | "scrape" | "manual" | "firecrawl"
  config       JSONB NOT NULL DEFAULT '{}'::jsonb,
  is_active    BOOLEAN NOT NULL DEFAULT TRUE
);

-- Price snapshots
-- grader / grade_value are promoted from JSONB to real columns so DISTINCT ON and unique indexes
-- do not depend on JSONB text representation. Metagross's PriceSnapshot.grade.{grader,grade}
-- maps directly onto these two columns on ingest.
CREATE TABLE price_snapshots (
  id                  BIGSERIAL PRIMARY KEY,
  product_source      product_source NOT NULL,
  external_product_id TEXT,
  local_product_id    UUID REFERENCES products(id),
  source_id           INT NOT NULL REFERENCES price_sources(id),
  price_amount        NUMERIC(18, 4) NOT NULL,
  price_currency      TEXT NOT NULL,
  condition           condition_type,
  grader              TEXT,           -- "PSA" | "BGS" | "CGC" | NULL
  grade_value         TEXT,           -- "10" | "9.5" | NULL (kept as text; supports half-grades)
  raw                 JSONB,          -- source-native payload
  captured_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_snapshots_product_time ON price_snapshots(external_product_id, captured_at DESC)
  WHERE external_product_id IS NOT NULL;
CREATE INDEX idx_snapshots_local_time ON price_snapshots(local_product_id, captured_at DESC)
  WHERE local_product_id IS NOT NULL;

-- Materialized latest-price view (refresh nightly)
-- Deterministic key on scalar columns only; no JSONB in the ORDER BY or the unique index.
CREATE MATERIALIZED VIEW latest_prices AS
SELECT DISTINCT ON (product_source, external_product_id, local_product_id, condition, grader, grade_value)
  product_source, external_product_id, local_product_id, condition, grader, grade_value,
  price_amount, price_currency, source_id, captured_at, id AS snapshot_id
FROM price_snapshots
ORDER BY product_source, external_product_id, local_product_id, condition, grader, grade_value, captured_at DESC;

CREATE UNIQUE INDEX idx_latest_prices_unique
  ON latest_prices(
    product_source,
    COALESCE(external_product_id, ''),
    COALESCE(local_product_id::text, ''),
    COALESCE(condition::text, ''),
    COALESCE(grader, ''),
    COALESCE(grade_value, '')
  );

-- FX rates (daily)
CREATE TABLE fx_rates (
  as_of_date  DATE NOT NULL,
  base        TEXT NOT NULL,
  quote       TEXT NOT NULL,
  rate        NUMERIC(18, 8) NOT NULL,
  source      TEXT NOT NULL DEFAULT 'frankfurter',
  PRIMARY KEY (as_of_date, base, quote)
);

-- Resale scenarios (calculated on demand, cached)
-- price_snapshot_id ties the scenario to the exact snapshot it was priced from, so we can
-- flag scenarios that would be invalidated by the next refresh instead of them silently rotting.
CREATE TABLE resale_scenarios (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  inventory_id      UUID NOT NULL REFERENCES inventory(id) ON DELETE CASCADE,
  price_snapshot_id BIGINT REFERENCES price_snapshots(id) ON DELETE SET NULL,
  platform          TEXT NOT NULL,   -- "ebay", "tcgplayer", "shopee_ph", "carousell_ph", "chrono24"
  gross_amount      NUMERIC(18, 4) NOT NULL,
  gross_currency    TEXT NOT NULL,
  fees              JSONB NOT NULL,  -- {"platform_pct": 0.1325, "payment_pct": 0.03, "shipping_flat": 200}
  net_php           NUMERIC(18, 4) NOT NULL,
  calculated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_resale_scenarios_inventory ON resale_scenarios(inventory_id);
CREATE INDEX idx_resale_scenarios_snapshot ON resale_scenarios(price_snapshot_id)
  WHERE price_snapshot_id IS NOT NULL;

-- Allocation strategies (metadata only; logic in Python)
CREATE TABLE allocation_rules (
  release_code   TEXT PRIMARY KEY,
  strategy_slug  TEXT NOT NULL,   -- maps to Python class in strategies/ package
  params         JSONB NOT NULL DEFAULT '{}'::jsonb,
  active         BOOLEAN NOT NULL DEFAULT TRUE,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Allocation outcomes (for future ML)
CREATE TABLE allocation_outcomes (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  release_code      TEXT NOT NULL,
  store             TEXT NOT NULL,
  inputs            JSONB NOT NULL,
  predicted_p50     INT,
  predicted_p90     INT,
  predicted_p10     INT,
  actual_units      INT,
  recorded_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Platform fee tables (seeded, editable)
CREATE TABLE platform_fees (
  platform          TEXT PRIMARY KEY,
  fee_structure     JSONB NOT NULL,
  -- shape: {"platform_pct": 0.1325, "payment_pct": 0.03, "listing_flat": 0, "shipping_flat_php": 200}
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### Grade-shape mapping (Metagross → tracker)

Metagross returns grade as `{"grader": "PSA", "grade": "10"}`. The tracker maps this on ingest:

| Metagross field | Tracker column | Notes |
|-----------------|----------------|-------|
| `grade.grader`  | `price_snapshots.grader` | passthrough |
| `grade.grade`   | `price_snapshots.grade_value` | kept as TEXT to preserve half-grades ("9.5") |
| n/a             | `inventory.grade.cert` | tracker-side provenance only; Metagross does not know cert numbers |

### Seed data expected

- `categories`: all 8 categories from the table in Section 4
- `price_sources`: metagross, apify_chrono24, apify_carousell_ph, apify_shopee_ph, apify_lamudi, apify_philkotse, firecrawl, manual
- `platform_fees`: eBay (13.25% + 3% PayPal), TCGPlayer (~10.25%), Shopee PH (5.24% + payment), Carousell PH (verify — see §18), Chrono24 (6.5%), Lamudi (agent fees vary)

## 6. Configuration

Environment variables (Railway):

```
DATABASE_URL=postgresql+psycopg://...   # Supabase pooler
API_KEY=<random>                        # required in X-API-Key
METAGROSS_BASE_URL=https://api.metagross.<domain>/v1
METAGROSS_TOKEN=<bearer>
APIFY_TOKEN=<token>
FIRECRAWL_API_KEY=<key>                 # optional
N8N_WEBHOOK_URL=<url>                   # optional, for alerts
LOG_LEVEL=INFO
```

## 7. API surface (FastAPI)

All routes under `/api/v1`. All require `X-API-Key`. JSON in and out. Errors follow the shape from the Metagross contract.

### Products (local only)
- `POST /products` create local product
- `GET /products/{id}` get local product
- `PATCH /products/{id}` update
- `GET /products?category=&q=&cursor=&limit=` search local products

### Inventory
- `POST /inventory` create (validates product_source + one product ref)
- `GET /inventory/{id}` get with joined product data
- `PATCH /inventory/{id}`
- `DELETE /inventory/{id}`
- `GET /inventory?category=&storage_location=&cursor=&limit=`
- `GET /inventory/portfolio` returns portfolio-level view: total cost basis in PHP, current market value in PHP, unrealized P&L, grouped by category. Response includes `fx_status: {"as_of_date": "...", "stale": bool}` — see §9.

### Pre-orders
- `POST /pre_orders`, `GET`, `PATCH`, `DELETE`
- `GET /pre_orders?status=&release_date_before=&release_date_after=`
- `POST /pre_orders/{id}/resolve` sets `actual_units`, `status`, optionally creates inventory rows for received units

### Prices
- `GET /prices/latest?product_source=&external_product_id=&local_product_id=&condition=&grader=&grade_value=` returns latest snapshot
- `GET /prices/history?...&from=&to=&granularity=` returns time series
- `POST /prices/manual` submit a manual price observation
- `POST /prices/refresh` trigger a refresh for a single product (calls appropriate source)

### Resale
- `POST /resale/preview` body `{inventory_id, platform}` returns `{gross_amount, fees, net_php, based_on_snapshot_id}` without persisting
- `POST /resale/scenarios` persist a scenario (for tracking "if I sold this at X, I'd net Y"). Response flags `stale: true` when its `price_snapshot_id` is older than the latest snapshot for the same (product, condition, grader, grade_value) key.

### Allocations
- `POST /allocations/predict` body `{release_code, store, inputs: {...}}` returns `AllocationPrediction`
- `POST /allocations/outcomes` record actual outcome for a past prediction

### Jobs (called by pg_cron)
- `POST /jobs/refresh-prices/{source_slug}` refresh prices for one source (e.g. `metagross`, `apify_chrono24`); walks inventory + pre_orders scoped to that source, writes snapshots, refreshes materialized view at end of run. **Each source is its own cron job** — see §11.
- `POST /jobs/refresh-prices` legacy convenience endpoint that fans out to all active sources sequentially. Not called by cron; intended for manual "refresh everything" from the shell.
- `POST /jobs/refresh-fx` fetches daily FX rates from Frankfurter
- `POST /jobs/health` heartbeat for uptime check

All response models are Pydantic v2 with `model_config = ConfigDict(from_attributes=True)`. Decimal in, Decimal out (Pydantic serializes to string to avoid float precision loss).

## 8. Pricing engine

### Source interface

```python
# sources/base.py
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Literal
from uuid import UUID

class PriceQuery(BaseModel):
    product_source: Literal["metagross", "local"]
    external_product_id: str | None = None
    local_product_id: UUID | None = None
    condition: str | None = None
    grader: str | None = None
    grade_value: str | None = None

class PriceResult(BaseModel):
    amount: Decimal
    currency: str
    condition: str | None
    grader: str | None
    grade_value: str | None
    raw: dict
    source_slug: str

class PriceSource(ABC):
    slug: str

    @abstractmethod
    async def fetch_latest(self, query: PriceQuery) -> PriceResult | None: ...

    async def fetch_latest_batch(
        self, queries: list[PriceQuery]
    ) -> list[PriceResult | None]:
        # Default: fan-out to fetch_latest. Sources with a native batch API
        # (Metagross) override this to make a single upstream call.
        return [await self.fetch_latest(q) for q in queries]

    @abstractmethod
    def can_handle(self, query: PriceQuery, product: dict) -> bool: ...
```

### Concrete sources

- `MetagrossSource` — overrides `fetch_latest_batch` to call `POST /products/prices/batch` (500 items/call, per the Metagross contract). `fetch_latest` still available for one-off lookups; the refresh job uses the batch path.
- `ApifyChrono24Source` — calls the Apify actor with a search or listing URL, extracts median. Uses default fan-out.
- `ApifyCarousellPHSource`, `ApifyShopeePHSource`, `ApifyLamudiSource`, `ApifyPhilkotseSource` — same pattern.
- `FirecrawlSource` — takes a URL from product `attributes.reference_url`, runs `/scrape` with a JSON schema.
- `ManualSource` — no fetching; just stores what the user submitted.

### Refresh job flow (per source)

```
refresh_prices(source_slug):
  source = registry[source_slug]
  queries = build_queries_for(source)      # inventory + open pre_orders that this source can handle
  results = await source.fetch_latest_batch(queries)
  for q, r in zip(queries, results):
    if r is None: log_missing(q); continue
    insert_snapshot(q, r)

  REFRESH MATERIALIZED VIEW CONCURRENTLY latest_prices;

  notify n8n webhook with per-source summary
```

Concurrency: `asyncio.gather` with a semaphore of 5 inside sources that fan-out (i.e. the scrapers). Metagross runs sequential batch calls of 500 each — no fan-out needed.

## 9. Money and FX

- All monetary fields `NUMERIC(18, 4)`. Currency always alongside.
- `py-moneyed` in application code.
- `cost_fx_to_php` snapshotted at inventory creation and never updated.
- Portfolio views apply latest daily FX from `fx_rates` for market values only, never for cost basis.

### FX refresh job (nightly)

```python
async def refresh_fx():
    base = "PHP"
    quotes = ["USD", "JPY", "TWD", "EUR", "GBP"]
    r = await httpx.get(
        f"https://api.frankfurter.dev/v1/latest?base={base}&symbols={','.join(quotes)}"
    )
    for quote, rate in r.json()["rates"].items():
        await db.upsert(
            fx_rates,
            {"as_of_date": date.today(), "base": base, "quote": quote, "rate": Decimal(str(rate))},
        )
```

### Fallback semantics (new)

Portfolio and resale calculations that need an FX rate resolve in this order:

1. `fx_rates` row for today's date and the required currency pair.
2. Most recent `fx_rates` row within the last 14 days.
3. Fail the request with `503 fx_unavailable` (the calling endpoint decides whether to surface partial results).

When step 2 is used, the API response includes `fx_status: {"as_of_date": "<older date>", "stale": true, "days_stale": <n>}` at the top level. Portfolio views degrade gracefully (values still render); resale previews degrade loudly (banner in the response body). The 14-day window is arbitrary — it exists so we notice the frankfurter job failed for two weeks instead of quietly serving stale values indefinitely.

## 10. Allocation strategies

### Interface

```python
# strategies/base.py
class AllocationInputs(BaseModel):
    quantity_requested: int
    customer_tier: str | None = None
    prior_spend_php: Decimal | None = None
    deposit_amount_php: Decimal | None = None
    deposit_timestamp: datetime | None = None
    cutoff_timestamp: datetime | None = None
    known_oversubscription_ratio: float | None = None
    store_specific: dict = {}

class AllocationPrediction(BaseModel):
    expected_units: float
    p50_units: int
    p90_units: int
    p10_units: int
    confidence: float  # 0.0 - 1.0
    explanation: list[str]

class AllocationStrategy(ABC):
    slug: str
    release_code: str
    store: str

    @abstractmethod
    def predict(self, inputs: AllocationInputs, params: dict) -> AllocationPrediction: ...
```

### Registry

```python
# strategies/registry.py
_STRATEGIES: dict[str, type[AllocationStrategy]] = {}

def register(cls: type[AllocationStrategy]):
    _STRATEGIES[cls.slug] = cls
    return cls

def get(slug: str) -> type[AllocationStrategy]:
    return _STRATEGIES[slug]

# strategies/upc_2026_11.py
@register
class UPC_2026_11_GreatToys(AllocationStrategy):
    slug = "upc_2026_11_great_toys"
    release_code = "UPC_2026_11"
    store = "Great Toys"

    def predict(self, inputs, params):
        # port from existing UPC Allocation Calculator
        ...
```

Endpoint `POST /allocations/predict` looks up strategy via `allocation_rules[release_code].strategy_slug`.

## 11. Scheduled jobs (Supabase Cron)

Configured via SQL migration. **One cron entry per source**, staggered so they don't contend for the pg_cron 8-concurrent-job cap or the 10-minute-per-job cap.

```sql
-- FX first at 2:00 AM PHT (18:00 UTC previous day) — cheap and quick
SELECT cron.schedule(
  'refresh-fx',
  '0 18 * * *',
  $$
  SELECT net.http_post(
    url := 'https://tracker-api.<domain>/api/v1/jobs/refresh-fx',
    headers := jsonb_build_object('X-API-Key', current_setting('app.tracker_api_key'))
  );
  $$
);

-- Metagross at 3:00 AM PHT (batch API, single call, fast)
SELECT cron.schedule(
  'refresh-prices-metagross',
  '0 19 * * *',
  $$SELECT net.http_post(
      url := 'https://tracker-api.<domain>/api/v1/jobs/refresh-prices/metagross',
      headers := jsonb_build_object('X-API-Key', current_setting('app.tracker_api_key')));$$
);

-- Apify sources staggered 10 minutes apart, each in its own job envelope.
SELECT cron.schedule('refresh-prices-chrono24', '10 19 * * *', $$
  SELECT net.http_post(
    url := 'https://tracker-api.<domain>/api/v1/jobs/refresh-prices/apify_chrono24',
    headers := jsonb_build_object('X-API-Key', current_setting('app.tracker_api_key')));$$);

SELECT cron.schedule('refresh-prices-carousell-ph', '20 19 * * *', $$
  SELECT net.http_post(
    url := 'https://tracker-api.<domain>/api/v1/jobs/refresh-prices/apify_carousell_ph',
    headers := jsonb_build_object('X-API-Key', current_setting('app.tracker_api_key')));$$);

SELECT cron.schedule('refresh-prices-shopee-ph', '30 19 * * *', $$
  SELECT net.http_post(
    url := 'https://tracker-api.<domain>/api/v1/jobs/refresh-prices/apify_shopee_ph',
    headers := jsonb_build_object('X-API-Key', current_setting('app.tracker_api_key')));$$);

SELECT cron.schedule('refresh-prices-lamudi', '40 19 * * *', $$
  SELECT net.http_post(
    url := 'https://tracker-api.<domain>/api/v1/jobs/refresh-prices/apify_lamudi',
    headers := jsonb_build_object('X-API-Key', current_setting('app.tracker_api_key')));$$);

SELECT cron.schedule('refresh-prices-philkotse', '50 19 * * *', $$
  SELECT net.http_post(
    url := 'https://tracker-api.<domain>/api/v1/jobs/refresh-prices/apify_philkotse',
    headers := jsonb_build_object('X-API-Key', current_setting('app.tracker_api_key')));$$);
```

Each per-source job endpoint refreshes the materialized view when it finishes. Two refresh calls landing within seconds of each other is fine — `REFRESH MATERIALIZED VIEW CONCURRENTLY` is idempotent and cheap.

API key stored in Supabase Vault, exposed via `current_setting`.

## 12. Directory structure

```
tracker-api/
├── pyproject.toml
├── README.md
├── Dockerfile
├── railway.json
├── alembic.ini
├── alembic/
│   ├── env.py
│   └── versions/
├── src/
│   └── tracker/
│       ├── __init__.py
│       ├── main.py                 # FastAPI app
│       ├── config.py               # pydantic-settings
│       ├── deps.py                 # dependency-injection helpers
│       ├── db/
│       │   ├── models.py           # SQLAlchemy models
│       │   ├── session.py
│       │   └── views.py            # materialized view helpers
│       ├── schemas/                # Pydantic v2 request/response
│       ├── routers/
│       │   ├── products.py
│       │   ├── inventory.py
│       │   ├── pre_orders.py
│       │   ├── prices.py
│       │   ├── resale.py
│       │   ├── allocations.py
│       │   └── jobs.py
│       ├── services/
│       │   ├── inventory.py
│       │   ├── portfolio.py
│       │   ├── resale.py
│       │   └── refresh.py
│       ├── sources/
│       │   ├── base.py
│       │   ├── metagross.py
│       │   ├── apify.py            # shared Apify client
│       │   ├── apify_chrono24.py
│       │   ├── apify_carousell.py
│       │   ├── apify_shopee.py
│       │   ├── apify_lamudi.py
│       │   ├── apify_philkotse.py
│       │   ├── firecrawl.py
│       │   └── manual.py
│       ├── strategies/
│       │   ├── base.py
│       │   ├── registry.py
│       │   ├── upc_2026_11.py
│       │   └── ...
│       ├── money/
│       │   ├── fx.py
│       │   └── conversion.py
│       └── clients/
│           ├── metagross.py        # HTTP client for Metagross API
│           └── frankfurter.py      # FX rates client
└── tests/
    ├── conftest.py
    ├── test_inventory.py
    ├── test_pricing.py
    ├── test_resale.py
    ├── test_allocations.py
    └── fixtures/
```

## 13. Tech stack (pinned)

```
python = "^3.12"
fastapi = "^0.115"
uvicorn = {extras = ["standard"], version = "^0.32"}
sqlalchemy = "^2.0"
alembic = "^1.13"
psycopg = {extras = ["binary", "pool"], version = "^3.2"}
pydantic = "^2.9"
pydantic-settings = "^2.6"
py-moneyed = "^3.0"
httpx = "^0.27"
apify-client = "^1.8"
firecrawl-py = "^1.0"        # optional
tenacity = "^9.0"            # retries on external calls

# dev
pytest = "^8.3"
pytest-asyncio = "^0.24"
pytest-httpx = "^0.32"
ruff = "^0.7"
mypy = "^1.13"
```

## 14. Phased implementation (Claude Code PRs)

Each phase is one PR. Each phase has clear acceptance criteria and can be tested independently.

### Phase 1 — Foundation
**Scope:** Project skeleton, config, DB, migrations, categories, local products, inventory CRUD.

**Deliverables:**
- `pyproject.toml`, `alembic.ini`, Dockerfile, `railway.json`
- Full initial migration creating all tables in Section 5 (including `grader`/`grade_value` scalar columns on `price_snapshots`, `price_snapshot_id` FK on `resale_scenarios`, and the tightened `pre_orders` constraint)
- Seed migration for `categories`, `price_sources`, `platform_fees`
- `main.py` with X-API-Key middleware
- Routers: `/products` (local), `/inventory` (all fields)
- Pydantic schemas for Product, Inventory
- `services/inventory.py` with cost_php_snapshot calculation
- Tests: 90%+ coverage of inventory service, contract tests on router happy path
- README with local dev instructions

**Acceptance:**
- `uvicorn tracker.main:app --reload` boots
- `alembic upgrade head` creates all tables and both constraints (`inventory.product_ref_exclusive` and `pre_orders.preorder_product_ref_exclusive`) reject invalid rows
- `pytest` passes with `pytest-asyncio` in strict mode
- Can create a local product (a Rolex Submariner), then create inventory for it, then GET back the full record with `cost_php_snapshot` computed correctly from `cost_amount * cost_fx_to_php`

### Phase 2 — Pricing engine (part 1: Metagross + Manual)
**Scope:** Source interface, Metagross client, manual source, price_snapshots writes, latest_prices view.

**Deliverables:**
- `sources/base.py` with `PriceSource` ABC (including `fetch_latest_batch` default)
- `clients/metagross.py` with typed methods matching the API contract, including `prices_batch(requests)`
- `sources/metagross.py` implementing `PriceSource`, overriding `fetch_latest_batch` to call the Metagross batch endpoint
- `sources/manual.py`
- `/prices/latest`, `/prices/history`, `/prices/manual`, `/prices/refresh` endpoints (queries take `grader` + `grade_value`)
- Materialized view + refresh function keyed on scalar columns only
- Tests using `pytest-httpx` to mock Metagross responses, including the batch endpoint

**Acceptance:**
- POST inventory referencing a Metagross product_id, then POST `/prices/refresh` for it, then GET `/prices/latest` returns the correct snapshot
- POST manual price for a local product works and is retrievable
- A refresh over 3 Metagross products issues **one** upstream batch call, not three

### Phase 3 — Portfolio, resale, FX
**Scope:** Portfolio view, resale calculator, FX job, py-moneyed integration.

**Deliverables:**
- `services/portfolio.py` computing category totals in PHP
- `services/resale.py` with platform_fees lookup; persisted scenarios carry `price_snapshot_id`
- `clients/frankfurter.py` + `/jobs/refresh-fx`
- `money/fx.py` implementing the fallback chain from §9 (today → last 14 days → 503)
- `money/conversion.py`
- `GET /inventory/portfolio` endpoint with `fx_status` in the response
- `POST /resale/preview` and `POST /resale/scenarios`; scenario responses include a `stale` flag when the snapshot they were priced from is no longer the latest
- Tests including edge cases: PHP-native items (no conversion), missing FX rate fallback (14-day window), FX gone for >14 days (503)

**Acceptance:**
- Portfolio view returns numbers that reconcile with manual math on a known small dataset (fixture)
- Resale preview for a $2000 USD sale on eBay returns net_php correctly (net of fees + FX)
- Deleting today's FX row and re-fetching portfolio returns yesterday's rate with `stale: true`

### Phase 4 — Apify sources
**Scope:** All Apify actor integrations, per-source `/jobs/refresh-prices/{slug}` endpoints, Supabase Cron setup.

**Deliverables:**
- `sources/apify.py` shared client wrapper (rate limiting via `asyncio.Semaphore`, retries via `tenacity`)
- One source module per site (Chrono24, Carousell PH, Shopee PH, Lamudi, Philkotse)
- `/jobs/refresh-prices/{source_slug}` orchestrator (one endpoint, dispatches by slug)
- `/jobs/refresh-prices` convenience fan-out endpoint (not wired to cron)
- Alembic migration for the staggered per-source pg_cron schedules
- Contract tests for each source with fixture Apify responses

**Acceptance:**
- `POST /jobs/refresh-prices/apify_chrono24` walks a seeded inventory of watches and writes at least one snapshot per item
- pg_cron entries visible in `cron.job` after migration, staggered 10 minutes apart
- No source can crash the whole job (failures isolated + logged per-item)
- A failing Apify actor for one source does not stop the other sources' cron entries from running

### Phase 5 — Pre-orders and allocations
**Scope:** Pre-order CRUD, allocation strategy framework, port UPC calculator as first strategy.

**Deliverables:**
- `/pre_orders/*` endpoints (with tightened exclusive constraint enforced)
- `/allocations/predict` and `/allocations/outcomes`
- `strategies/base.py`, `strategies/registry.py`
- `strategies/upc_2026_11_great_toys.py` (port from your UPC calculator)
- `POST /pre_orders/{id}/resolve` creates inventory rows
- Tests including a golden-file test for UPC predictions (input → expected output)

**Acceptance:**
- Predict endpoint returns valid `AllocationPrediction` for the UPC release
- Resolving a pre-order with `actual_units=2` creates two inventory rows in a transaction

### Phase 6 — Polish and n8n hooks
**Scope:** Alert webhooks, health checks, observability.

**Deliverables:**
- Webhook to n8n on: price threshold cross, pre-order status change, refresh job summary (per-source)
- `/jobs/health` for uptime monitoring
- Structured logging (JSON, INFO by default)
- OpenAPI docs cleaned up (`/docs` accurate)

**Acceptance:**
- Setting a price threshold in `attributes.alert_threshold_php` on a product triggers an n8n webhook when crossed
- OpenAPI schema validates without warnings

## 15. Testing strategy

- **Unit tests** for services (portfolio math, FX conversion + fallback chain, resale calc, allocation strategies).
- **Contract tests** for external clients (`pytest-httpx`), including Metagross batch endpoint shape.
- **Integration tests** via `testcontainers-python` spinning up Postgres.
- **Golden files** for allocation predictions (frozen expected output for known inputs).
- No E2E against real Apify or Metagross in CI. Manual verification in a staging environment.

## 16. Deployment

- **Backend:** Railway (Dockerfile + `railway.json`, autodeploy from `main`)
- **Database:** Supabase project (free tier)
- **Scheduling:** pg_cron in Supabase (one entry per source; see §11)
- **Secrets:** Railway env vars + Supabase Vault for the API key needed by cron

CI (GitHub Actions):
1. Ruff + Mypy
2. Pytest (with testcontainers Postgres)
3. On merge to `main`, Railway deploy triggered

## 17. Out of scope for v1 (reminder)

Reject any of these from PRs until v1 lands:
- UI beyond OpenAPI `/docs`
- Auth beyond static API key
- Multi-user, sharing, RLS (see §3 for the deferred-migration plan)
- Real-time updates (WebSockets, SSE)
- Advanced ML for allocations
- Native mobile app
- Sneakers, comics, Funko (add category rows later without schema changes)

## 18. Open items to decide during Phase 1

Resolved since v1.0:
- ~~Whether to keep `condition` on `price_snapshots` PK or model it separately~~ → resolved: `grader`/`grade_value` promoted; `condition` remains as a scalar column and participates in the latest-view key.
- ~~Multi-user or single-user + RLS?~~ → resolved in §3: single-tenant; deferred migration documented.
- ~~FX fallback strategy~~ → resolved in §9.

Still open (verify or decide during Phase 1):
- Exact set of platform fees for `platform_fees` seed. Carousell PH specifically — they have been rolling out seller fees on high-value verticals (watches, sneakers) through 2025–2026, so the "0%" from research findings needs re-verification before seeding. Also confirm eBay, TCGPlayer, Shopee PH, Chrono24 current rates.
- Timezone strategy for `release_date` fields on pre_orders (store as DATE in Manila time).
- Whether the `attributes` JSONB on `products` should have a JSON Schema validator per category (fine to skip in v1; a nice week-two upgrade).
- Historical price backfill: for items already owned, backfill from Apify sales-history endpoints, or start clean from now? Decision affects Phase 2 scope by a day or two.
- Alert channels (§9 research doc): Telegram bot vs Semaphore SMS vs email. Cheapest is Telegram; SMS costs per message. Blocks Phase 6 only.
