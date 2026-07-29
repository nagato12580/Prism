# prism/engine/eval/run_retrieval_v2.py
"""Step 2: Extended retrieval evaluation with latency and channel health.

Usage:
    python -m engine.eval.run_retrieval_v2 --dataset results/<ts>/golden_dataset_v2.json
"""
import argparse
import csv
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from engine.app.retrieval.unified import scoped_text_hybrid_search
from engine.app.retrieval.contracts import SearchScope

K_VALUES = (5, 10, 20)
AGGREGATE_METRICS = [
    "recall@5", "recall@10", "recall@20",
    "precision@5", "precision@10", "precision@20",
    "hit@5", "hit@10", "hit@20",
    "ndcg@10", "ndcg@20",
    "mrr", "latency_ms",
]


def compute_retrieval_metrics(
    retrieved_ids: list[str],
    relevant_ids: set[str],
    ks: tuple[int, ...] = K_VALUES,
) -> dict[str, Any]:
    """Compute Recall@K, Precision@K, Hit@K, NDCG@K, MRR for a single query."""
    max_k = max(ks)
    retrieved = list(dict.fromkeys(retrieved_ids))[:max_k]
    relevant = set(relevant_ids)

    metrics: dict[str, Any] = {}
    first_relevant_rank = None

    for rank, cid in enumerate(retrieved, start=1):
        if cid in relevant:
            first_relevant_rank = rank
            break

    metrics["first_relevant_rank"] = first_relevant_rank
    metrics["mrr"] = 1.0 / first_relevant_rank if first_relevant_rank else 0.0

    for k in ks:
        top_k = retrieved[:k]
        hits = sum(1 for cid in top_k if cid in relevant)

        metrics[f"recall@{k}"] = hits / len(relevant) if relevant else 0.0
        metrics[f"precision@{k}"] = hits / k
        metrics[f"hit@{k}"] = 1 if hits > 0 else 0

        dcg = sum(
            (1.0 / math.log2(rank + 1))
            for rank, cid in enumerate(top_k, start=1)
            if cid in relevant
        )
        idcg = sum(
            1.0 / math.log2(i + 1)
            for i in range(1, min(len(relevant), k) + 1)
        )
        metrics[f"ndcg@{k}"] = dcg / idcg if idcg > 0 else 0.0

    return metrics


