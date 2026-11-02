# Evaluation report

## Retrieval comparison

The first deliberate change was to make the query family explicit and search the matching regulation family for each expected provision. The protein-claim case uses two related queries, one for the Advertising and Claims condition and one for the Labelling and Display nutrition declaration. Both runs use the same five scenarios and six expected source/page evidence items, `k=5`, the same generated corpus, and the same TF-IDF index. The baseline uses the original combined queries and global search; the updated strategy uses refined queries with regulation-family filters.

| Metric | Baseline | Family-filtered | Change |
| --- | ---: | ---: | ---: |
| Source/page evidence recall@5 | 0.5000 (3/6) | 1.0000 (6/6) | +0.5000 |
| Mean reciprocal rank per expected evidence item | 0.1806 | 0.4583 | +0.2777 |

Recall@5 is the fraction of expected source/page pairs appearing among the top five results for the matching query. MRR is the mean of `1/rank` for each expected source/page item, with a miss scored as zero. The paired outputs are [baseline results](retrieval_evaluation_baseline.json) and [updated results](retrieval_evaluation.json). Each records the corpus build time and chunk-file hash.

The set covers nutrition declarations, ingredients, allergens, vegetarian marking, and the cross-regulation protein claim. It is a small retrieval diagnostic; a correct source/page match does not prove that the passage applies to a specific product or assessment date. The case pages and expected outcomes still need independent regulatory-affairs review. The current score should not be presented as full-system accuracy.

## End-to-end protein-claim demonstration

The queued local stub run completed with the `Source of protein` label and a declared `5 g` protein value on a per-100-g basis. It returned verified passages from both regulation families, including the 2018 Advertising and Claims Gazette page 28 and Labelling and Display nutrition declaration passages. Citation verification resolved each returned document, page, and chunk and found the quoted excerpt in indexed text. The result routed to `regulatory-review`, and its explanation left the numeric comparison unresolved because the applicable RDA, amendments, and effective dates have not been verified.

The initial run used 15 bounded tool calls and completed without a workflow failure. A fresh run during final handoff also succeeded in the local queue with ten verified citations across both regulation families. The deterministic stub reports zero model cost; this is not an estimate for a hosted model. Its end-to-end wall time is machine- and load-dependent. Reproduce the flow with the API and worker instructions in the README. Compose has not been runtime-verified on this host because no Docker daemon is available.

## Local load test

The declared p95 target and completed one-worker, three-worker, and 120-user Locust results are summarized in [the load test report](LOAD_TEST_REPORT.md). The five-user, three-worker run met the target with p95 1.3 seconds; the 120-user run had p95 25 seconds and no Locust failures. These short same-host tests used the deterministic stub and local SQLite queue, so they do not establish production capacity.

## Evaluation limits and next quality gate

- This run did not measure groundedness, answer faithfulness, toxicity, or hallucination rate across a broad request set. The application currently emits deterministic evidence summaries rather than open-ended model-authored compliance decisions.
- It did not compare two prompt variants. The local stub follows a fixed tool policy; prompt changes are not meaningful model-quality experiments against that stub.
- It does not establish production capacity from the short local Locust runs.
- A future broader evaluation should add reviewed cases, include unsupported-evidence and failed-verification cases, and compare retrieval and generated report behavior separately.
