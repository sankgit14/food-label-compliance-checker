# Development incident log

Record observed failures and their recovery. Do not replace these entries with hypothetical incidents.

## 2026-10-29 — PDF extraction command unavailable in the host environment

- **Symptom:** `pdftotext` was not installed, and the host `python3` did not have `pypdf`; the ingestion command could not be run in that interpreter.
- **Impact:** Corpus ingestion and API search were delayed until the project environment was installed.
- **Cause:** The project dependencies are declared in `requirements.txt`, but there is no active project virtual environment in this checkout.
- **Recovery:** Created `.venv`, installed declared requirements, ran ingestion, and exercised API search and review workflow. Used macOS PDFKit with module caches redirected to `/private/tmp` to inspect local PDF first pages for the source manifest.
- **Status:** Recovered.

## 2026-10-29 — Python package installation blocked by DNS

- **Symptom:** Installing the declared requirements in `.venv` failed while pip attempted to resolve the configured package index host (`nodename nor servname provided`).
- **Impact:** The environment initially lacked the project runtime dependencies, delaying corpus build, API, worker, evaluation, and load checks.
- **Cause:** The current host/network environment could not resolve the package index. The pip output did not establish that any declared version is unavailable.
- **Recovery:** Retried pip installation with package-index network access; dependency installation succeeded. Ingestion, API, worker, evaluation, tests, and local load tests then completed.
- **Status:** Recovered.

## 2026-10-30 — Docker daemon unavailable for Compose runtime validation

- **Symptom:** `docker compose config --quiet` succeeds, but `docker compose up --build` cannot connect to the Docker daemon. The expected Docker Desktop application executable is unavailable on this host.
- **Impact:** Container image build, service startup, health checks, and Compose networking remain unverified. The local Python API, worker, UI, and Locust workflow were run independently.
- **Recovery:** Kept the Python demo runnable locally and documented the exact Compose verification gap in the runbook.
- **Status:** Open pending an available Docker Engine or Desktop installation.
