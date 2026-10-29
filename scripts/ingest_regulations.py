
import hashlib
import json
import re
from pathlib import Path

from pypdf import PdfReader

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
OUTPUT_DIR = PROJECT_ROOT / "data" / "processed"
OUTPUT_FILE = OUTPUT_DIR / "regulatory_chunks.jsonl"

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

    with OUTPUT_FILE.open("w", encoding="utf-8") as output:
        for pdf_path in pdf_files:
            relative_path = pdf_path.relative_to(RAW_DIR).as_posix()
            print(f"Reading: {relative_path}")

            try:
                reader = PdfReader(str(pdf_path))

                for page_index, page in enumerate(reader.pages):
                    page_number = page_index + 1
                    text = page.extract_text() or ""

                    if not text.strip():
                        print(
                            f"  Warning: page {page_number} "
                            "has no extractable text"
                        )
                        continue

                    total_pages += 1

                    for chunk_index, chunk in enumerate(
                        split_text(text)
                    ):
                        record = {
                            "document_id": hashlib.sha256(
                                relative_path.encode("utf-8")
                            ).hexdigest()[:16],
                            "source_file": relative_path,
                            "page": page_number,
                            "chunk_index": chunk_index,
                            "category": (
                                "labelling_display"
                                if "labelling" in relative_path.lower()
                                else (
                                    "advertising_claims"
                                    if "advertising" in relative_path.lower()
                                    else "unclassified"
                                )
                            ),
                            "text": chunk,
                        }

                        output.write(
                            json.dumps(record, ensure_ascii=False) + "\n"
                        )
                        total_chunks += 1

            except Exception as exc:
                failed_files.append(relative_path)
                print(f"  ERROR: {exc}")

    print("\n--- Ingestion summary ---")
    print(f"PDF files discovered: {len(pdf_files)}")
    print(f"Pages with extractable text: {total_pages}")
    print(f"Chunks written: {total_chunks}")
    print(f"Files with errors: {len(failed_files)}")
    print(f"Output: {OUTPUT_FILE}")

    if failed_files:
        print("Review these files:")
        for name in failed_files:
            print(f" - {name}")


if __name__ == "__main__":
    main()
