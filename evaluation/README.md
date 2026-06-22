# Prism Evaluation Workspace

This directory is the home for Prism evaluation assets and outputs.

## Layout

```text
evaluation/
  datasets/              # Curated eval datasets and benchmark manifests
  runs/
    retrieval/           # Offline retrieval comparison outputs
    online/              # Future online eval logs and sampled traces
    llm_judge/           # Future LLM-as-judge reports
  benchmarks/            # Future benchmark definitions and rubrics
```

Current retrieval evaluation code lives in `engine/eval/compare_retrieval_chains.py`
because it imports backend and engine modules directly. Its run artifacts are written
to `evaluation/runs/retrieval/` by default.

## Current Offline Retrieval Evaluation

Compare traditional chunk hybrid retrieval with the governed CKP/PKU chain:

```powershell
python -m engine.eval.compare_retrieval_chains --chains traditional governed --verbose
```

Outputs per run:

- `summary.json`: aggregate metrics for each chain
- `detailed_exact.csv`: direct chunk-id matching metrics
- `detailed_expanded.csv`: metrics after expanding retrieved parent chunks to child chunks
- `detailed_verbose.json`: optional retrieved chunk text and per-query details

## Metric Notes

The current golden dataset labels relevant child chunks. The governed CKP/PKU chain
may backtrack to parent chunks, so retrieval reports both exact and expanded metrics.
Use exact metrics for strict chunk retrieval quality, and expanded metrics when the
answering chain can use parent context that contains the labeled child evidence.
