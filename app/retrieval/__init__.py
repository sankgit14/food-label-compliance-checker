"""Reusable lexical search over the extracted regulation corpus.

Search results are evidence candidates. A similarity score is not a legal
interpretation, a relevance guarantee, or a compliance decision.
"""

import json
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CHUNKS_FILE = (
    PROJECT_ROOT / "data" / "processed" / "regulatory_chunks.jsonl"
)
ALLOWED_CATEGORIES = {"labelling_display", "advertising_claims"}


class CorpusUnavailableError(FileNotFoundError):
    """Raised when ingestion has not produced the search corpus."""


class RegulationSearch:
    """Load and search provenance-carrying regulation text chunks."""

    def __init__(self, chunks_file: Path = DEFAULT_CHUNKS_FILE):
        self.chunks_file = Path(chunks_file)
        self._chunks: list[dict[str, Any]] | None = None
        self._vectorizer: TfidfVectorizer | None = None
        self._matrix = None
        self._cache: OrderedDict[tuple[str, int, str | None], tuple[dict[str, Any], ...]] = OrderedDict()
        self._cache_lock = threading.Lock()
        self._cache_hits = 0
        self._cache_misses = 0

    @property
    def cache_stats(self) -> dict[str, int]:
        with self._cache_lock:
            return {
                "hits": self._cache_hits,
                "misses": self._cache_misses,
                "entries": len(self._cache),
            }

    def _load(self) -> None:
        if not self.chunks_file.is_file():
            raise CorpusUnavailableError(
                f"Regulation corpus not found at {self.chunks_file}. "
                "Run scripts/ingest_regulations.py first."
            )

        try:
            with self.chunks_file.open("r", encoding="utf-8") as source:
                chunks = [
                    json.loads(line)
                    for line in source
                    if line.strip()
                ]
        except (OSError, json.JSONDecodeError) as exc:
            raise CorpusUnavailableError(
                f"Could not read the regulation corpus at {self.chunks_file}: {exc}"
            ) from exc

        chunks = [
            chunk for chunk in chunks
            if isinstance(chunk, dict)
            and isinstance(chunk.get("text"), str)
            and chunk["text"].strip()
        ]
        if not chunks:
            raise CorpusUnavailableError(
                "The regulation corpus exists but contains no searchable text."
            )

        vectorizer = TfidfVectorizer(
            lowercase=True,
            ngram_range=(1, 2),
            sublinear_tf=True,
            token_pattern=r"(?u)\b[a-zA-Z0-9][a-zA-Z0-9-]*\b",
        )
        try:
            matrix = vectorizer.fit_transform(
                [chunk["text"] for chunk in chunks]
            )
        except ValueError as exc:
            raise CorpusUnavailableError(
                f"Could not build a lexical index: {exc}"
            ) from exc

        self._chunks = chunks
        self._vectorizer = vectorizer
        self._matrix = matrix

    @property
    def chunk_count(self) -> int:
        self._ensure_loaded()
        return len(self._chunks or [])

    def _ensure_loaded(self) -> None:
        if self._chunks is None:
            self._load()

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return the highest scoring positive lexical matches.

        When ``category`` is set, only that regulation family is searched.
        With no category, both families are searched together.
        """
        normalized_query = query.strip()
        if not normalized_query:
            return []
        if not 1 <= top_k <= 20:
            raise ValueError("top_k must be between 1 and 20")
        if category is not None and category not in ALLOWED_CATEGORIES:
            raise ValueError(
                f"category must be one of: {', '.join(sorted(ALLOWED_CATEGORIES))}"
            )

        cache_key = (normalized_query.casefold(), top_k, category)
        with self._cache_lock:
            cached = self._cache.get(cache_key)
            if cached is not None:
                self._cache_hits += 1
                self._cache.move_to_end(cache_key)
                return [dict(item) for item in cached]
            self._cache_misses += 1

        self._ensure_loaded()
        assert self._chunks is not None
        assert self._vectorizer is not None
        assert self._matrix is not None

        eligible_indices = [
            index
            for index, chunk in enumerate(self._chunks)
            if category is None or chunk.get("category") == category
        ]
        if not eligible_indices:
            return []

        query_vector = self._vectorizer.transform([normalized_query])
        scores = cosine_similarity(query_vector, self._matrix).ravel()
        ranked = sorted(
            eligible_indices,
            key=lambda index: (scores[index], -index),
            reverse=True,
        )

        results = []
        for index in ranked:
            score = float(scores[index])
            if score <= 0:
                break
            chunk = self._chunks[index]
            results.append(
                {
                    "document_id": chunk.get("document_id"),
                    "source_file": chunk.get("source_file"),
                    "page": chunk.get("page"),
                    "chunk_index": chunk.get("chunk_index"),
                    "category": chunk.get("category"),
                    "similarity": round(score, 6),
                    "text": chunk["text"],
                }
            )
            if len(results) >= top_k:
                break
        with self._cache_lock:
            self._cache[cache_key] = tuple(dict(item) for item in results)
            self._cache.move_to_end(cache_key)
            while len(self._cache) > 512:
                self._cache.popitem(last=False)
        return results

    def lookup_citation(
        self,
        document_id: str,
        source_file: str,
        page: int,
        chunk_index: int | None = None,
    ) -> dict[str, Any] | None:
        """Resolve a candidate citation to the indexed source chunk."""
        self._ensure_loaded()
        assert self._chunks is not None
        for chunk in self._chunks:
            if (
                chunk.get("document_id") == document_id
                and chunk.get("source_file") == source_file
                and chunk.get("page") == page
                and (
                    chunk_index is None
                    or chunk.get("chunk_index") == chunk_index
                )
            ):
                return {
                    "document_id": chunk.get("document_id"),
                    "source_file": chunk.get("source_file"),
                    "page": chunk.get("page"),
                    "chunk_index": chunk.get("chunk_index"),
                    "category": chunk.get("category"),
                    "text": chunk.get("text", ""),
                }
        return None
