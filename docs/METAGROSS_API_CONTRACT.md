# Metagross Public API — Collectibles Consumer Contract

**Version:** 0.1 (draft)
**Status:** For review before implementation
**Consumers:** Portfolio tracker (this new project), potentially future clients

## Purpose and scope

Metagross exposes what it already knows about TCG cards and sealed product (identification via computer vision, catalog data, live pricing) as a stable HTTP API. The portfolio tracker consumes this API to avoid rebuilding CV, catalog, and pricing infrastructure.

**In scope for v0.1:**
- Product identification from an image
- Product lookup by ID
- Product search by name, set, SKU
- Latest price per product
- Price history per product
- Batch price fetch (for nightly refresh jobs)

**Out of scope for v0.1:**
- Writes from clients (no client can create products)
- User-specific inventory (that lives in the consumer)
- Non-TCG categories (watches, gadgets, etc.)
- Webhooks and real-time push (see "Future" section)

## Conventions

**Base URL:** `https://api.metagross.<domain>/v1`

**Authentication:** Bearer token in `Authorization` header. Issued out-of-band per client. Tokens scoped to read-only for v0.1.

**Content type:** `application/json` for all requests and responses. `multipart/form-data` for image upload endpoints.

**Timestamps:** ISO 8601 with UTC offset (`2026-09-12T14:30:00Z`).

**Currency:** All prices carry an explicit ISO 4217 code (`USD`, `PHP`, `JPY`, `TWD`). Metagross does not FX-convert. Consumers convert if they need to.

**IDs:** ULIDs as strings. Stable across the product's lifetime.

**Pagination:** Cursor-based via `?cursor=<opaque>&limit=<n>`. Default limit 50, max 200. Response includes `next_cursor` (null when done).

**Errors:** All errors return the shape below with an appropriate HTTP status:

```json
{
  "error": {
    "code": "product_not_found",
    "message": "No product matches the given ID.",
    "details": {}
  }
}
```

## Data models

### Product

```json
{
  "id": "01JEXXX...",
  "game": "pokemon" | "one_piece",
  "category": "single" | "sealed",
  "sealed_type": "booster_box" | "etb" | "upc" | "booster_pack" | null,
  "set_code": "SV10",
  "set_name": "Destined Rivals",
  "sku": "SV10-054",
  "name": "Mega Greninja ex",
  "rarity": "SIR",
  "card_number": "116/162",
  "language": "EN" | "JP" | "TW" | ...,
  "release_date": "2026-11-07",
  "srp": { "amount": 149.99, "currency": "USD" },
  "image_url": "https://cdn.metagross.<domain>/products/01JEXXX.jpg",
  "attributes": {}
}
```

`attributes` is a free-form object for game-specific extras (e.g. `is_promo`, `illustration_type`) that don't fit the core schema. Keep it small and documented.

### PriceSnapshot

```json
{
  "product_id": "01JEXXX...",
  "source": "tcgplayer" | "pricecharting" | "yuyutei" | "cardmarket" | "manual",
  "price": 245.00,
  "currency": "USD",
  "condition": "NM" | "LP" | "MP" | "HP" | "DMG" | "SEALED",
  "grade": {
    "grader": "PSA" | "BGS" | "CGC" | null,
    "grade": "10" | "9.5" | null
  },
  "captured_at": "2026-09-12T14:30:00Z",
  "raw": {}
}
```

`raw` holds source-native fields (e.g. TCGPlayer market vs low vs mid). Consumers can ignore it or use it for detail views.

### IdentificationResult

```json
{
  "candidates": [
    {
      "product_id": "01JEXXX...",
      "confidence": 0.94,
      "matched_attributes": ["set_symbol", "artwork", "card_number"]
    }
  ],
  "scan_id": "01JFYYY..."
}
```

Always returns an array of candidates ranked by confidence. Empty array means no match above threshold.

## Endpoints

### 1. Identify a product from an image

```
POST /identify
Content-Type: multipart/form-data
```

**Fields:**
- `image` (file, required): JPG or PNG, max 8 MB
- `hint_game` (string, optional): `pokemon` or `one_piece` to narrow search
- `hint_category` (string, optional): `single` or `sealed`

**Response 200:** `IdentificationResult`

**Errors:** `413` payload too large, `422` unreadable image, `429` rate limited.

**Notes:** Store scans server-side under `scan_id` for a rolling window (say 30 days) so consumers can reference them in support flows.

### 2. Get a product by ID

```
GET /products/{product_id}
```

**Response 200:** `Product`
**Errors:** `404 product_not_found`

### 3. Search products

```
GET /products?q=<text>&game=<game>&set_code=<code>&category=<category>&cursor=<c>&limit=<n>
```

**Query params (all optional):**
- `q`: free text against name and SKU
- `game`: filter by game
- `set_code`: filter by set
- `category`: `single` or `sealed`
- `language`: filter by print language

**Response 200:**

```json
{
  "items": [Product, ...],
  "next_cursor": "..." | null
}
```

### 4. Get latest price