def aggregate_by_dimension(
    results: list[dict],
    dimension: str,
    metric_keys: list[str],
) -> dict[str, Any]:
    """Group results by a dimension and compute per-group aggregates."""
    groups: dict[str, list[dict]] = {}
    for r in results:
        key = r.get(dimension, "unknown")
        groups.setdefault(key, []).append(r)

    output: dict[str, Any] = {}
    for group_key, group_results in groups.items():
        agg: dict[str, Any] = {"count": len(group_results)}
        for metric in metric_keys:
            values = [r[metric] for r in group_results if metric in r and r[metric] is not None]
            if not values:
                continue
            n = len(values)
            mean = sum(values) / n
            sorted_vals = sorted(values)
            median = (sorted_vals[n // 2] + sorted_vals[(n - 1) // 2]) / 2
            variance = sum((v - mean) ** 2 for v in values) / n
            agg[metric] = {
                "mean": round(mean, 4),
                "median": round(median, 4),
                "std": round(math.sqrt(variance), 4),
                "min": round(min(values), 4),
                "max": round(max(values), 4),
            }
        output[group_key] = agg

    return output


def _format_retrieved_list(hits: list[dict], relevant_ids: set[str]) -> str:
    parts = []
    for i, h in enumerate(hits):
        cid = h["chunk_id"]
        score = h["score"]
        is_rel = "★" if cid in relevant_ids else " "
        parts.append(f"{is_rel}#{i + 1}:{cid[:8]}...({score:.4f})")
    return " | ".join(parts)


def _compute_aggregates(results: list[dict]) -> dict[str, Any]:
    """Compute overall aggregate statistics."""
    agg: dict[str, Any] = {}
    for metric in AGGREGATE_METRICS:
        values = [r[metric] for r in results if metric in r and r[metric] is not None]
        if not values:
            continue
        n = len(values)
        mean = sum(values) / n
        sorted_vals = sorted(values)
        median = (sorted_vals[n // 2] + sorted_vals[(n - 1) // 2]) / 2
        variance = sum((v - mean) ** 2 for v in values) / n
        agg[metric] = {
            "mean": round(mean, 4),
            "median": round(median, 4),
            "std": round(math.sqrt(variance), 4),
            "min": round(min(values), 4),
            "max": round(max(values), 4),
        }
    return agg


def _estimate_channel_hits(hits: list[dict]) -> dict[str, int]:
    """Estimate per-channel contribution from metadata."""
    channels = {"dense": 0, "bm25": 0, "graph": 0, "rerank": 0}
    for h in hits:
        source = h.get("source_marker", "")
        if source == "graph_1hop":
            channels["graph"] += 1
        elif source in ("vector", "dense"):
            channels["dense"] += 1
        elif source == "bm25":
            channels["bm25"] += 1
        elif source == "rerank":
            channels["rerank"] += 1
        else:
            # Fallback: estimate from metadata
            meta = h.get("metadata", {})
            graph_rag = meta.get("graph_rag", {})
            if graph_rag.get("hops"):
                channels["graph"] += 1
            else:
                channels["dense"] += 1
    return channels


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Prism Retrieval Evaluation v2")
    parser.add_argument("--dataset", required=True, help="Path to golden_dataset_v2.json")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--kb-uid", required=True)
    parser.add_argument("--index-generation", required=True)
    parser.add_argument("--graph-generation", default=None)
    args = parser.parse_args(argv)

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        print(f"[!] Dataset not found: {dataset_path}")
        sys.exit(1)

    # Determine run directory (same parent as dataset)
    run_dir = dataset_path.parent
    scope = SearchScope(
        tenant_id=args.tenant_id,
        kb_uid=args.kb_uid,
        index_generation=args.index_generation,
        graph_generation=args.graph_generation,
    )

    print("=" * 60)
    print("Prism Retrieval Evaluation v2")
    print("=" * 60)

    # Load dataset
    print(f"\n[1/3] Loading dataset: {dataset_path}")
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    queries = dataset["queries"]
    print(f"  Questions: {len(queries)}")

    # Run retrieval
    print(f"\n[2/3] Running retrieval evaluation...")
    results: list[dict] = []
    failures: list[dict] = []

    for i, q in enumerate(queries):
        qid = q["id"]
        question = q["question"]
        relevant_ids = {c["chunk_id"] for c in q["relevant_children"]}

        try:
            t0 = time.perf_counter()
            hits = scoped_text_hybrid_search(question, scope, top_k=max(K_VALUES))
            latency_ms = round((time.perf_counter() - t0) * 1000)
        except Exception as e:
            print(f"  [{i + 1}/{len(queries)}] {qid} ERROR: {e}")
            failures.append({"query_id": qid, "question": question, "error": str(e)})
            continue

        retrieved_ids = [h["chunk_id"] for h in hits]

        metrics = compute_retrieval_metrics(retrieved_ids, relevant_ids)
        channels = _estimate_channel_hits(hits)
        metrics["latency_ms"] = latency_ms
        metrics.update({f"{ch}_hits": count for ch, count in channels.items()})

        result = {
            "query_id": qid,
            "question": question,
            "question_type": q.get("question_type", "?"),
            "paper_title": (q.get("paper_titles") or [q.get("item_title", "?")])[0],
            "relevant_count": len(relevant_ids),
            **metrics,
            "retrieved_detail": _format_retrieved_list(hits, relevant_ids),
        }
        results.append(result)

        status = "OK" if metrics["hit@10"] else "XX"
        print(f"  [{i + 1}/{len(queries)}] {status} {qid} "
              f"R@10={metrics['recall@10']:.2f} MRR={metrics['mrr']:.2f} "
              f"lat={latency_ms}ms | {question[:40]}...")

    # Output
    print(f"\n[3/3] Writing results...")

    # detailed.csv
    csv_path = run_dir / "retrieval_detailed.csv"
    csv_fields = [
        "query_id", "question", "question_type", "paper_title", "relevant_count",
        "recall@5", "recall@10", "recall@20",
        "precision@5", "precision@10", "precision@20",
        "hit@5", "hit@10", "hit@20",
        "ndcg@10", "ndcg@20", "mrr", "first_relevant_rank",
        "latency_ms", "dense_hits", "bm25_hits", "graph_hits", "rerank_hits",
        "retrieved_detail",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)
    print(f"  CSV: {csv_path}")

    # summary.json
    summary = {
        "meta": {
            "dataset": str(dataset_path),
            "run_at": datetime.now(timezone.utc).isoformat(),
            "total_queries": len(queries),
            "evaluated": len(results),
            "failed": len(failures),
            "scope": {
                "tenant_id": args.tenant_id,
                "kb_uid": args.kb_uid,
                "index_generation": args.index_generation,
            },
        },
        "aggregates": _compute_aggregates(results),
        "by_paper": aggregate_by_dimension(results, "paper_title", AGGREGATE_METRICS),
        "by_type": aggregate_by_dimension(results, "question_type", AGGREGATE_METRICS),
        "zero_recall": [r["query_id"] for r in results if r["recall@10"] == 0],
        "latency": {
            "values_ms": sorted([r["latency_ms"] for r in results]),
        },
        "failures": failures,
    }
    # Compute latency percentiles
    lats = sorted([r["latency_ms"] for r in results if "latency_ms" in r])
    if lats:
        summary["latency"]["p50"] = lats[len(lats) // 2]
        summary["latency"]["p95"] = lats[int(len(lats) * 0.95)]
        summary["latency"]["p99"] = lats[int(len(lats) * 0.99)]

    summary_path = run_dir / "retrieval_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  JSON: {summary_path}")

    # Terminal summary
    agg = summary["aggregates"]
    print(f"\n{'=' * 60}")
    print("Retrieval Summary")
    print(f"{'=' * 60}")
    print(f"Evaluated: {len(results)}/{len(queries)} (failed: {len(failures)})")
    for k in K_VALUES:
        r = agg.get(f"recall@{k}", {})
        if r:
            print(f"Recall@{k:>2}:  mean={r['mean']:.3f} median={r['median']:.3f} σ={r['std']:.3f}")
    m = agg.get("mrr", {})
    if m:
        print(f"MRR:       mean={m['mean']:.3f} median={m['median']:.3f}")
    zero = summary.get("zero_recall", [])
    print(f"Zero Recall@10: {len(zero)} queries")
    if summary.get("latency", {}).get("p95"):
        print(f"Latency P50/P95: {summary['latency'].get('p50')}ms / {summary['latency'].get('p95')}ms")


if __name__ == "__main__":
    main()
