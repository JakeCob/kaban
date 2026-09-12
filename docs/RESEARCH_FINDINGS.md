# Portfolio Tracker — Tools, Frameworks, Algorithms Research

**Date:** September 2026
**Purpose:** Ground the SPEC.md in current landscape before locking choices.
**Scope:** Non-TCG data sources (watches, gadgets, cars, property), the pricing engine, scraping approach, scheduling, money handling, allocation prediction, and how it all fits Jacob's existing stack.

TL;DR bar at the top of each section so you can scan and drill down only where you need to.

---

## 1. TCG pricing (context for Metagross)

**TL;DR:** TCGPlayer's official API is closed to new developers. The 2026 ecosystem replacement is JustTCG or tcgapi.dev. PriceCharting is the pick for sealed. This is Metagross's problem, not the tracker's, but worth knowing.

The TCGPlayer official API stopped granting new keys years ago and remains closed. New builds have to pick from third-party sources that mirror TCGPlayer data or aggregate their own.

**Options ranked:**

- **JustTCG** — 17 games including Pokemon (English + Japanese) and One Piece. Condition and printing granularity. Free tier with API key on signup. Blends online listings with in-store sales from partner network. Cleanest fit if OP TCG matters.
- **tcgapi.dev (TCG API)** — 89+ games, all conditions, daily refresh on top 7 (includes One Piece). Free tier 100 req/day. Cloudflare edge, x402 micropayments supported. Broader coverage than JustTCG.
- **PriceCharting** — Best for sealed product (booster boxes, ETBs, UPCs) across all TCGs plus retro video games and Funko. Historic sales-based pricing. Has API access.
- **Pokemon TCG API (pokemontcg.io / Scrydex)** — Catalog + prices for Pokemon only. Well-maintained.
- **optcg-api (arjunkai)** — Community One Piece TCG API. ~99.6% price coverage via TCGPlayer + dotgg.gg + Firecrawl fallback. Data endpoints gated to opbindr.com, request key for dev use.
- **one-piece-api.com** — Cardmarket (EU) + TCGPlayer (US) prices for One Piece.

**Recommendation for Metagross:** JustTCG as primary (Pokemon + OP condition-specific), PriceCharting as fallback for sealed. tcgapi.dev if you want breadth without commercial license constraints.

---

## 2. Non-TCG pricing sources

**TL;DR:** No clean official APIs for watches, PH marketplaces, cars, or property. Everything routes through Apify actors ($1-5 per 1,000 records) or Firecrawl structured extraction. Costs are trivial at personal-tracker volume.

### Watches
- **Chrono24** — No public API. Best route is Apify's `memo23/chrono24-scraper` which uses the official mobile JSON API (structured, resilient to redesigns, no Cloudflare wall). Alternative: Parse.bot Chrono24 API.
- **WatchCharts** — No public API. Parse.bot has a wrapper. Better price history than Chrono24 for pre-owned market analysis.
- **ChronoPulse** — Free public index of top 140 watch models across 14 brands. Good baseline for reference-level trends, useless for specific listings.

### Philippine marketplaces (gadgets, TCG local, misc)
- **Carousell PH** — Multiple Apify scrapers ($1-17 per 1,000 listings). `scrapesage/carousell-scraper` is pure HTTP (no browser, fast, cheap at ~$2/1k).
- **Shopee PH** — `gio21/shopee-scraper` covers PH at $5/1k products. Returns price, discount, seller, ratings, stock.
- **Facebook Marketplace** — No sanctioned API. Meta actively blocks scraping. Manual entry is the honest answer here.

### Cars
- **Philkotse** — `rainminer/philkotse-scraper` at $4.48/1k listings. Extracts make, model, price, year, mileage, transmission, location.
- **AutoDeal** — No dedicated actor found; Firecrawl structured extraction works.

### Property
- **Lamudi PH** — Multiple actors, cheapest at $0.70/1k listings (`fatihtahta/lamudi-ph-property-scraper`). Returns price, beds, baths, floor area, coordinates, agent info.
- **DotProperty** — Combined actors with Lamudi (e.g. `pixelperfekt`).
- **Bank foreclosure listings** — Manual only. If you're property-hunting seriously, this is where the deals actually live and no scraper covers them.

