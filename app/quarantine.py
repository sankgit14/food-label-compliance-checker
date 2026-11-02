"""Local quarantine records for invalid API submissions."""

import hashlib
import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUARANTINE_FILE = (
    PROJECT_ROOT / "data" / "quarantine" / "rejected_records.jsonl"
)
QUARANTINE_FILE = Path(
    os.getenv("QUARANTINE_FILE", str(DEFAULT_QUARANTINE_FILE))
)
WRITE_LOCK = threading.Lock()
SECRET_KEY_PATTERN = re.compile(
    r"(secret|token|password|credential|authorization|api[_-]?key)",
    re.IGNORECASE,
)


def _redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                "[REDACTED]"
                if SECRET_KEY_PATTERN.search(str(key))
                else _redact_secrets(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_secrets(item) for item in value]
    return value


def record_rejection(body: Any, errors: list[dict[str, Any]]) -> str:
    """Persist field errors and a redacted request for offline correction."""
    request_id = str(uuid.uuid4())
    body_bytes = json.dumps(
        body, ensure_ascii=False, sort_keys=True, default=str
    ).encode("utf-8")
    record = {
        "request_id": request_id,
        "received_at": datetime.now(timezone.utc).isoformat(),
        "body_sha256": hashlib.sha256(body_bytes).hexdigest(),
        "rejected_body": _redact_secrets(body),
        "field_errors": [
            {
                "location": [str(part) for part in error.get("loc", [])],
                "message": error.get("msg", "Invalid value"),
                "type": error.get("type", "validation_error"),
            }
            for error in errors
        ],
        "agent_run_started": False,
    }
    QUARANTINE_FILE.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(record, ensure_ascii=False, default=str) + "\n"
    with WRITE_LOCK:
        with QUARANTINE_FILE.open("a", encoding="utf-8") as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
    return request_id