```
GET /products/{product_id}/price/latest?condition=NM&grader=PSA&grade=10
```

**Query params:**
- `condition` (optional, defaults to `NM` for singles, `SEALED` for sealed)
- `grader`, `grade` (optional, required together if provided)

**Response 200:** `PriceSnapshot`
**Errors:** `404 product_not_found`, `404 no_price_available` (product exists but no price captured yet)

### 5. Get price history

```
GET /products/{product_id}/price/history?condition=NM&from=2026-01-01&to=2026-09-12&granularity=daily
```

**Query params:**
- `condition`, `grader`, `grade`: same as above
- `from`, `to` (ISO date): inclusive range, defaults to last 90 days
- `granularity`: `daily` | `weekly` | `monthly`, defaults to `daily`

**Response 200:**

```json
{
  "product_id": "01JEXXX...",
  "condition": "NM",
  "grade": null,
  "series": [
    { "date": "2026-09-10", "price": 240.00, "currency": "USD", "source": "tcgplayer" },
    ...
  ]
}
```

### 6. Batch latest prices (for nightly refresh)

```
POST /products/prices/batch
Content-Type: application/json
```

**Body:**

```json
{
  "requests": [
    { "product_id": "01JEXXX...", "condition": "NM" },
    { "product_id": "01JEZZZ...", "condition": "SEALED" }
  ]
}
```

Max 500 items per call.

**Response 200:**

```json
{
  "results": [
    { "product_id": "01JEXXX...", "price": PriceSnapshot },
    { "product_id": "01JEZZZ...", "error": { "code": "no_price_available" } }
  ]
}
```

Individual failures don't fail the whole batch. Consumers walk the results array.

## Error codes

| HTTP | Code | Meaning |
|------|------|---------|
| 400 | `invalid_request` | Malformed body or params |
| 401 | `unauthorized` | Missing or invalid token |
| 403 | `forbidden` | Token lacks scope for this resource |
| 404 | `product_not_found` | ID does not match any product |
| 404 | `no_price_available` | Product exists, no price on record |
| 413 | `payload_too_large` | Image over size limit |
| 422 | `unreadable_image` | CV pipeline could not process |
| 429 | `rate_limited` | See `Retry-After` header |
| 500 | `internal_error` | Log the request ID and file an issue |

## Rate limits

Default per token: 60 requests per minute, 5,000 per day. Batch endpoints count as 1 request regardless of item count.

Returned headers:
- `X-RateLimit-Limit`
- `X-RateLimit-Remaining`
- `X-RateLimit-Reset` (unix seconds)

## Versioning

Path-based (`/v1`). Breaking changes bump the version. Additive changes (new optional fields, new endpoints) do not.

Deprecation policy: minimum 60 days notice via `Deprecation` and `Sunset` headers before removing an endpoint.

## Idempotency

`GET` endpoints are naturally idempotent. `POST /identify` accepts an optional `Idempotency-Key` header so retries after a network failure don't spawn duplicate scans.

## Client integration notes (for the portfolio tracker)

**Nightly refresh job:**
1. Query local inventory for TCG items (where `product_source = 'metagross'`).
2. Group by (product_id, condition, grade) to dedupe.
3. Call `POST /products/prices/batch` in chunks of 500.
4. Write results into `price_snapshots`.
5. Flag any `no_price_available` items for manual review.

**Scan flow:**
1. User uploads a photo in the tracker UI.
2. Tracker POSTs to `/identify`.
3. If top candidate confidence is above threshold (say 0.85), auto-fill the product. Otherwise show candidates and ask user to confirm.
4. Save inventory row with `external_product_id = <chosen candidate>` and `product_source = 'metagross'`.

**Caching:**
- `GET /products/{id}` responses can be cached for 24h. Product data rarely changes.
- Price responses should not be cached beyond a few minutes.

## Open questions to resolve before v1.0

1. **User-scoped scans:** should scan_ids be scoped to the calling client, or global? Global is simpler; scoped is safer if Metagross grows a UI.
2. **Manual price overrides:** does Metagross accept `POST /prices` from trusted consumers (e.g. the tracker submitting a PH Shopee price)? If yes, that's a v0.2 feature, not v0.1.
3. **Sealed product SKU standard:** does Metagross use a canonical SKU format, or does it defer to TCGPlayer / PriceCharting IDs? This affects how the tracker deduplicates products across sources.
4. **OP TCG coverage:** which sets does Metagross currently cover for One Piece? If OP-17 isn't in the catalog yet, the tracker needs a "local product" fallback path documented.
5. **Language handling:** if a card exists in EN and JP, are those separate `Product` records or one record with language variants? This is a modeling choice that ripples through the entire schema.

## Future (post-v0.1)

- **Webhooks** for price threshold alerts (`price_dropped_below`, `price_rose_above`).
- **Write endpoints** for trusted consumers to submit manual price observations.
- **Bulk product ingest** for pre-release catalog updates.
- **GraphQL alternative** if consumers start needing partial-field fetches at scale.
