
import json
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


# Project paths
PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHUNKS_FILE = (
    PROJECT_ROOT / "data" / "processed" / "regulatory_chunks.jsonl"
)

TOP_K = 5


def load_chunks():
    """Load JSONL records from the processed regulatory corpus."""
    with CHUNKS_FILE.open("r", encoding="utf-8") as file:
        return [
            json.loads(line)
            for line in file
            if line.strip()
        ]


def main():
    # Check that the processed corpus exists.
    if not CHUNKS_FILE.exists():
        print(f"Corpus not found: {CHUNKS_FILE}")
        return

    all_chunks = load_chunks()

    print(f"Total corpus chunks: {len(all_chunks)}")

    # Restrict this diagnostic search to Advertising and Claims.
    chunks = [
        chunk
        for chunk in all_chunks
        if chunk.get("category") == "advertising_claims"
    ]

    print(f"Advertising and Claims chunks: {len(chunks)}")

    if not chunks:
        print(
            "No Advertising and Claims chunks found. "
            "Check the category values in regulatory_chunks.jsonl."
        )
        return

    print("Example source:", chunks[0].get("source_file", "Unknown"))

    # Prepare searchable text.
    texts = [
        chunk.get("text", "")
        for chunk in chunks
    ]

    vectorizer = TfidfVectorizer(
        lowercase=True,
        ngram_range=(1, 2),
        sublinear_tf=True,
        token_pattern=r"(?u)\b[a-zA-Z0-9][a-zA-Z0-9-]*\b",
    )

    try:
        document_matrix = vectorizer.fit_transform(texts)
    except ValueError as exc:
        print(f"Could not build search index: {exc}")
        return

    print("\nAdvertising and Claims search is ready.")
    print("Type 'exit' to stop.")

    while True:
        query = input(
            "\nEnter a question (or type exit): "
        ).strip()

        if query.lower() in {"exit", "quit"}:
            print("Search ended.")
            break

        if not query:
            print("Please enter a question.")
            continue

        # Convert the question into the same TF-IDF space.
        query_vector = vectorizer.transform([query])

        # Calculate similarity against every eligible chunk.
        scores = cosine_similarity(
            query_vector,
            document_matrix
        ).ravel()

        ranked_indices = scores.argsort()[::-1]
        results_shown = 0

        for index in ranked_indices:
            score = float(scores[index])

            # No remaining positive lexical matches.
            if score <= 0:
                break

            chunk = chunks[index]

            print("\n" + "=" * 75)
            print(f"Similarity score: {score:.3f}")
            print(
                "Source:",
                chunk.get("source_file", "Unknown")
            )
            print("Page:", chunk.get("page", "Unknown"))
            print("Category:", chunk.get("category", "Unknown"))
            print("\nPassage:\n")
            print(chunk.get("text", "")[:1500])

            results_shown += 1

            if results_shown >= TOP_K:
                break

        if results_shown == 0:
            print(
                "No positive lexical matches found in "
                "Advertising and Claims documents."
            )


if __name__ == "__main__":
    main()
