# Food Label Compliance Checker

An educational decision-support service for reviewing packaged-food labels against selected FSSAI regulations. It is intended to surface evidence for a regulatory affairs professional; it does not approve labels for print or provide legal advice.

## Current status

The repository currently provides:

- FastAPI liveness and readiness endpoints, Prometheus gauges, and validated label input.
- A PDF ingestion script that extracts page text into provenance-carrying JSONL chunks.
- A reusable TF-IDF search service exposed as `POST /api/v1/regulations/search`, plus a command-line diagnostic.
- An SQLite-backed durable queue with `POST /api/v1/reviews`, a separate worker process, and `GET /api/v1/reviews/{run_id}` polling.
- A six-service Docker Compose stack with one-shot corpus initialization, API, worker, Prometheus, Jaeger, and Grafana.
- A browser client at `/` for submission, polling, citations, escalation details, and feedback.
- The source PDFs under `data/raw/`.

The queued worker runs a LangGraph Discovery Agent and Verification Agent with tool-selected corpus search, request lookup, clause lookup, and citation resolution. The default deterministic stub works without a provider. The local API, worker, browser UI, queued protein-claim example, tests, and Locust load runs have been exercised. Every report still routes to human review: complete deterministic rule checks and effective-date filtering are not implemented. Invalid submissions are quarantined locally with field errors and secret-like fields redacted. Successful PDF extraction does not establish that the corpus is complete, current, or legally applicable. No compliance conclusion should be drawn from the current API.

## Requirements

- Python 3.11 or newer
- pip

Create an environment and install the dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`.

Copy `.env.example` to `.env` for local configuration. The default `stub` backend needs no credentials. To use a hosted or local OpenAI-compatible model, set `MODEL_BACKEND=openai_compatible`, then provide `MODEL_BASE_URL`, `MODEL_NAME`, and an optional `MODEL_API_KEY` in the untracked `.env` file.

## Run the API

From this directory:

```bash
python -m uvicorn app.main:app --reload
```

The service listens at `http://127.0.0.1:8000`. Open `/` for the web client and `/docs` for the interactive API schema. `GET /health` checks that the API process is responding. `POST /api/v1/validate-input` validates a label request without starting a run. `POST /api/v1/reviews` validates, queues a review, and returns a run ID; poll the returned URL for its retrieval-only report. See [the API contract](docs/API_CONTRACT.md) for request and response examples.

In a second terminal, start the queue worker:

```bash
python -m app.worker
```

To process a single queued run and exit, use the `--once` flag:

```bash
python -m app.worker --once
```

## Run the test suite

Run the automated tests using `pytest`:

```bash
pytest
```

All unit and integration tests are configured via `pytest.ini`.

For end-to-end load testing, use Locust:

```bash
locust -f load/locustfile.py --host http://127.0.0.1:8000
```

For the containerized demo, run `docker compose up --build`. Compose builds the image, ingests the PDFs once, waits for corpus initialization before starting the API and worker, and starts Prometheus, Jaeger, and Grafana. Open the web client at `http://localhost:8000`, Prometheus at `http://localhost:9090`, Jaeger at `http://localhost:16686`, and Grafana at `http://localhost:3000`. Grafana has anonymous read-only access for local use; do not expose the stack publicly. See [runtime architecture](docs/ARCHITECTURE.md) and [runbook](docs/RUNBOOK.md).

## Build and search the regulation text corpus

Extract text from the PDFs into `data/processed/regulatory_chunks.jsonl`. The ingestion run also writes `data/processed/regulatory_index_metadata.json` with the source hashes, extraction gaps, chunk count, build time, and throughput:

```bash
python scripts/ingest_regulations.py
```

Run the lexical search diagnostic:

```bash
python scripts/search_regulations.py
```

Run the source-page retrieval evaluation:

```bash
python scripts/evaluate_retrieval.py --top-k 5
```

The expected sources and pages are in `data/evaluation/retrieval_cases.jsonl`. These cases measure retrieval only; claim-rule applicability and the RDA basis still need regulatory review. [The evaluation report](docs/EVALUATION_REPORT.md) records the baseline and updated retrieval results.

The current search script focuses on Advertising and Claims documents and reports source path and page for each result. The API search endpoint searches both regulation families unless a category is specified. Treat all results as research leads until document versions and applicability have been verified. Generated files under `data/processed/` are ignored by Git and can be recreated from `data/raw/`.

The API search endpoint requires the generated corpus and returns HTTP 503 with setup guidance if it has not been built. Example request:

```json
{
  "query": "source of protein claim conditions",
  "top_k": 5,
  "category": "advertising_claims"
}
```

## Repository layout

```text
app/                 FastAPI application, agents, queue, and request schemas
web/                 Browser client UI (HTML, CSS, JS)
data/raw/            Source regulation PDFs
data/processed/      Generated extraction output (ignored by Git)
data/evaluation/     Curated retrieval evaluation cases
scripts/             PDF ingestion, search diagnostics, and evaluation
tests/               Automated test suite (API, reviews, agents, quarantine)
deploy/              Prometheus and Grafana provisioning
load/                Locust load-testing workload
docs/                Architecture, API contract, runbook, and evaluation reports
compose.yaml         Local six-service deployment and optional Locust profile
pytest.ini           Test runner configuration
```

## Project scope and safety

The assignment targets an asynchronous, locally runnable service with bounded agent runs, cited findings, verification, escalation when evidence is insufficient, and operational visibility. See [PROJECT_PLAN.md](PROJECT_PLAN.md) for the implementation roadmap and current gaps.

See the [local runbook](docs/RUNBOOK.md) for corpus and API troubleshooting and the [incident log](docs/INCIDENT_LOG.md) for an observed development environment issue.

Regulatory material can change and may have different effective dates. Verify the applicable Gazette text and effective date before using any provision in an assessment. The tool must distinguish retrieved text from interpretation, expose uncertainty, and route unresolved cases to a human reviewer.

## Source data

The PDFs in `data/raw/` are retained as project inputs. Confirm redistribution rights and source authenticity before publishing or sharing the repository outside the team.

The current file inventory is in [`data/regulatory_manifest.json`](data/regulatory_manifest.json). It records provenance but deliberately leaves legal applicability unresolved. FSSAI describes compendia as ready-reference material rather than legal documents; verify provisions and effective dates against Gazette notifications and applicable official directions.
