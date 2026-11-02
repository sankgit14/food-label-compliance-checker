"""Configurable chat-model transport with bounded retries and a breaker."""

import asyncio
import json
import os
import time
from typing import Any

import httpx

from app.review_workflow import detect_claim_phrases


class ModelUnavailableError(RuntimeError):
    pass


class CircuitOpenError(ModelUnavailableError):
    pass


class ChatModelClient:
    def __init__(self) -> None:
        self.backend = os.getenv("MODEL_BACKEND", "stub").strip().lower()
        self.base_url = os.getenv("MODEL_BASE_URL", "").strip().rstrip("/")
        self.model = os.getenv("MODEL_NAME", "").strip()
        self.api_key = os.getenv("MODEL_API_KEY", "").strip()
        self.timeout_seconds = float(os.getenv("MODEL_TIMEOUT_SECONDS", "30"))
        self.max_retries = int(os.getenv("MODEL_MAX_RETRIES", "2"))
        self.breaker_threshold = int(os.getenv("MODEL_BREAKER_THRESHOLD", "3"))
        self.breaker_reset_seconds = float(
            os.getenv("MODEL_BREAKER_RESET_SECONDS", "30")
        )
        self._consecutive_failures = 0
        self._opened_at: float | None = None

    async def complete(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        if self.backend == "stub":
            delay = max(float(os.getenv("STUB_DELAY_SECONDS", "0")), 0.0)
            if delay:
                await asyncio.sleep(delay)
            return self._stub_response(context)
        if self.backend != "openai_compatible":
            raise ModelUnavailableError("Unsupported model backend configuration")
        if not self.base_url or not self.model:
            raise ModelUnavailableError(
                "MODEL_BASE_URL and MODEL_NAME are required for the configured backend"
            )

        if (
            self._opened_at is not None
            and time.monotonic() - self._opened_at < self.breaker_reset_seconds
        ):
            raise CircuitOpenError("Model provider circuit is open")

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": 0,
        }
        url = f"{self.base_url}/chat/completions"
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout_seconds
                ) as client:
                    response = await client.post(url, headers=headers, json=body)
                if response.status_code == 429 or response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        "Transient model provider response",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                payload = response.json()
                message = payload["choices"][0]["message"]
                self._consecutive_failures = 0
                self._opened_at = None
                return {
                    "content": message.get("content") or "",
                    "tool_calls": message.get("tool_calls") or [],
                    "usage": payload.get("usage") or {},
                    "model": payload.get("model") or self.model,
                    "retry_count": attempt,
                }
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                last_error = exc
                retryable = not isinstance(exc, httpx.HTTPStatusError) or (
                    exc.response.status_code == 429 or exc.response.status_code >= 500
                )
                if not retryable:
                    break
                if attempt < self.max_retries:
                    await asyncio.sleep(min(0.5 * (2**attempt), 4.0))
            except (ValueError, KeyError, IndexError) as exc:
                last_error = exc
                break

        self._consecutive_failures += 1
        if self._consecutive_failures >= self.breaker_threshold:
            self._opened_at = time.monotonic()
        error_name = type(last_error).__name__ if last_error else "UnknownError"
        raise ModelUnavailableError(
            f"Model provider call failed ({error_name})"
        ) from last_error

    @staticmethod
    def _stub_response(context: dict[str, Any]) -> dict[str, Any]:
        """Deterministic local policy used only when no model is configured."""
        stage = context.get("agent_stage", "discovery")
        tools = {tool.get("name"): tool for tool in context.get("tools", [])}
        history = context.get("tool_history", [])
        request = context.get("request", {})
        call_offset = 0

        def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            nonlocal call_offset
            call_offset += 1
            return {
                "id": f"stub-{len(history) + call_offset}-{name}",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(arguments),
                },
            }

        if stage == "discovery":
            used_request_lookup = any(
                item.get("tool") == "request_lookup" for item in history
            )
            if not used_request_lookup:
                return {
                    "content": "",
                    "tool_calls": [
                        call("request_lookup", {"field": "label_text"}),
                        call("request_lookup", {"field": "nutrition"}),
                        call("request_lookup", {"field": "package"}),
                    ],
                    "model": "stub",
                }
            used_searches = {
                (
                    item.get("arguments", {}).get("claim", ""),
                    item.get("arguments", {}).get("category"),
                )
                for item in history
                if item.get("tool") == "corpus_search"
            }
            pending = []
            claims = detect_claim_phrases(request.get("label_text", ""))
            if not claims:
                claims = [""]
            for claim in claims:
                if "protein" in claim.casefold():
                    searches = (
                        (
                            "advertising_claims",
                            "source protein Schedule I claim conditions RDA per 100 g",
                        ),
                        (
                            "labelling_display",
                            "nutritional information energy value amounts protein carbohydrate total sugars declaration shall label",
                        ),
                    )
                elif claim:
                    searches = (
                        ("advertising_claims", f"{claim} conditions nutrition health claim"),
                        ("labelling_display", f"{claim} nutrition information declaration"),
                    )
                else:
                    searches = (
                        ("labelling_display", "label declarations ingredients allergen nutrition veg non-veg"),
                    )
                for category, query in searches:
                    if (claim, category) not in used_searches:
                        pending.append(
                            call(
                                "corpus_search",
                                {
                                    "query": query,
                                    "category": category,
                                    "claim": claim,
                                    "top_k": 5,
                                },
                            )
                        )
            if pending:
                return {"content": "", "tool_calls": pending, "model": "stub"}
            evidence = [
                item.get("result")
                for item in history
                if item.get("tool") == "corpus_search" and item.get("result")
            ]
            return {
                "content": json.dumps(
                    {"summary": "Candidate provisions retrieved", "evidence": evidence}
                ),
                "tool_calls": [],
                "model": "stub",
            }

        citations = context.get("candidate_citations", [])
        attempted = {
            (
                item.get("arguments", {}).get("document_id"),
                item.get("arguments", {}).get("source_file"),
                item.get("arguments", {}).get("page"),
                item.get("arguments", {}).get("chunk_index"),
            )
            for item in history
            if item.get("tool") == "citation_verify"
        }
        pending = [
            citation
            for citation in citations
            if (
                citation.get("document_id"),
                citation.get("source_file"),
                citation.get("page"),
                citation.get("chunk_index"),
            ) not in attempted
        ][:4]
        if pending:
            return {
                "content": "",
                "tool_calls": [
                    call(
                        "citation_verify",
                        {
                            "document_id": item.get("document_id"),
                            "source_file": item.get("source_file"),
                            "page": item.get("page"),
                            "chunk_index": item.get("chunk_index"),
                            "quote": item.get("text", item.get("excerpt", ""))[:200],
                        },
                    )
                    for item in pending
                ],
                "model": "stub",
            }
        verified_ids = sorted(
            {
                item.get("result", {}).get("document_id")
                for item in history
                if item.get("tool") == "citation_verify"
                and item.get("result", {}).get("verified")
                and item.get("result", {}).get("document_id")
            }
        )
        return {
                "content": json.dumps(
                {
                    "verified_document_ids": verified_ids,
                    "workflow_route": "regulatory-review",
                    "reason": "The local stub cannot determine legal applicability; human review is required.",
                }
            ),
            "tool_calls": [],
            "model": "stub",
        }
