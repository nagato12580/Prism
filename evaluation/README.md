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

Compare traditional chunk hybrid retrieval with the governed CKP/PKU chains:

```powershell
python -m engine.eval.compare_retrieval_chains --chains traditional governed governed_evidence --verbose
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

## Latest Retrieval Run

Latest three-chain run:

```text
evaluation/runs/retrieval/2026-06-22_170217_compare/
```

Key result:

- `traditional_hybrid`: Expanded Recall@10 0.516, Expanded Hit@10 95.0%
- `governed_ckp_pku`: Expanded Recall@10 0.281, Expanded Hit@10 28.3%
- `governed_evidence + PKU vector`: Expanded Recall@10 0.602, Expanded Hit@10 61.7%

Learning report:

```text
evaluation/runs/retrieval/2026-06-22_170217_compare/pku_vector_retrieval_report.md
```

Previous governed evidence baseline:

```text
evaluation/runs/retrieval/2026-06-22_155519_compare/
```

- `governed_evidence`: Expanded Recall@10 0.632, Expanded Hit@10 65.0%, Expanded MRR 0.492

The PKU vector retrieval path is now implemented, but this run did not beat the
previous governed evidence baseline. The report above documents the current
noise pattern and the next recommended gated-fusion phase.
