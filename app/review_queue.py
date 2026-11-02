"""SQLite-backed durable queue and state store for local review runs."""

import json
import os
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "state" / "review_runs.sqlite3"
DB_PATH = Path(os.getenv("REVIEW_DB_PATH", str(DEFAULT_DB_PATH)))
MAX_ATTEMPTS = 3
RUN_LEASE_SECONDS = 180


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat()


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=30000")
    return connection


def initialize() -> None:
    with closing(_connect()) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS review_runs (
                run_id TEXT PRIMARY KEY,
                status TEXT NOT NULL CHECK (
                    status IN ('queued', 'running', 'succeeded', 'failed')
                ),
                request_json TEXT NOT NULL,
                result_json TEXT,
                error_code TEXT,
                error_message TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                started_at TEXT,
                heartbeat_at TEXT,
                finished_at TEXT
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS review_runs_queue_idx "
            "ON review_runs(status, created_at)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS review_feedback (
                feedback_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES review_runs(run_id),
                rating TEXT NOT NULL CHECK (
                    rating IN ('satisfactory', 'unsatisfactory')
                ),
                reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )


def enqueue(request: dict[str, Any]) -> dict[str, str]:
    initialize()
    run_id = str(uuid.uuid4())
    created_at = _iso()
    with closing(_connect()) as connection:
        connection.execute(
            """
            INSERT INTO review_runs (
                run_id, status, request_json, created_at
            ) VALUES (?, 'queued', ?, ?)
            """,
            (run_id, json.dumps(request, ensure_ascii=False), created_at),
        )
    return {"run_id": run_id, "status": "queued", "created_at": created_at}


def claim_next() -> dict[str, Any] | None:
    """Atomically lease the oldest queued run to a single worker."""
    initialize()
    now = utc_now()
    stale_before = _iso(now - timedelta(seconds=RUN_LEASE_SECONDS))
    now_text = _iso(now)
    with closing(_connect()) as connection:
        connection.execute("BEGIN IMMEDIATE")
        stale_runs = connection.execute(
            """
            SELECT run_id, attempts FROM review_runs
            WHERE status = 'running' AND heartbeat_at < ?
            """,
            (stale_before,),
        ).fetchall()
        for stale in stale_runs:
            if stale["attempts"] >= MAX_ATTEMPTS:
                connection.execute(
                    """
                    UPDATE review_runs
                    SET status = 'failed', error_code = 'worker_lease_expired',
                        error_message = 'Worker lease expired after maximum attempts',
                        finished_at = ?, heartbeat_at = NULL
                    WHERE run_id = ? AND status = 'running'
                    """,
                    (now_text, stale["run_id"]),
                )
            else:
                connection.execute(
                    """
                    UPDATE review_runs
                    SET status = 'queued', heartbeat_at = NULL
                    WHERE run_id = ? AND status = 'running'
                    """,
                    (stale["run_id"],),
                )

        row = connection.execute(
            """
            SELECT run_id, request_json, attempts FROM review_runs
            WHERE status = 'queued' AND attempts < ?
            ORDER BY created_at, run_id LIMIT 1
            """,
            (MAX_ATTEMPTS,),
        ).fetchone()
        if row is None:
            connection.commit()
            return None

        updated = connection.execute(
            """
            UPDATE review_runs
            SET status = 'running', attempts = attempts + 1,
                started_at = COALESCE(started_at, ?), heartbeat_at = ?,
                error_code = NULL, error_message = NULL
            WHERE run_id = ? AND status = 'queued'
            """,
            (now_text, now_text, row["run_id"]),
        )
        if updated.rowcount != 1:
            connection.rollback()
            return None
        connection.commit()
        return {
            "run_id": row["run_id"],
            "request": json.loads(row["request_json"]),
            "attempt": row["attempts"] + 1,
        }


def heartbeat(run_id: str) -> None:
    with closing(_connect()) as connection:
        connection.execute(
            "UPDATE review_runs SET heartbeat_at = ? "
            "WHERE run_id = ? AND status = 'running'",
            (_iso(), run_id),
        )


def succeed(run_id: str, result: dict[str, Any]) -> None:
    with closing(_connect()) as connection:
        connection.execute(
            """
            UPDATE review_runs
            SET status = 'succeeded', result_json = ?, error_code = NULL,
                error_message = NULL, finished_at = ?, heartbeat_at = NULL
            WHERE run_id = ? AND status = 'running'
            """,
            (json.dumps(result, ensure_ascii=False), _iso(), run_id),
        )


def fail(run_id: str, *, code: str, message: str) -> None:
    with closing(_connect()) as connection:
        connection.execute(
            """
            UPDATE review_runs
            SET status = 'failed', error_code = ?, error_message = ?,
                finished_at = ?, heartbeat_at = NULL
            WHERE run_id = ? AND status = 'running'
            """,
            (code[:100], message[:500], _iso(), run_id),
        )


