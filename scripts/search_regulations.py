"""Interactive diagnostic client for the shared regulation search tool."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.retrieval import CorpusUnavailableError, RegulationSearch

TOP_K = 5
DEFAULT_CATEGORY = "advertising_claims"


def main():
    search = RegulationSearch()
    try:
        print(f"Total corpus chunks: {search.chunk_count}")
    except CorpusUnavailableError as exc:
        print(exc)
        return

    print(f"Search category: {DEFAULT_CATEGORY}")
    print("Type 'exit' to stop.")

    while True:
        query = input("\nEnter a question: ").strip()
        if query.lower() in {"exit", "quit"}:
            print("Search ended.")
            break
        if not query:
            print("Please enter a question.")
            continue

        try:
            results = search.search(
                query,
                top_k=TOP_K,
                category=DEFAULT_CATEGORY,
            )
        except CorpusUnavailableError as exc:
            print(exc)
            break

        if not results:
            print("No positive lexical matches found.")
            continue

        for result in results:
            print("\n" + "=" * 75)
            print(f"Similarity score: {result['similarity']:.3f}")
            print(f"Source: {result.get('source_file') or 'Unknown'}")
            print(f"Page: {result.get('page') or 'Unknown'}")
            print(f"Category: {result.get('category') or 'Unknown'}")
            print("\nPassage:\n")
            print(result["text"][:1500])


if __name__ == "__main__":
    main()
