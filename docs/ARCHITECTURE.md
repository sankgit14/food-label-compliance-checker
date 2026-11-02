# Runtime architecture

The local Compose stack has six always-on services, plus an on-demand Locust load-test profile:

| Service | Responsibility | State / dependency |
| --- | --- | --- |
| `corpus-init` | Extracts the tracked regulation PDFs into page and chunk indexed JSONL. | Runs once per `docker compose up --build`; writes the `corpus-data` volume. |
| `api` | Validates submissions, persists them, serves run status, corpus search, readiness, and Prometheus gauges. | Reads `corpus-data`; writes SQLite and quarantine files in `app-state`. |
| `worker` | Claims durable runs, runs Discovery then Verification, checks citation source/page/chunk/quote, and stores the retrieval-only report. | Shares `app-state`; renews its lease while a run is active. |
| `prometheus` | Scrapes API and Jaeger metrics every 15 seconds. | Stores local time series in `prometheus-data`. |
| `jaeger` | Receives OpenTelemetry spans from the API and worker and provides the trace UI. | In-memory local demo storage; traces are not retained after restart. |
| `grafana` | Displays review, latency, corpus, and feedback metrics. | Uses the provisioned Prometheus datasource and `grafana-data`; anonymous access is read only for local use. |
| `locust` profile | Submits a request and polls it through terminal status to measure end-to-end latency. | Run on demand with `docker compose --profile load run --rm locust ...`. |

The queue is SQLite with WAL and atomic claims. It is suitable for a single-host demonstration, not multiple hosts or high write concurrency. The API and worker must use the same local state volume. Worker leases expire after three minutes without a heartbeat and can be reclaimed up to three attempts.

The model client defaults to a deterministic local stub. An OpenAI-compatible endpoint can be configured through environment variables; outbound connectivity and provider credentials are deployment-specific. Calls use a bounded timeout, retries, and a circuit breaker. Agent runs also have wall-clock, step, and tool-call limits. OpenTelemetry spans cover API routes, model calls, tools, and each run. `run_id` is the correlation ID in spans, worker logs, queue state, and the persisted audit trace. Model step records include prompt version, latency, token usage, retry count, and configured cost estimate. Values returned by request-field lookup are hashed in the persisted trace.

The API exports request and complete-run latency summaries, run throughput and failures, per-agent model-call durations and success counts, per-tool calls and latency, token/cost totals, feedback totals, retrieval-cache operations, corpus freshness, and ingestion throughput. Jaeger stores trace data for local inspection. SQLite-backed aggregate metrics are for this local demonstration, not a high-volume telemetry store.

## Data boundaries

- PDFs and generated corpus are read only by the API and worker after `corpus-init` completes.
- SQLite queue state and rejected-request quarantine files are local volume data and should be retained and access-controlled together.
- The quarantine file may contain submitted label content. Secret-like fields are redacted; the file is excluded from Git.
- No model prompt or output can establish legal applicability. Reports remain `evidence_retrieval_only` and route to a professional reviewer.
- The source PDFs are retrieval inputs; legal use requires checking the current Gazette text and effective dates.
