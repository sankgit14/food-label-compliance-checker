# API contract

Current API version: `v1`. The running OpenAPI document at `/openapi.json` is the machine-readable contract; `/docs` provides interactive exploration.

`GET /` serves the browser client. It submits a review, polls for completion, shows findings, source excerpts, and escalation questions, and posts optional feedback.

## `GET /health`

Returns HTTP 200 when the API process is available:

```json
{"status":"ok","service":"food-label-compliance"}
```

This is a liveness check only. `GET /ready` checks that SQLite state can be opened and the regulation corpus can be loaded. `GET /metrics` exposes Prometheus request and run latency, queue, agent/tool, model usage/cost, feedback, cache, corpus freshness, and ingestion throughput metrics.

## `POST /api/v1/validate-input`

Validates a label request and returns HTTP 200 when the request satisfies the schema. It does not start an agent run or make a compliance determination.

```json
{
  "product_name": "Jackfruit Chips",
  "product_category": "Packaged snack",
  "label_text": "Jackfruit Chips. Ingredients: jackfruit, oil, salt. Source of protein.",
  "ingredients": ["jackfruit", "oil", "salt"],
  "declared_allergens": [],
  "nutrition": {
    "basis": "per_100g",
    "energy_kcal": 450,
    "protein_g": 5,
    "carbohydrates_g": 50,
    "total_fat_g": 25,
    "sodium_mg": 400
  },
  "package": {
    "net_quantity": 100,
    "net_quantity_unit": "g",
    "package_surface_area_cm2": 250,
    "is_single_ingredient_food": false
  }
}
```

`nutrition.basis` is one of `per_100g`, `per_100ml`, or `per_serving`. A `serving_size_g` is required for `per_serving`. Unknown fields are rejected. Numeric values have schema-defined bounds. Package units are `g`, `kg`, `ml`, or `l`.

Malformed or invalid requests receive HTTP 422 with field-level errors and a `request_id`. The redacted request and errors are appended to the local quarantine JSONL file; invalid requests do not enter the review queue.

## `POST /api/v1/regulations/search`

Searches extracted regulation text and returns candidate passages with their source path, page, chunk, family, and lexical similarity score. It returns HTTP 503 if the ingestion output does not exist or cannot be indexed.

```json
{
  "query": "source of protein claim conditions",
  "top_k": 5,
  "category": "advertising_claims"
}
```

`category` may be `labelling_display`, `advertising_claims`, or omitted to search both. `top_k` is 1–20. Similarity is a retrieval ranking signal only; it does not show that a passage applies or supports a compliance finding.

## `POST /api/v1/reviews`

Accepts the same validated request body as `/api/v1/validate-input`, persists it to the local SQLite queue, and returns HTTP 202 without waiting for retrieval:

```json
{
  "run_id": "2a8a66ae-0eb0-4e43-9ca0-406e3dc96eb1",
  "status": "queued",
  "created_at": "2026-10-29T10:00:00+00:00",
  "poll_url": "/api/v1/reviews/2a8a66ae-0eb0-4e43-9ca0-406e3dc96eb1"
}
```

Invalid requests receive HTTP 422 before a row is queued. A separate worker must be running to process accepted runs. The worker runs bounded Discovery and Verification roles with corpus search, clause lookup, request lookup, and source/page/chunk/quote verification tools. All runs still return `evidence_retrieval_only` and route to `regulatory-review`; the system does not decide legal applicability or compliance.

Submissions are rate limited per client. The local default is 20 accepted submissions per minute, configurable with `REVIEWS_PER_CLIENT_PER_MINUTE`.

## `GET /api/v1/reviews/{run_id}`

Returns HTTP 200 with status `queued`, `running`, `succeeded`, or `failed`; unknown IDs return 404. A successful run contains detected phrases, citations that resolve to exact indexed text chunks, unresolved questions, execution metadata, and an explicit notice that a professional must verify the law. It never returns `clear-for-print` or a legal approval in this retrieval-only stage.

## `POST /api/v1/feedback`

Accepts `run_id`, `rating` (`satisfactory` or `unsatisfactory`), and an optional reason up to 2000 characters. Feedback is stored only for a completed successful run and contributes to feedback metrics.