### Cost math at your volume
If you own 20 watches, 30 gadgets, 2 cars, 1 property, refreshing prices weekly = ~2,700 records/year. At even $5/1k, that's $13.50/year across the whole non-TCG universe. Cost isn't the constraint. Reliability and maintenance are.

---

## 3. Scraping approach

**TL;DR:** Apify-hosted actors for maintenance-hostile targets (Chrono24, Carousell, Shopee, Lamudi, Philkotse). Firecrawl for one-off structured extraction from any URL. Skip Scrapy/Playwright/Scrapling for this project — you'd own the maintenance yourself, and personal-tracker volume doesn't justify it.

### The tradeoff

Every scraper in your codebase is a liability. Sites change layout every 3-6 weeks. On average, budget a weekend of repair per scraper per quarter. If you self-host Scrapy or Playwright spiders, that weekend is yours. If you use Apify actors, it's the actor developer's.

**VGC analogy:** Building your own scraper stack is like teching a niche move on every Pokemon "just in case." Apify actors are the equivalent of tera'ing into your best coverage type when you need it. Delegate the fragile bits.

### 2026 landscape by tool

- **Scrapy** — Still the production Python default for static/server-rendered pages at scale. Overkill here.
- **Playwright** — Full browser automation, needed for JS-heavy sites. Not needed if you delegate to Apify.
- **Scrapling** — Rising Python library in 2025-2026, adaptive matching that survives HTML structure changes. Interesting for the future, not for MVP.
- **Firecrawl** — AI-powered scraping API. Managed proxies, JS rendering, structured JSON extraction via prompt. $19/mo Hobby = 5,000 credits = ~1,000 structured pages. Good for adhoc "give me the price on this URL" flows.
- **Crawl4AI** — Open-source, LLM-output-oriented. Interesting for future RAG work in Metagross, not this tracker.
- **Apify actors** — Managed actors for specific sites. Pay per record. Zero maintenance on your side.

### Recommendation
- **Primary**: Apify SDK from Python. One `ApifyClient` call per source, results into `price_snapshots`.
- **Fallback**: Firecrawl `/scrape` with a JSON schema for one-off URLs the user pastes ("what's this listing worth").
- **Explicitly not doing**: any self-hosted scraper for MVP. Revisit only if Apify pricing changes or a source needs custom logic.

---

## 4. Task scheduling and background jobs

**TL;DR:** Two viable stacks. (A) ARQ + Redis on Railway for full async task queue. (B) Supabase Cron (pg_cron) triggering Railway HTTP endpoints or Supabase Edge Functions. Given your stack, (B) is simpler for v1; (A) is where you land when scale demands it.

### The options

- **FastAPI BackgroundTasks** — Fire-and-forget same-process tasks. Fine for "after inventory create, notify user." Dies with the process. Not for anything that must survive a restart. Not for scheduled work.
- **ARQ** — Modern asyncio task queue, Redis-backed. Built for FastAPI. Retries, deferred execution, timeouts. ~7x faster than sync RQ. No Flower-style GUI, but Redis-inspectable.
- **Celery** — Battle-tested, multi-broker, mature ecosystem. Overkill for a personal project, and sync/async bridging is friction with FastAPI.
- **Dramatiq** — Simpler than Celery, less feature-rich than ARQ. Skip.
- **APScheduler** — In-process scheduler. Fine if you only need cron-style triggers and single-instance deployment.
- **Supabase Cron (pg_cron)** — Cron jobs stored and executed inside Postgres. Can call SQL functions directly (zero network latency) or hit HTTP endpoints (your FastAPI). Job history in `cron.job_run_details`. Cap: 8 concurrent jobs, 10 min per job.

### Recommendation for v1
Supabase Cron triggers your FastAPI's `/jobs/refresh-prices` endpoint on schedule. FastAPI kicks off the Apify runs, awaits results, writes to `price_snapshots`. Zero extra infra. When the job list grows past a dozen or runtime approaches 10 min, migrate to ARQ + Redis on Railway.

**Why this order:** Adding Redis + a worker process now doubles your deploy surface for no benefit. pg_cron is already there in Supabase.

