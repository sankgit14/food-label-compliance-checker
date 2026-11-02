
import hashlib
import json
import re
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from pypdf import PdfReader

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
OUTPUT_DIR = PROJECT_ROOT / "data" / "processed"
OUTPUT_FILE = OUTPUT_DIR / "regulatory_chunks.jsonl"
METADATA_FILE = OUTPUT_DIR / "regulatory_index_metadata.json"

CHUNK_SIZE = 1400
CHUNK_OVERLAP = 200


def split_text(text: str) -> list[str]:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    if not text:
        return []

    chunks = []
    start = 0

    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))

        # Prefer ending at a paragraph or sentence boundary.
        if end < len(text):
            boundary = max(
                text.rfind("\n", start, end),
                text.rfind(". ", start, end),
            )
            if boundary > start + CHUNK_SIZE // 2:
                end = boundary + 1

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end >= len(text):
            break

        start = max(end - CHUNK_OVERLAP, start + 1)

    return chunks


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    built_at = datetime.now(timezone.utc).isoformat()

    pdf_files = sorted(
        path for path in RAW_DIR.rglob("*")
        if path.is_file() and path.suffix.lower() == ".pdf"
    )

    if not pdf_files:
        print(f"No PDFs found under: {RAW_DIR}")
        return

    total_pages = 0
    total_chunks = 0
    failed_files = []
    document_metadata = []
    temporary_output = OUTPUT_FILE.with_suffix(".jsonl.tmp")

    with temporary_output.open("w", encoding="utf-8") as output:
        for pdf_path in pdf_files:
            relative_path = pdf_path.relative_to(RAW_DIR).as_posix()
            print(f"Reading: {relative_path}")
            source_sha256 = hashlib.sha256(
                pdf_path.read_bytes()
            ).hexdigest()
            document_id = hashlib.sha256(
                f"{relative_path}:{source_sha256}".encode("utf-8")
            ).hexdigest()[:16]
            document_info = {
                "document_id": document_id,
                "source_file": relative_path,
                "source_sha256": source_sha256,
                "category": (
                    "labelling_display"
                    if "labelling" in relative_path.lower()
                    else (
                        "advertising_claims"
                        if "advertising" in relative_path.lower()
                        else "unclassified"
                    )
                ),
                "pages_total": 0,
                "pages_with_text": 0,
                "pages_without_text": [],
                "error": None,
            }

            try:
                reader = PdfReader(str(pdf_path))
                document_info["pages_total"] = len(reader.pages)

                for page_index, page in enumerate(reader.pages):
                    page_number = page_index + 1
                    text = page.extract_text() or ""

                    if not text.strip():
                        document_info["pages_without_text"].append(page_number)
                        print(
                            f"  Warning: page {page_number} "
                            "has no extractable text"
                        )
                        continue

                    total_pages += 1
                    document_info["pages_with_text"] += 1

                    for chunk_index, chunk in enumerate(
                        split_text(text)
                    ):
                        record = {
                            "document_id": document_id,
                            "source_sha256": source_sha256,
                            "source_file": relative_path,
                            "page": page_number,
                            "chunk_index": chunk_index,
                            "category": document_info["category"],
                            "text": chunk,
                        }

                        output.write(
                            json.dumps(record, ensure_ascii=False) + "\n"
                        )
                        total_chunks += 1

            except Exception as exc:
                failed_files.append(relative_path)
                document_info["error"] = str(exc)
                print(f"  ERROR: {exc}")
            finally:
                document_metadata.append(document_info)

    os.replace(temporary_output, OUTPUT_FILE)
    elapsed_seconds = max(time.perf_counter() - started, 0.000001)
    index_metadata = {
        "built_at_utc": built_at,
        "source_root": RAW_DIR.relative_to(PROJECT_ROOT).as_posix(),
        "documents_discovered": len(pdf_files),
        "pages_with_text": total_pages,
        "chunks_written": total_chunks,
        "failed_documents": len(failed_files),
        "elapsed_seconds": round(elapsed_seconds, 3),
        "pages_per_second": round(total_pages / elapsed_seconds, 3),
        "chunks_per_second": round(total_chunks / elapsed_seconds, 3),
        "chunks_file": OUTPUT_FILE.relative_to(PROJECT_ROOT).as_posix(),
        "chunks_sha256": hashlib.sha256(OUTPUT_FILE.read_bytes()).hexdigest(),
        "documents": document_metadata,
    }
    temporary_metadata = METADATA_FILE.with_suffix(".json.tmp")
    temporary_metadata.write_text(
        json.dumps(index_metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary_metadata, METADATA_FILE)

    print("\n--- Ingestion summary ---")
    print(f"PDF files discovered: {len(pdf_files)}")
    print(f"Pages with extractable text: {total_pages}")
    print(f"Chunks written: {total_chunks}")
    print(f"Files with errors: {len(failed_files)}")
    print(f"Output: {OUTPUT_FILE}")
    print(f"Index metadata: {METADATA_FILE}")
    print(f"Throughput: {total_pages / elapsed_seconds:.2f} pages/s")

    if failed_files:
        print("Review these files:")
        for name in failed_files:
            print(f" - {name}")


if __name__ == "__main__":
    main()