def get_run(run_id: str) -> dict[str, Any] | None:
    initialize()
    with closing(_connect()) as connection:
        row = connection.execute(
            """
            SELECT run_id, status, result_json, error_code, error_message,
                   attempts, created_at, started_at, finished_at
            FROM review_runs WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "run_id": row["run_id"],
        "status": row["status"],
        "report": json.loads(row["result_json"]) if row["result_json"] else None,
        "error": (
            {"code": row["error_code"], "message": row["error_message"]}
            if row["error_code"]
            else None
        ),
        "attempts": row["attempts"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
    }


def queue_counts() -> dict[str, int]:
    """Return counts for each durable run state for health and metrics."""
    initialize()
    with closing(_connect()) as connection:
        rows = connection.execute(
            "SELECT status, COUNT(*) AS count FROM review_runs GROUP BY status"
        ).fetchall()
    counts = {state: 0 for state in ("queued", "running", "succeeded", "failed")}
    counts.update({row["status"]: row["count"] for row in rows})
    return counts


def add_feedback(run_id: str, rating: str, reason: str) -> dict[str, str] | None:
    """Persist feedback for a completed run; return None if it is not complete."""
    initialize()
    feedback_id = str(uuid.uuid4())
    created_at = _iso()
    with closing(_connect()) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT status FROM review_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None or row["status"] != "succeeded":
            connection.rollback()
            return None
        connection.execute(
            """INSERT INTO review_feedback
               (feedback_id, run_id, rating, reason, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (feedback_id, run_id, rating, reason[:2000], created_at),
        )
        connection.commit()
    return {
        "feedback_id": feedback_id,
        "run_id": run_id,
        "rating": rating,
        "created_at": created_at,
    }


def feedback_counts() -> dict[str, int]:
    initialize()
    with closing(_connect()) as connection:
        rows = connection.execute(
            "SELECT rating, COUNT(*) AS count FROM review_feedback GROUP BY rating"
        ).fetchall()
    counts = {"satisfactory": 0, "unsatisfactory": 0}
    counts.update({row["rating"]: row["count"] for row in rows})
    return counts


def completed_run_telemetry(limit: int = 2000) -> dict[str, Any]:
    """Summarize bounded durable run traces for Prometheus aggregation."""
    initialize()
    with closing(_connect()) as connection:
        rows = connection.execute(
            """SELECT status, created_at, finished_at, result_json
               FROM review_runs WHERE finished_at IS NOT NULL
               ORDER BY finished_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    telemetry: dict[str, Any] = {
        "runs": [],
        "agent_calls": {"discovery": [], "verification": []},
        "agent_success": {"discovery": 0, "verification": 0},
        "agent_runs": {"discovery": 0, "verification": 0},
        "tool_calls": {},
        "tool_latency_ms": {},
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "model_retries": 0,
        "model_cost_usd": 0.0,
        "model_cost_known": True,
        "completed_count": 0,
        "failed_count": 0,
    }
    now = utc_now()
    five_minutes_ago = now - timedelta(minutes=5)
    for row in rows:
        try:
            created = datetime.fromisoformat(row["created_at"])
            finished = datetime.fromisoformat(row["finished_at"])
        except (TypeError, ValueError):
            continue
        latency = max((finished - created).total_seconds(), 0)
        telemetry["runs"].append(
            {
                "status": row["status"],
                "finished_at": finished,
                "latency_seconds": latency,
            }
        )
        if row["status"] == "succeeded":
            telemetry["completed_count"] += 1
        else:
            telemetry["failed_count"] += 1
        if finished >= five_minutes_ago:
            telemetry.setdefault("finished_last_five_minutes", 0)
            telemetry["finished_last_five_minutes"] += 1
        try:
            report = json.loads(row["result_json"] or "{}")
            metadata = report.get("execution_metadata", {})
        except (json.JSONDecodeError, TypeError):
            continue
        stages_seen = set()
        for call in metadata.get("model_trace", []):
            stage = call.get("agent_stage")
            if stage not in telemetry["agent_calls"]:
                continue
            stages_seen.add(stage)
            telemetry["agent_calls"][stage].append(
                call.get("duration_ms", 0) / 1000
            )
            telemetry["prompt_tokens"] += call.get("prompt_tokens") or 0
            telemetry["completion_tokens"] += call.get("completion_tokens") or 0
            telemetry["model_retries"] += call.get("retry_count", 0)
            if call.get("estimated_cost_usd") is None:
                telemetry["model_cost_known"] = False
            else:
                telemetry["model_cost_usd"] += call["estimated_cost_usd"]
        for stage in stages_seen:
            telemetry["agent_runs"][stage] += 1
            if row["status"] == "succeeded" and not metadata.get("workflow_failure"):
                telemetry["agent_success"][stage] += 1
        for call in metadata.get("tool_trace", []):
            tool = call.get("tool", "unknown")
            telemetry["tool_calls"][tool] = telemetry["tool_calls"].get(tool, 0) + 1
            telemetry["tool_latency_ms"].setdefault(tool, []).append(
                (call.get("duration_ms") or 0) / 1000
            )
    telemetry["finished_last_five_minutes"] = telemetry.get(
        "finished_last_five_minutes", 0
    )
    return telemetry
