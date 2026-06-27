# Deep Knowledge Search Benchmark Design

## Dataset

Each case contains:

- `question`
- `depth`
- `answerable`
- `expected_ckp_ids`
- `expected_pku_ids`
- `expected_source_ids`
- `required_dimensions`

The example schema lives at `evaluation/datasets/deep_knowledge_search_v1.example.json`.

## Metrics

- `ckp_recall_at_k_mean`: whether the correct canonical knowledge points are found.
- `pku_recall_at_k_mean`: whether the correct evidence units are found.
- `source_recall_at_k_mean`: whether original chunk or asset sources are recovered.
- `judge_completeness_accuracy`: whether judge complete/incomplete matches labels.
- `avg_iterations`: average orchestrator loop count.
- `avg_latency_ms` and `p95_latency_ms`: runtime cost.
- `fallback_rate`: share of cases that needed global fallback.

## Quantitative Targets

For a first internal benchmark of 30 to 50 labeled cases:

- CKP recall@10 >= 0.80
- PKU recall@10 >= 0.70
- Source recall@10 >= 0.65
- Judge completeness accuracy >= 0.75
- Average iterations <= 3.0
- p95 latency <= 8 seconds on local database without global chunk fallback
- Fallback rate <= 0.20

## Running

```bash
python engine/eval/run_deep_knowledge_search_eval.py \
  --dataset evaluation/datasets/deep_knowledge_search_v1.example.json \
  --top-k 10
```

The script writes `summary.json` under `evaluation/runs/deep_search/<timestamp>/`.
