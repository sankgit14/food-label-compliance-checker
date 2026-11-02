"""Standalone worker for queued label review runs."""

import argparse
import asyncio
import json
import logging
import os
import time

from app.review_queue import claim_next, fail, heartbeat, succeed
from app.agents import run_agent_review
from app.model_client import ChatModelClient
from app.retrieval import RegulationSearch
from app.telemetry import configure_tracing
from opentelemetry import trace

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("food_label.worker")
MODEL_CLIENT = ChatModelClient()
REGULATION_SEARCH = RegulationSearch()
configure_tracing("food-label-worker")
TRACER = trace.get_tracer(__name__)


async def _review_with_heartbeat(run_id: str, request: dict) -> tuple[dict, dict]:
    """Keep the SQLite lease alive while a bounded agent run is in progress."""
    async def pulse() -> None:
        while True:
            await asyncio.sleep(30)
            heartbeat(run_id)

    pulse_task = asyncio.create_task(pulse())
    try:
        return await run_agent_review(
            run_id, request, model=MODEL_CLIENT, search=REGULATION_SEARCH
        )
    finally:
        pulse_task.cancel()
        try:
            await pulse_task
        except asyncio.CancelledError:
            pass


def process_once() -> bool:
    job = claim_next()
    if job is None:
        return False
    run_id = job["run_id"]
    logger.info(
        json.dumps({"event": "review_started", "run_id": run_id, "attempt": job["attempt"]})
    )
    try:
        with TRACER.start_as_current_span("review.run") as span:
            span.set_attribute("run.id", run_id)
            span.set_attribute("app.correlation_id", run_id)
            span.set_attribute("review.attempt", job["attempt"])
            report, diagnostics = asyncio.run(
                _review_with_heartbeat(run_id, job["request"])
            )
        heartbeat(run_id)
        succeed(run_id, report)
        logger.info(
            json.dumps(
                {
                    "event": "review_succeeded",
                    "run_id": run_id,
                    "model_calls": diagnostics["model_calls"],
                    "tool_calls": diagnostics["tool_calls"],
                    "latency_ms": diagnostics["latency_ms"],
                    "workflow_failure": diagnostics["workflow_failure"],
                }
            )
        )
    except Exception as exc:
        fail(
            run_id,
            code="review_worker_error",
            message=f"Review worker failed ({type(exc).__name__}).",
        )
        logger.exception(
            json.dumps({"event": "review_failed", "run_id": run_id})
        )
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--once", action="store_true", help="process at most one queued run"
    )
    args = parser.parse_args()
    poll_seconds = max(float(os.getenv("WORKER_POLL_SECONDS", "1")), 0.1)
    logger.info(json.dumps({"event": "worker_started", "poll_seconds": poll_seconds}))

    while True:
        handled = process_once()
        if args.once:
            return
        if not handled:
            time.sleep(poll_seconds)


if __name__ == "__main__":
    main()