---

## 5. Money and currency handling

**TL;DR:** Store `Decimal` amounts + ISO 4217 currency codes. Use `py-moneyed` for arithmetic and formatting. Snapshot FX rate at transaction time on `inventory`. Don't auto-convert at read time; render conversions in the portfolio view.

### Why this matters for you specifically
You have PHP, USD, NTD, likely JPY next. If you naively compare a booster box "cost 4,000 NTD" against "current price 250 USD", you'll compute a fake gain. Every monetary value needs a currency alongside it, and every cross-currency compare needs an FX rate with a date.

### Libraries
- **`Decimal`** (stdlib) — Never use `float` for money. Use `Decimal` at the ORM boundary too (Pydantic supports it).
- **`py-moneyed`** — Money class + Currency enum. Prevents accidental cross-currency arithmetic.
- **`py-money` (vimeo)** — Similar, immutable, enforces per-currency decimal precision (JPY has zero, most others two). More rigorous.

### FX rates
- **exchangerate.host** — Free, ECB data, daily rates. Fine for personal use.
- **openexchangerates.org** — Free tier 1,000 req/mo, better coverage.
- **frankfurter.dev** — Free, no API key, ECB-backed.

Store one FX snapshot per day in an `fx_rates` table. Portfolio views join against it.

### Pattern
```
inventory:
  cost_amount: Decimal
  cost_currency: str  (ISO 4217)
  cost_fx_to_php: Decimal   -- rate at purchase time, frozen
  cost_php_snapshot: Decimal -- convenience denorm

fx_rates:
  date, base, quote, rate  -- daily job populates this
```

Portfolio value view = `SUM(quantity * latest_price_in_native_currency * fx_native_to_php_today)`.

---

## 6. Allocation predictor

**TL;DR:** This is inherently per-release logic. Your UPC calculator is the template. Model it as a Strategy interface with concrete classes per store per release. Don't try to generalize into one engine — you'd bake in wrong assumptions.

### What the problem actually is
Store allocation for PH pre-orders (UPC, ETB drops, chase products) has different rules per store and per release:

- **Great Toys** — Tiered by past purchase volume + deposit timing
- **Toys Cave** — First-come-first-served with a per-customer cap
- **GameOne** — Loyalty points + lottery on oversubscribed items
- **International routes** — TAG, Amazon JP, shopping services (different mechanics again)

Each of these is a small function. Given inputs (customer tier, deposit amount, cutoff timestamp, oversubscription ratio), output a probability distribution over "how many will I actually get".

### Approach

**Strategy pattern** (VGC analogy: like separate movesets for the same Pokemon on different teams):

```python
class AllocationStrategy(Protocol):
    release_code: str
    store: str
    def predict(self, inputs: AllocationInputs) -> AllocationPrediction: ...

class AllocationPrediction:
    expected_units: float
    p50_units: int   # 50% chance of at least this many
    p90_units: int
    p10_units: int
    confidence: float
    explanation: list[str]  # human-readable reasoning
```

For MVP, most strategies can be closed-form heuristics you already know from experience. Later, if you record actual allocations vs predictions, you can:

- Fit a **beta-binomial** for FCFS caps (models the "did I get in the window" probability)
- Fit a **logistic regression** for tier-based systems (tier + deposit + prior spend → allocation odds)
- Use **Monte Carlo** simulation for lottery systems (simulate 10,000 draws)

But don't build the ML layer until you have real allocation-outcome data. First version is domain heuristics, and that's fine.

### Key data table
```
allocation_outcomes:
  release_code, store, predicted_units, actual_units, inputs_json, captured_at
```
Every actual outcome you record makes your next-release model better. This is the compounding value.

---

## 7. Architecture fit with your existing stack

**TL;DR:** FastAPI on Railway, Supabase Postgres, Supabase Cron for scheduling, Apify SDK for scraping, py-moneyed for money, Metagross as external service. No new heavy infrastructure. All plays to your strengths.

### Concrete layout

