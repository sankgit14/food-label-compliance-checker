# Local runbook

This runbook covers the local Python workflow and six-service Docker Compose demonstration. Reports are evidence retrieval only and always require a regulatory professional's review.

## Start the API

From the repository root, activate the project environment and run:

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Check `GET /health`. A 200 response confirms only that the API process is serving.

`GET /ready` checks the corpus and SQLite queue. Prometheus scrapes `/metrics`; Grafana displays review latency, queue, agent, and corpus indicators. Jaeger at port 16686 displays spans correlated by the review run ID.

## Search returns HTTP 503

The API loads the processed corpus on its first search. Build it with:

```bash
python scripts/ingest_regulations.py
```

Inspect `data/processed/regulatory_index_metadata.json`. Confirm that the document count and source hashes look expected, `failed_documents` is zero, and the list of `pages_without_text` has been reviewed. Rebuild after changing files under `data/raw/`.

If ingestion reports `No module named pypdf`, activate the project virtual environment and reinstall the declared dependencies:

```bash
python -m pip install -r requirements.txt
```

If some pages have no extractable text, check whether the PDF is scanned. The current pipeline does not perform OCR; add and review OCR output before treating those pages as searchable.

## Search returns no results

- Confirm that a query has at least one term present in the indexed text.
- Retry without a category filter to search both regulation families.
- Check the source pages directly. Lexical retrieval can miss relevant wording and is not evidence that no rule exists.
- If a relevant provision is absent, record the retrieval failure and add a curated evaluation case before changing the search logic.

## File or JSON errors

Preserve the raw PDFs. Check the ingestion console output and per-document metadata, correct the source or parser issue, then rebuild the processed corpus. Do not edit the generated JSONL by hand; it will be replaced on the next ingestion run.

## Rejected API requests

HTTP 422 responses include a request ID and field-level errors. The redacted request is appended to `data/quarantine/rejected_records.jsonl`, which is ignored by Git because it can contain label text. Review access and retention with the project team before sharing the local state directory. Correct the payload and submit it again; quarantined entries are not automatically retried.

## Docker Compose

Run `docker compose up --build` from the repository root. `corpus-init` must complete before the API and worker start. The first build needs Docker access to the Python package index and container registries. The web client, Prometheus, Jaeger, and Grafana are published on ports 8000, 9090, 16686, and 3000. Grafana has anonymous read-only access for local demonstration; do not expose this stack publicly.

To rebuild the generated index after changing a PDF, remove only the `corpus-data` volume and start Compose again:

```bash
docker compose down
docker volume rm food-label-compliance-checker_corpus-data
docker compose up --build
```

Check `/ready` and Prometheus Targets when a service does not become healthy. Inspect logs with `docker compose logs corpus-init api worker prometheus jaeger grafana`. A failed `corpus-init` blocks API and worker startup; resolve the parser or dependency error, then rerun Compose.

## Load test and SLO

The service-level objective is **p95 submission-to-terminal-result latency below 30 seconds at five concurrent users**. The clock starts before `POST /api/v1/reviews` and stops only after polling returns `succeeded` or `failed`; this target is chosen to keep a label review within the brief's tens-of-seconds workflow. The stub adds configurable delay per model step and avoids provider rate limits. This target was declared before the Locust load runs.

Local Python load runs completed with five concurrent users, a 0.1-second stub delay, and 45-second Locust windows. One worker completed 51 workflows (p95 4.2s, 1.18 workflows/s); three workers completed 156 (p95 1.3s, 3.54 workflows/s). A separate 120-user run with three workers completed 107 workflows without Locust failures; p95 was 25s, below the target. CSVs are under `docs/load-results/`; the summary and limits are in `docs/LOAD_TEST_REPORT.md`.

These runs used the local Python API and workers, not Compose. To reproduce on this host, start the API and workers as described in the README, then run Locust directly. Example for one worker:

```bash
REVIEWS_PER_CLIENT_PER_MINUTE=1000 STUB_DELAY_SECONDS=0.1 .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
.venv/bin/python -m app.worker
.venv/bin/locust -f load/locustfile.py --headless --users 5 --spawn-rate 1 --run-time 45s --host http://127.0.0.1:8000 --csv docs/load-results/one-worker --csv-full-history
```

Run two additional workers in separate terminals against the same SQLite DB, then repeat with the same users, spawn rate, duration, and model delay:

```bash
.venv/bin/python -m app.worker
.venv/bin/python -m app.worker
.venv/bin/locust -f load/locustfile.py --headless --users 5 --spawn-rate 1 --run-time 45s --host http://127.0.0.1:8000 --csv docs/load-results/three-workers --csv-full-history
```

Locust records `review submit-to-result` as a separate workflow measurement. Report its p50/p95 and completed runs per second from the CSV; API request latency alone is not the service SLO. The 120-user run remained below the p95 target, but its 25-second p95 leaves little headroom. It is one local run, not a production capacity guarantee. SQLite write contention and sequential model steps are possible bottlenecks; confirm with profiling before claiming a cause.

Compose syntax validation passes, but this checkout has no reachable Docker daemon and Docker Desktop is unavailable, so the container stack has not been built or runtime-verified. The local Python API, workers, UI, and Locust runs are verified independently. Build the Compose stack on a host with Docker Engine or Docker Desktop before relying on the container health checks.

## Model provider failure

The default local stub has no provider dependency. For an OpenAI-compatible endpoint, configure `MODEL_BACKEND`, `MODEL_BASE_URL`, `MODEL_NAME`, and optionally `MODEL_API_KEY` in `.env` before starting Compose. Calls have bounded timeouts and retries; a circuit breaker rejects calls while open. If the provider cannot be reached before the bounded agent limit, the worker stores a retrieval-only fallback where possible and records the workflow failure in execution metadata. Review the worker logs and report before retrying.
