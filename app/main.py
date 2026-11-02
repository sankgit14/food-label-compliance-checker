
import logging
import os
from pathlib import Path
import json
import time
from collections import defaultdict, deque
from threading import Lock
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from opentelemetry import trace
from app.retrieval import CorpusUnavailableError, RegulationSearch
from app.quarantine import record_rejection
from app.review_queue import (
    DB_PATH,
    add_feedback,
    enqueue,
    feedback_counts,
    completed_run_telemetry,
    get_run,
    queue_counts,
)
from app.schemas import (
    LabelRequest,
    RegulationSearchRequest,
    ReviewRunResponse,
    ReviewSubmissionResponse,
    FeedbackRequest,
    FeedbackResponse,
)
from app.telemetry import instrument_fastapi

app = FastAPI(
    title="Food Label Compliance Check Service",
    version="0.1.0",
    description="Evidence-based food label compliance findings.",
)
instrument_fastapi(app)
regulation_search = RegulationSearch()
logger = logging.getLogger("food_label.api")
WEB_INDEX = Path(__file__).resolve().parents[1] / "web" / "index.html"
INDEX_METADATA = WEB_INDEX.parents[1] / "data" / "processed" / "regulatory_index_metadata.json"
SERVICE_STARTED = time.monotonic()
REQUEST_OBSERVATIONS: deque[dict[str, Any]] = deque(maxlen=5000)
REQUEST_LOCK = Lock()
RATE_LIMIT = max(int(os.getenv("REVIEWS_PER_CLIENT_PER_MINUTE", "20")), 1)
RATE_LIMIT_WINDOW_SECONDS = 60.0
CLIENT_SUBMISSIONS: dict[str, deque[float]] = defaultdict(deque)
CLIENT_SUBMISSION_LOCK = Lock()


@app.middleware("http")
async def observe_request(request: Request, call_next):
    started = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        route = getattr(request.scope.get("route"), "path", "unmatched")
        observation = {
            "method": request.method,
            "route": route,
            "status": status_code,
            "duration_seconds": time.perf_counter() - started,
        }
        with REQUEST_LOCK:
            REQUEST_OBSERVATIONS.append(observation)


@app.get("/", include_in_schema=False)
def web_client():
    return FileResponse(
        WEB_INDEX,
        media_type="text/html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/ready")
def ready():
    """Check that local durable state can be opened and the corpus is present."""
    try:
        queue_counts()
        checks = {"database_available": os.access(DB_PATH.parent, os.W_OK)}
    except Exception:
        checks = {"database_available": False}
    try:
        regulation_search.chunk_count
        checks["corpus_loaded"] = True
    except CorpusUnavailableError:
        checks["corpus_loaded"] = False
    healthy = all(checks.values())
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "ready" if healthy else "not_ready", "checks": checks},
    )