```
tracker-api (FastAPI on Railway)
├── /inventory, /pre_orders, /storage endpoints
├── /prices/latest, /prices/history
├── /jobs/refresh-prices        <- called by pg_cron
├── /jobs/refresh-fx            <- called by pg_cron
├── /allocations/predict
├── strategies/                 <- per-release allocation code
│   ├── base.py
│   ├── upc_2026_11.py
│   └── ...
├── sources/                    <- pricing adapters
│   ├── metagross.py            <- TCG via your API
│   ├── apify_chrono24.py
│   ├── apify_carousell.py
│   ├── apify_shopee.py
│   ├── apify_lamudi.py
│   ├── apify_philkotse.py
│   ├── firecrawl_url.py        <- adhoc URL pricing
│   └── manual.py               <- user-submitted prices
└── money/
    ├── fx.py                   <- rate fetching + caching
    └── conversion.py

supabase (Postgres + pg_cron + Vault for secrets)
├── schema per SPEC
└── cron.jobs -> HTTP calls to tracker-api

apify (managed scraping)
└── existing actors, no custom code

metagross (Next.js, existing)
└── TCG catalog + CV + prices per API_CONTRACT.md

n8n (you already run this)
└── optional: user-facing alert flows
```

### Why n8n stays
You already run n8n. Instead of building a full alerts subsystem in v1, wire a webhook from tracker-api ("price crossed threshold X") into n8n, and let n8n send you the SMS / email / Slack / Telegram. This is a genuine shortcut, not scope creep.

### What's deliberately not in v1
- No Redis (add when ARQ becomes necessary)
- No custom scrapers (Apify covers it)
- No mobile app (PWA on Next.js later, or reuse Metagross UI shell)
- No auth beyond Supabase Auth defaults
- No shared library between Metagross and tracker (a shared package tempts you to couple them; keep the API contract as the seam)

---

## 8. Frontend consideration

**TL;DR:** Skip a dedicated UI in v1. Use Supabase Studio + a few SQL views for inventory browsing. If that becomes annoying fast (it will, within weeks), add a Next.js dashboard as v1.5. Don't build UI and backend at once.

For eventual UI, you already have Next.js in Metagross. Options:
- **Add tracker as a route in Metagross** — Single deployment, shared auth. Couples the two projects visually.
- **Separate Next.js app** — Cleaner separation, matches the service split. Two deploys.
- **Retool / Appsmith** — Internal-tool builders. Faster than hand-coding CRUD screens. Fine for personal use.

I'd bet on separate Next.js app. Shopping the Metagross UI shell (components, auth) into a new app takes half a day and keeps identities separate.

---

## 9. Cost estimate (annual)

| Layer | Service | Cost |
|-------|---------|------|
| Backend | Railway (Hobby, $5 credit) | ~$60/yr |
| Database | Supabase Free tier | $0 |
| Scraping | Apify (personal volume) | ~$20/yr |
| Firecrawl (optional) | Hobby | $228/yr |
| TCG pricing | JustTCG free tier or PriceCharting | $0-$100/yr |
| FX rates | Frankfurter (free) | $0 |
| **Total realistic** | | **~$100-400/yr** |

Firecrawl is the only meaningful line item. Skip it if adhoc URL pricing isn't a real need.

---

## 10. Open questions this research surfaced

1. **Metagross scope confirmation** — does it already handle non-Pokemon TCG (OP), or only Pokemon? Determines whether JustTCG needs to be added there.
2. **Historical price backfill** — for items you already own, do you want to backfill price history from Apify sales-history endpoints, or start "clean" from now?
3. **Alert channels** — SMS via Semaphore/Twilio (PH friendly), Telegram, or just email? Cheapest is Telegram bot; SMS costs per message.
4. **Grading integration** — does Metagross expose PSA/BGS pop reports? Grading changes value 5-10x on TCG singles; if not in scope, this project treats grade as a manual field.
5. **Multi-user or single-user?** — RLS in Supabase costs almost nothing to add now, expensive to retrofit later. If there's any chance you share this with your partner or a friend, add auth + RLS from day one.

---

## Recommendation snapshot

Ship v1 with: FastAPI + Supabase + Apify SDK + Supabase Cron + py-moneyed + Metagross client. No Redis, no self-hosted scrapers, no ML. Skip UI for two weeks. Get pricing, inventory, and one allocation strategy working end-to-end before adding anything else.
