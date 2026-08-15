# Ragas Answer Evaluation Design

## Purpose

Add Ragas as an offline, end-to-end answer quality evaluator for Prism's existing RAG evaluation system.

The first version evaluates final answers produced by `/api/v1/chat/answer`. It does not replace the existing retrieval metrics or self-managed LLM judge. It adds semantic quality signals around answer grounding, answer relevance, and context usefulness.

## Scope

In scope:

- Collect reusable answer artifacts from the live Prism answer endpoint.
- Evaluate those artifacts with Ragas without calling the Prism answer endpoint again.
- Use existing golden dataset gold chunks as the first-version reference.
- Write file-based reports under `evaluation/runs/answer/<timestamp>/`.
- Keep Ragas out of online request handling and backend database persistence for the first version.

Out of scope:

- Frontend display of Ragas results.
- Persisting Ragas results into `EvaluationRun`.
- Human-authored `reference_answer` fields.
- Replacing `engine/eval/run_retrieval_v2.py` or `engine/eval/run_answer_eval.py`.
- Making Ragas scores a hard CI gate in the first version.

## Recommended Approach

Use a two-stage artifact pipeline:

1. `collect_answer_artifacts.py` calls the Prism answer endpoint once and saves the resulting question, answer, sources, contexts, reference, and metadata.
2. `run_ragas_on_artifacts.py` reads the saved artifacts and computes Ragas metrics offline.

This keeps system execution and judge execution separate. The same answer artifacts can be re-evaluated with different Ragas metrics, judge models, thresholds, or bug fixes without regenerating answers.

## Files

Add:

- `engine/eval/answer_artifacts.py`
- `engine/eval/collect_answer_artifacts.py`
- `engine/eval/run_ragas_on_artifacts.py`
- `evaluation/ragas_thresholds.json`

Add tests:

- `engine/tests/test_answer_artifacts.py`
- `engine/tests/test_run_ragas_on_artifacts.py`

Optionally add:

- `requirements-eval.txt`

Ragas should be kept in evaluation-only dependencies initially to reduce the chance of dependency churn affecting the online backend or engine runtime.

## Artifact Contract

Each line in `answer_artifacts.jsonl` is one JSON object:

```json
{
  "query_id": "q001",
  "question": "Question text",
  "answer": "Final answer text",
  "sources": [
    {
      "chunk_uid": "chunk-id",
      "text": "Full source text if available",
      "snippet": "Source snippet if available",
      "title": "Document title",
      "score": 0.82
    }
  ],
  "retrieved_contexts": ["Context text used for evaluation"],
  "reference": "Gold chunk text joined into a single reference",
  "metadata": {
    "question_type": "single_paper",
    "paper_title": "Document title",
    "ttfb_ms": 123,
    "total_latency_ms": 4567,
    "tool_calls": 2,
    "status": "done",
    "missing_context_count": 0
  }
}
```

The contract intentionally mirrors the fields Ragas needs while keeping Prism-specific data in `sources` and `metadata`.

## Reference Construction

The first version uses the existing golden dataset:

1. Read `relevant_children[].chunk_text`.
2. Join non-empty chunk texts with clear separators.
3. If chunk text is missing, use `chunk_id` to query `KnowledgeChunk.chunk_text`.
4. If no reference text can be found, mark the artifact as not evaluable for reference-dependent metrics.

This reference is evidence text, not a human-authored ideal answer. Ragas scores from this version should be interpreted as grounding and context quality signals, not as answer correctness.

## Retrieved Context Construction

For each source returned by the streamed answer endpoint:

1. Prefer `source["text"]`.
2. Fall back to `source["snippet"]`.
3. Fall back to DB lookup by `chunk_uid` or `chunk_id`.
4. Skip unresolved sources and increment `metadata.missing_context_count`.

Artifacts with an empty `retrieved_contexts` list should still be written, but Ragas should mark them as `retrieval_failure` and skip metrics that require contexts.

## Ragas Field Mapping

Map artifact fields to Ragas fields:

- `user_input` <- `question`
- `response` <- `answer`
- `retrieved_contexts` <- `retrieved_contexts`
- `reference` <- `reference`

The Ragas wrapper should isolate version-specific metric names. If the installed Ragas version uses `answer_relevancy` instead of `response_relevancy`, normalize the output key to `response_relevancy`.

## Metrics

First-version metrics:

- `faithfulness`
- `response_relevancy`
- `context_precision`
- `context_recall`

These complement existing metrics:

- Existing retrieval scripts remain responsible for deterministic `Recall@K`, `Precision@K`, `MRR`, and `NDCG`.
- Existing answer judge remains responsible for Prism's custom 1-5 faithfulness, relevance, and completeness rubric.
- Ragas adds standardized semantic judge metrics over the same answer artifacts.

## Thresholds

Initial `evaluation/ragas_thresholds.json`:

```json
{
  "faithfulness": 0.8,
  "response_relevancy": 0.75,
  "context_precision": 0.65,
  "context_recall": 0.65
}
```

Initial thresholds are advisory. The first implementation should flag bad cases and produce summaries, but should not fail CI by default.

## Bad Case Rules

Tag low-quality cases as follows:

- `faithfulness < 0.70`: `hallucination_risk`
- `response_relevancy < 0.65`: `off_topic`
- `context_precision < 0.50`: `noisy_context`
- `context_recall < 0.50`: `missing_context`
- Empty answer or `metadata.status != "done"`: `system_failure`
- Empty `retrieved_contexts`: `retrieval_failure`

Write bad cases to:

```text
evaluation/runs/answer/<timestamp>/bad_cases/<query_id>_ragas_bad_case.md
```

Each bad case should include the question, answer, Ragas scores, tags, retrieved contexts, reference excerpt, source ids, and latency metadata.

## Commands

Collect artifacts:

```powershell
python -m engine.eval.collect_answer_artifacts `
  --dataset evaluation/datasets/formal_docs_v1.json `
  --tenant-id default-tenant `
  --kb-uid <kb_uid> `
  --engine-url http://localhost:<engine_port> `
  --dry-run
```

Run Ragas:

```powershell
python -m engine.eval.run_ragas_on_artifacts `
  --artifacts evaluation/runs/answer/<timestamp>/answer_artifacts.jsonl `
  --judge-model gpt-4o-mini `
  --thresholds evaluation/ragas_thresholds.json
```

## Output Files

For each answer run:

```text
evaluation/runs/answer/<timestamp>/
  answer_artifacts.jsonl
  answer_summary.json
  ragas_detailed.csv
  ragas_summary.json
  ragas_low_scores.csv
  bad_cases/
    <query_id>_ragas_bad_case.md
```

`ragas_summary.json` should include:

- artifact path
- run timestamp
- judge model
- metric names
- total artifacts
- evaluated artifacts
- failed artifacts
- aggregate mean, median, min, and max by metric
- grouping by question type when available
- bad case counts
- failure details

## Error Handling

Artifact collection should:

- Always write an artifact for each attempted query when possible.
- Preserve endpoint errors in metadata and summary failures.
- Refresh the signed knowledge scope token using the same TTL pattern as `run_answer_eval.py`.
- Support `--dry-run` for the first three queries.

Ragas evaluation should:

- Continue when a single artifact fails.
- Record per-artifact failure messages.
- Skip reference-dependent metrics when `reference` is missing.
- Skip context-dependent metrics when `retrieved_contexts` is empty.
- Normalize metric output names before writing reports.

## Testing

Unit tests for `answer_artifacts.py`:

- NDJSON stream parsing handles token, sources, done, and error events.
- Reference construction uses inline `chunk_text`.
- Retrieved context extraction prefers `text`, then `snippet`, then DB lookup.
- JSONL writing preserves one artifact per line.

Unit tests for `run_ragas_on_artifacts.py`:

- Artifact fields map to Ragas inputs correctly.
- Mocked Ragas outputs produce detailed CSV and summary JSON.
- Threshold rules generate the expected bad case tags.
- Failed artifacts do not stop the whole run.

Manual smoke test:

- Run artifact collection with `--dry-run`.
- Run Ragas on the generated artifacts.
- Confirm `ragas_summary.json`, `ragas_detailed.csv`, and `bad_cases/` are created when expected.

## Migration Path

Phase 1:

- Add independent artifact collection and Ragas evaluation scripts.

Phase 2:

- Update `run_answer_eval.py` to optionally read `answer_artifacts.jsonl`, so the self-managed judge and Ragas can use the same captured answers.

Phase 3:

- Add a suite command such as `run_answer_quality_suite.py` to run `collect -> self_judge -> ragas -> report`.

Phase 4:

- After metrics stabilize, consider persisting results to `EvaluationRun` and exposing them in the frontend.

## Open Decisions

- Exact Ragas version pin should be selected during implementation after checking compatibility with the existing Python dependency set.
- The first implementation should verify whether the installed Ragas package exposes `response_relevancy` or `answer_relevancy`, then normalize to `response_relevancy` in Prism output.
- CI gating should remain disabled until several runs establish stable score distributions.