@app.get("/metrics", response_class=PlainTextResponse)
def metrics():
    """Expose small dependency-free Prometheus gauges for the local demo."""
    counts = queue_counts()
    run_stats = completed_run_telemetry()
    lines = [
        "# HELP food_label_service_up Whether the API can serve requests.",
        "# TYPE food_label_service_up gauge",
        "food_label_service_up 1",
        "# HELP food_label_review_runs Number of review runs by state.",
        "# TYPE food_label_review_runs gauge",
    ]
    for state in ("queued", "running", "succeeded", "failed"):
        lines.append(f'food_label_review_runs{{state="{state}"}} {counts[state]}')
    try:
        corpus_chunks = regulation_search.chunk_count
        corpus_up = 1
    except CorpusUnavailableError:
        corpus_chunks = 0
        corpus_up = 0
    lines.extend(
        [
            "# HELP food_label_corpus_available Whether the extracted corpus is loadable.",
            "# TYPE food_label_corpus_available gauge",
            f"food_label_corpus_available {corpus_up}",
            "# HELP food_label_corpus_chunks Number of loaded searchable text chunks.",
            "# TYPE food_label_corpus_chunks gauge",
            f"food_label_corpus_chunks {corpus_chunks}",
        ]
    )
    lines.extend(
        [
            "# HELP food_label_feedback_total Total reviewer feedback submitted by rating.",
            "# TYPE food_label_feedback_total counter",
        ]
    )
    for rating, count in feedback_counts().items():
        lines.append(f'food_label_feedback_total{{rating="{rating}"}} {count}')
    cache_stats = regulation_search.cache_stats
    lines.extend(
        [
            "# HELP food_label_retrieval_cache_operations_total Retrieval cache hits and misses.",
            "# TYPE food_label_retrieval_cache_operations_total counter",
            f'food_label_retrieval_cache_operations_total{{result="hit"}} {cache_stats["hits"]}',
            f'food_label_retrieval_cache_operations_total{{result="miss"}} {cache_stats["misses"]}',
            "# HELP food_label_retrieval_cache_entries Current retrieval cache entries.",
            "# TYPE food_label_retrieval_cache_entries gauge",
            f"food_label_retrieval_cache_entries {cache_stats['entries']}",
        ]
    )
    http_counts: dict[tuple[str, str, int], int] = defaultdict(int)
    http_durations: dict[tuple[str, str], list[float]] = defaultdict(list)
    with REQUEST_LOCK:
        request_observations = list(REQUEST_OBSERVATIONS)
    for observation in request_observations:
        key = (observation["method"], observation["route"], observation["status"])
        http_counts[key] += 1
        http_durations[(observation["method"], observation["route"])].append(
            observation["duration_seconds"]
        )
    lines.extend(
        [
            "# HELP food_label_http_requests_total API requests observed in this process.",
            "# TYPE food_label_http_requests_total counter",
        ]
    )
    for (method, route, status_code), count in http_counts.items():
        safe_route = route.replace('\\', '\\\\').replace('"', '\\"')
        lines.append(
            f'food_label_http_requests_total{{method="{method}",route="{safe_route}",status="{status_code}"}} {count}'
        )
    lines.extend(
        [
            "# HELP food_label_http_request_duration_seconds API request duration summary.",
            "# TYPE food_label_http_request_duration_seconds summary",
        ]
    )
    for (method, route), durations in http_durations.items():
        safe_route = route.replace('\\', '\\\\').replace('"', '\\"')
        for quantile, value in ((0.5, _quantile(durations, 0.5)), (0.95, _quantile(durations, 0.95))):
            lines.append(
                f'food_label_http_request_duration_seconds{{method="{method}",route="{safe_route}",quantile="{quantile}"}} {value:.6f}'
            )
        lines.append(
            f'food_label_http_request_duration_seconds_count{{method="{method}",route="{safe_route}"}} {len(durations)}'
        )
        lines.append(
            f'food_label_http_request_duration_seconds_sum{{method="{method}",route="{safe_route}"}} {sum(durations):.6f}'
        )
    run_latencies = [item["latency_seconds"] for item in run_stats["runs"]]
    lines.extend(
        [
            "# HELP food_label_review_end_to_end_latency_seconds Submission to terminal status latency summary.",
            "# TYPE food_label_review_end_to_end_latency_seconds summary",
        ]
    )
    if run_latencies:
        for quantile in (0.5, 0.95):
            lines.append(
                f'food_label_review_end_to_end_latency_seconds{{quantile="{quantile}"}} {_quantile(run_latencies, quantile):.6f}'
            )
    lines.append(f"food_label_review_end_to_end_latency_seconds_count {len(run_latencies)}")
    lines.append(f"food_label_review_end_to_end_latency_seconds_sum {sum(run_latencies):.6f}")
    lines.extend(
        [
            "# HELP food_label_review_runs_completed_total Completed review runs in the retained telemetry window.",
            "# TYPE food_label_review_runs_completed_total counter",
            f"food_label_review_runs_completed_total {run_stats['completed_count']}",
            "# HELP food_label_review_runs_failed_total Failed review runs in the retained telemetry window.",
            "# TYPE food_label_review_runs_failed_total counter",
            f"food_label_review_runs_failed_total {run_stats['failed_count']}",
            "# HELP food_label_review_throughput_runs_5m Review runs completed in the last five minutes.",
            "# TYPE food_label_review_throughput_runs_5m gauge",
            f"food_label_review_throughput_runs_5m {run_stats['finished_last_five_minutes']}",
        ]
    )
    lines.extend(
        [
            "# HELP food_label_agent_runs_total Total agent stage executions.",
            "# TYPE food_label_agent_runs_total counter",
            "# HELP food_label_agent_success_total Total successful agent stage executions.",
            "# TYPE food_label_agent_success_total counter",
            "# HELP food_label_agent_model_calls_total Total model completions by agent stage.",
            "# TYPE food_label_agent_model_calls_total counter",
            "# HELP food_label_agent_model_call_duration_seconds Agent stage model call duration quantiles.",
            "# TYPE food_label_agent_model_call_duration_seconds summary",
        ]
    )
    for stage in ("discovery", "verification"):
        durations = run_stats["agent_calls"][stage]
        lines.extend(
            [
                f'food_label_agent_runs_total{{agent="{stage}"}} {run_stats["agent_runs"][stage]}',
                f'food_label_agent_success_total{{agent="{stage}"}} {run_stats["agent_success"][stage]}',
                f'food_label_agent_model_calls_total{{agent="{stage}"}} {len(durations)}',
            ]
        )
        if durations:
            lines.append(
                f'food_label_agent_model_call_duration_seconds{{agent="{stage}",quantile="0.5"}} {_quantile(durations, 0.5):.6f}'
            )
            lines.append(
                f'food_label_agent_model_call_duration_seconds{{agent="{stage}",quantile="0.95"}} {_quantile(durations, 0.95):.6f}'
            )
    lines.extend(
        [
            "# HELP food_label_tool_calls_total Total tool calls executed.",
            "# TYPE food_label_tool_calls_total counter",
            "# HELP food_label_tool_call_duration_seconds Tool call duration quantiles in seconds.",
            "# TYPE food_label_tool_call_duration_seconds summary",
        ]
    )
    for tool, calls in run_stats["tool_calls"].items():
        lines.append(f'food_label_tool_calls_total{{tool="{tool}"}} {calls}')
        durations = run_stats["tool_latency_ms"][tool]
        lines.append(
            f'food_label_tool_call_duration_seconds{{tool="{tool}",quantile="0.95"}} {_quantile(durations, 0.95):.6f}'
        )
    lines.extend(
        [
            "# HELP food_label_model_tokens_total Model token usage from completed reviews.",
            "# TYPE food_label_model_tokens_total counter",
            f'food_label_model_tokens_total{{type="prompt"}} {run_stats["prompt_tokens"]}',
            f'food_label_model_tokens_total{{type="completion"}} {run_stats["completion_tokens"]}',
            "# HELP food_label_model_retries_total Provider retry attempts recorded per call.",
            "# TYPE food_label_model_retries_total counter",
            f"food_label_model_retries_total {run_stats['model_retries']}",
        ]
    )
    if run_stats["model_cost_known"]:
        lines.extend(
            [
                "# HELP food_label_model_cost_usd_total Estimated model cost for completed runs.",
                "# TYPE food_label_model_cost_usd_total counter",
                f"food_label_model_cost_usd_total {run_stats['model_cost_usd']:.8f}",
            ]
        )
    try:
        metadata = json.loads(INDEX_METADATA.read_text(encoding="utf-8"))
        from datetime import datetime

        built_at = datetime.fromisoformat(metadata["built_at_utc"]).timestamp()
        lines.extend(
            [
                "# HELP food_label_index_built_timestamp_seconds Unix timestamp of the latest corpus build.",
                "# TYPE food_label_index_built_timestamp_seconds gauge",
                f"food_label_index_built_timestamp_seconds {built_at}",
                "# HELP food_label_index_pages_per_second Corpus ingestion throughput in pages per second.",
                "# TYPE food_label_index_pages_per_second gauge",
                f"food_label_index_pages_per_second {metadata.get('pages_per_second', 0)}",
                "# HELP food_label_index_chunks_per_second Corpus ingestion throughput in chunks per second.",
                "# TYPE food_label_index_chunks_per_second gauge",
                f"food_label_index_chunks_per_second {metadata.get('chunks_per_second', 0)}",
                "# HELP food_label_index_source_documents Number of source documents in the latest build.",
                "# TYPE food_label_index_source_documents gauge",
                f"food_label_index_source_documents {metadata.get('documents_discovered', 0)}",
            ]
        )
    except (OSError, ValueError, KeyError, TypeError):
        pass
    lines.extend(
        [
            "# HELP food_label_service_uptime_seconds API process uptime.",
            "# TYPE food_label_service_uptime_seconds gauge",
            f"food_label_service_uptime_seconds {time.monotonic() - SERVICE_STARTED:.3f}",
        ]
    )
    return "\n".join(lines) + "\n"


