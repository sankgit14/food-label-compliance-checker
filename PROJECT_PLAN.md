# Project completion plan

This plan translates the assignment brief into reviewable implementation stages. The brief is the source of project requirements; `PROJECT_CONTEXT.md` is historical handoff context and is not proof that a feature or regulatory fact is current. Regulatory rules and effective dates require verification against official Gazette sources before they are used to decide a finding.

## Current baseline

| Area | Current state |
| --- | --- |
| REST API and request validation | Present: `/health` and `POST /api/v1/validate-input` |
| Corpus | 14 source PDFs tracked under `data/raw/`; no checked-in processed index |
| Ingestion | Run successfully: 14 PDFs, 254 text pages, 597 chunks, zero failed PDFs; source hashes, extraction gaps, and build throughput are recorded |
| Retrieval | Present: shared TF-IDF component and `POST /api/v1/regulations/search`; CLI diagnostic remains focused on Advertising and Claims |
| Asynchronous run and status API | Present: SQLite queue, separate worker, submit and poll endpoints; report is retrieval-only |
| Multi-agent orchestration and agent-selected tools | LangGraph Discovery and Verification roles with four tools and bounded steps/calls; exercised in successful local protein-claim workflow |
| Evidence verification, findings, and escalation | Source/page/chunk/quote citations verified; protein workflow returned evidence from both families; every report still escalates because legal applicability is unresolved |
| Version-aware corpus manifest and evaluation set | 14-file provenance manifest and five source-page retrieval cases added; effective dates/applicability and human validation of the gold set remain unresolved |
| Docker Compose, queue, telemetry, dashboard | Six-service Compose definition parses; SQLite queue with leases; Prometheus, Jaeger, Grafana configured; local Compose runtime unavailable because Docker daemon is absent |
| Runbook, incident log, evaluation report | Retrieval evaluation and Locust runs completed and documented; runbook includes runtime limits and reproduction steps |

## Delivery order

### Stage 0 — Keep the project runnable (complete locally)

- Publish a concise setup guide and document the current API accurately.
- Keep credentials out of Git and preserve `data/raw/`; generated data remains reproducible.
- Establish the smallest working end-to-end demonstration before broadening scope. **Complete:** protein-claim example submitted, processed, citation-checked, and routed for human review.

### Stage 1 — Evidence-backed demo path (complete for the selected claim)

- Upgrade the initial versioned request/response contract and asynchronous review-run submission/polling into the complete evidence-backed workflow.
- Add corpus search, clause lookup, and request-field lookup tools.
- Validate the LangGraph workflow's bounded Discovery-to-Verification handoff and tool selection in the runnable environment.
- Retrieve provisions for both label declarations and detected claims; verify every returned citation against retrieved text.
- Return a per-requirement finding and route to `clear-for-print`, `revise-and-recheck`, or `regulatory-review`. These are workflow recommendations, not legal approvals. Escalate when evidence, applicability, or verification is unresolved.
- Demonstrate the assignment's “source of protein” case using verified passages from both relevant regulation families. Do not encode the historical thresholds in the handoff as rules without official-source verification.

### Stage 2 — Corpus and evaluation quality

- Inventory every PDF with stable identity, title, source type, dates, category, verification status, and official source URL.
- Keep compendia as convenient retrieval snapshots only: FSSAI states they are ready-reference documents, not legal documents. Confirm relevant text and effective dates against Gazette notifications and applicable official directions.
- Improve extraction around headings and tables; report pages with no text and preserve page-level provenance.
- Human-review and finalize the compact source-page retrieval set spanning nutrition declarations, ingredients, allergens, veg/non-veg marking, and nutrition claims; run it and report retrieval metrics.
- Measure evidence retrieval at top-k and require citation resolution before an answer can be returned. **Complete for the current small diagnostic:** recall@5 improved from 0.50 to 1.00; expected cases still need domain review.

### Stage 3 — Operational service

- Retain the SQLite queue for the local demo; worker lease heartbeats, bounded lease-recovery attempts, provider timeouts/retries/circuit breaker are implemented. Caching and per-client rate limiting remain open.
- Run at least four Docker Compose services with declared dependencies and health checks; scale workers independently and measure whether scaling improves throughput.
- Structured worker logs, Prometheus queue/corpus gauges, and a Grafana dashboard are implemented. Distributed traces and request latency histograms remain open.
- Use a delayed stub model for reproducible load tests. Declare the end-to-end p95 SLO before measurement and record throughput, latency, and scaling effect. **Complete locally:** one and three workers measured at five users, plus a 120-user run; details and limits in `docs/LOAD_TEST_REPORT.md`.
- Add a runbook and a real incident entry from development.

### Stage 4 — Final handoff

- Keep README, `.env.example`, evaluation set, runbook, incident log, and report sufficient for a clean-clone demonstration.
- Report what works, what failed, evidence quality limits, evaluation results, p95 target and results, bottlenecks, and cost estimates.
- **Still open:** Rehearse additional demonstration cases for unsupported evidence, failed verification, prompt injection, and provider outage. Invalid-input quarantine is covered by tests; the protein claim is exercised end to end.
- **Still open:** Build and run the Docker Compose stack on a host with an available Docker daemon. This host's Docker CLI has no reachable daemon, so container runtime health checks remain unverified.
- **Still open:** Have regulatory-affairs reviewers validate the corpus, expected retrieval pages, and rule applicability before using results beyond educational demonstration.

## Completion discipline

Do not mark a stage complete based only on code existing. It needs a reproducible demonstration and corresponding evidence in the report. Do not present a search hit, model response, or historical compendium excerpt as a verified legal determination.