def _quantile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(max(int(round((len(ordered) - 1) * quantile)), 0), len(ordered) - 1)
    return float(ordered[index])


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "food-label-compliance",
    }


@app.post("/api/v1/validate-input")
def validate_input(request: LabelRequest):
    return {
        "accepted": True,
        "message": (
            "Input validation passed. "
            "No compliance determination has been made."
        ),
        "product_name": request.product_name,
        "product_category": request.product_category,
        "agent_run_started": False,
    }


@app.post("/api/v1/regulations/search")
def search_regulations(request: RegulationSearchRequest):
    """Search source passages for use by reviewers and later agent tools."""
    try:
        results = regulation_search.search(
            request.query,
            top_k=request.top_k,
            category=request.category,
        )
    except CorpusUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {
        "query": request.query,
        "category": request.category,
        "results": results,
        "interpretation": (
            "Search results are candidate evidence only. "
            "They do not establish applicability or compliance."
        ),
    }


@app.post(
    "/api/v1/reviews",
    response_model=ReviewSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_review(request: LabelRequest, http_request: Request):
    """Persist a validated request and return immediately with a run ID."""
    forwarded = http_request.headers.get("x-forwarded-for")
    if forwarded:
        client_id = forwarded.split(",")[0].strip()
    elif http_request.client:
        client_id = http_request.client.host
    else:
        client_id = "unknown"
    now = time.monotonic()
    with CLIENT_SUBMISSION_LOCK:
        submissions = CLIENT_SUBMISSIONS[client_id]
        while submissions and now - submissions[0] >= RATE_LIMIT_WINDOW_SECONDS:
            submissions.popleft()
        if len(submissions) >= RATE_LIMIT:
            raise HTTPException(
                status_code=429,
                detail="Review submission rate limit exceeded; retry after one minute.",
                headers={"Retry-After": str(int(RATE_LIMIT_WINDOW_SECONDS))},
            )
        submissions.append(now)
    with trace.get_tracer(__name__).start_as_current_span("review.submit") as span:
        queued = enqueue(request.model_dump(mode="json"))
        span.set_attribute("run.id", queued["run_id"])
        span.set_attribute("app.correlation_id", queued["run_id"])
    return {
        **queued,
        "poll_url": f"/api/v1/reviews/{queued['run_id']}",
    }


@app.get("/api/v1/reviews/{run_id}", response_model=ReviewRunResponse)
def get_review(run_id: str):
    run = get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Review run not found")
    return run


@app.post("/api/v1/feedback", response_model=FeedbackResponse, status_code=201)
def submit_feedback(request: FeedbackRequest):
    feedback = add_feedback(request.run_id, request.rating, request.reason)
    if feedback is None:
        raise HTTPException(
            status_code=409,
            detail="Feedback is accepted only for a completed successful run.",
        )
    return feedback


@app.exception_handler(RequestValidationError)
async def quarantine_invalid_request(
    request: Request, exc: RequestValidationError
):
    request_id = record_rejection(exc.body, exc.errors())
    logger.warning(
        "request_rejected request_id=%s path=%s field_error_count=%d agent_run_started=false",
        request_id,
        request.url.path,
        len(exc.errors()),
    )
    return JSONResponse(
        status_code=422,
        content={
            "request_id": request_id,
            "detail": [
                {
                    "loc": [str(part) for part in error.get("loc", [])],
                    "msg": error.get("msg", "Invalid value"),
                    "type": error.get("type", "validation_error"),
                }
                for error in exc.errors()
            ],
            "agent_run_started": False,
        },
    )
