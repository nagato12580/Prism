# prism/engine/eval/compare_retrieval_chains.py
"""Compare traditional chunk hybrid retrieval with governed CKP/PKU retrieval.

The golden dataset marks relevant child chunks. Governed retrieval often
backtracks to parent document chunks, so this evaluator reports two views:

- exact: retrieved chunk IDs are compared directly with relevant child IDs.
- expanded: retrieved parent chunks are expanded to their child chunk IDs.
"""
import argparse
import csv
import json
import math
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.app.database import SessionLocal
from backend.app.models.knowledge_item import KnowledgeChunk
from engine.app.agent.tools.governed_knowledge import (
    _GOVERNED_EVIDENCE_PKU_VECTOR_WEIGHT as GOVERNED_EVIDENCE_PKU_VECTOR_WEIGHT,
    _query_governed_evidence,
    _query_governed_knowledge,
)
from engine.app.config import settings
from engine.app.retrieval.hybrid import BM25_WEIGHT, RRF_K, VECTOR_WEIGHT, hybrid_search

DEFAULT_DATASET = Path(__file__).resolve().parent / "golden_dataset.json"
EVALUATION_ROOT = _project_root / "evaluation"
RESULTS_DIR = EVALUATION_ROOT / "runs" / "retrieval"
K_VALUES = [5, 10, 20]
GOVERNED_EVIDENCE_PKU_EVIDENCE_BOOST = 0.05

Retriever = Callable[[str, int], list[dict[str, Any]]]


def _governed_evidence_params() -> dict[str, Any]:
    return {
        "ckp_vector_recall": True,
        "ckp_lexical_recall": True,
        "pku_vector_recall": True,
        "pku_vector_weight": GOVERNED_EVIDENCE_PKU_VECTOR_WEIGHT,
        "pku_query_aware_rerank": True,
        "pku_evidence_boost": GOVERNED_EVIDENCE_PKU_EVIDENCE_BOOST,
        "parent_child_expansion": True,
        "eval_k_values": K_VALUES,
    }


def _compute_metrics(retrieved_ids: list[str], relevant_ids: set[str], k_values: list[int] = K_VALUES) -> dict[str, Any]:
    max_k = max(k_values)
    retrieved = retrieved_ids[:max_k]
    first_relevant_rank = None

    for rank, cid in enumerate(retrieved, start=1):
        if cid in relevant_ids:
            first_relevant_rank = rank
            break

    metrics: dict[str, Any] = {
        "first_relevant_rank": first_relevant_rank,
        "mrr": 1.0 / first_relevant_rank if first_relevant_rank else 0.0,
    }

    for k in k_values:
        top_k = retrieved[:k]
        hits = sum(1 for cid in top_k if cid in relevant_ids)
        dcg = sum(
            1.0 / math.log2(rank + 1)
            for rank, cid in enumerate(top_k, start=1)
            if cid in relevant_ids
        )
        idcg = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(relevant_ids), k) + 1))
        metrics[f"recall@{k}"] = hits / len(relevant_ids) if relevant_ids else 0.0
        metrics[f"precision@{k}"] = hits / k
        metrics[f"hit@{k}"] = 1 if hits else 0
        metrics[f"ndcg@{k}"] = dcg / idcg if idcg else 0.0

    return metrics


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    metric_names = [
        *[f"recall@{k}" for k in K_VALUES],
        *[f"precision@{k}" for k in K_VALUES],
        *[f"hit@{k}" for k in K_VALUES],
        *[f"ndcg@{k}" for k in K_VALUES],
        "mrr",
    ]
    aggregates: dict[str, dict[str, float]] = {}
    for name in metric_names:
        values = [float(row[name]) for row in rows]
        n = len(values)
        mean = sum(values) / n if n else 0.0
        median = sorted(values)[n // 2] if n else 0.0
        variance = sum((value - mean) ** 2 for value in values) / n if n else 0.0
        aggregates[name] = {
            "mean": round(mean, 4),
            "median": round(median, 4),
            "std": round(math.sqrt(variance), 4),
            "min": round(min(values), 4) if values else 0.0,
            "max": round(max(values), 4) if values else 0.0,
        }
    return aggregates


def _relevant_child_ids(query: dict[str, Any]) -> set[str]:
    if "relevant_children" in query:
        return {str(child["chunk_id"]) for child in query["relevant_children"]}
    return {str(chunk_id) for chunk_id in query.get("relevant_child_ids", [])}


def _child_ids_for_chunks(chunk_ids: set[str]) -> dict[str, list[str]]:
    if not chunk_ids:
        return {}

    db = SessionLocal()
    try:
        chunks = db.query(KnowledgeChunk).filter(KnowledgeChunk.id.in_(chunk_ids)).all()
        by_chunk: dict[str, list[str]] = {chunk_id: [chunk_id] for chunk_id in chunk_ids}
        parent_ids = [chunk.id for chunk in chunks if chunk.chunk_type == "parent"]
        if parent_ids:
            children = (
                db.query(KnowledgeChunk)
                .filter(KnowledgeChunk.parent_id.in_(parent_ids), KnowledgeChunk.chunk_type == "child")
                .order_by(KnowledgeChunk.chunk_index.asc(), KnowledgeChunk.created_at.asc(), KnowledgeChunk.id.asc())
                .all()
            )
            grouped: dict[str, list[str]] = {}
            for child in children:
                grouped.setdefault(str(child.parent_id), []).append(str(child.id))
            for parent_id, child_ids in grouped.items():
                by_chunk[parent_id] = child_ids
        return by_chunk
    finally:
        db.close()


def _load_chunk_texts(chunk_ids: set[str]) -> dict[str, str]:
    if not chunk_ids:
        return {}
    db = SessionLocal()
    try:
        chunks = db.query(KnowledgeChunk).filter(KnowledgeChunk.id.in_(chunk_ids)).all()
        return {str(chunk.id): chunk.chunk_text for chunk in chunks}
    finally:
        db.close()


def _dedupe_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for hit in hits:
        chunk_id = str(hit.get("chunk_id") or "")
        if not chunk_id or chunk_id in seen:
            continue
        seen.add(chunk_id)
        deduped.append(hit)
    return deduped


def _traditional_hybrid(query: str, top_k: int) -> list[dict[str, Any]]:
    return [
        {
            "chunk_id": str(hit["chunk_id"]),
            "item_id": hit.get("item_id"),
            "score": float(hit.get("score") or 0.0),
            "source": "traditional_hybrid",
        }
        for hit in hybrid_search(query, top_k=top_k)
    ]


def _governed_ckp_pku(query: str, top_k: int) -> list[dict[str, Any]]:
    _terms, bundles, _knowledge_results = _query_governed_knowledge(query, limit=top_k)
    hits: list[dict[str, Any]] = []
    for rank, bundle in enumerate(bundles, start=1):
        bundle_score = float(bundle.get("score") or 0.0)
        for source in bundle.get("raw_sources", []):
            if source.get("source_kind") != "document_chunk":
                continue
            chunk_id = str(source.get("chunk_id") or source.get("source_id") or "")
            if not chunk_id:
                continue
            hits.append(
                {
                    "chunk_id": chunk_id,
                    "item_id": source.get("item_id"),
                    "score": float(source.get("score") or bundle_score),
                    "source": "governed_ckp_pku",
                    "canonical_id": bundle.get("canonical_id"),
                    "canonical_title": bundle.get("title"),
                    "rank_hint": rank,
                }
            )
    hits.sort(key=lambda item: (float(item.get("score") or 0.0), -int(item.get("rank_hint") or 0)), reverse=True)
    return _dedupe_hits(hits)[:top_k]


def _governed_evidence(query: str, top_k: int) -> list[dict[str, Any]]:
    _terms, bundles, _knowledge_results = _query_governed_evidence(query, limit=top_k)
    hits: list[dict[str, Any]] = []
    for rank, bundle in enumerate(bundles, start=1):
        bundle_score = float(bundle.get("score") or 0.0)
        expanded_child_ids = [
            str(source.get("chunk_id") or source.get("source_id"))
            for source in bundle.get("expanded_sources", [])
            if source.get("source_kind") == "document_chunk" and (source.get("chunk_id") or source.get("source_id"))
        ]
        sources = bundle.get("raw_sources", [])
        for source in sources:
            if source.get("source_kind") != "document_chunk":
                continue
            chunk_id = str(source.get("chunk_id") or source.get("source_id") or "")
            if not chunk_id:
                continue
            hits.append(
                {
                    "chunk_id": chunk_id,
                    "item_id": source.get("item_id"),
                    "score": float(source.get("score") or bundle_score),
                    "source": "governed_evidence",
                    "canonical_id": bundle.get("canonical_id"),
                    "canonical_title": bundle.get("title"),
                    "rank_hint": rank,
                    "expanded_child_ids": expanded_child_ids,
                }
            )
    hits.sort(key=lambda item: (float(item.get("score") or 0.0), -int(item.get("rank_hint") or 0)), reverse=True)
    return _dedupe_hits(hits)[:top_k]


def _chain_map() -> dict[str, tuple[str, Retriever]]:
    return {
        "traditional": ("traditional_hybrid", _traditional_hybrid),
        "governed": ("governed_ckp_pku", _governed_ckp_pku),
        "governed_evidence": ("governed_evidence", _governed_evidence),
    }


def _expanded_retrieved_ids(hits: list[dict[str, Any]]) -> list[str]:
    chunk_ids = {str(hit["chunk_id"]) for hit in hits if hit.get("chunk_id")}
    children_by_chunk = _child_ids_for_chunks(chunk_ids)
    expanded: list[str] = []
    seen: set[str] = set()
    for hit in hits:
        for child_id in children_by_chunk.get(str(hit["chunk_id"]), [str(hit["chunk_id"])]):
            if child_id not in seen:
                expanded.append(child_id)
                seen.add(child_id)
    return expanded


def _retrieved_detail(hits: list[dict[str, Any]], relevant_ids: set[str], *, expanded: bool) -> str:
    if expanded:
        expanded_ids = _expanded_retrieved_ids(hits)
        return " | ".join(
            f"{'*' if cid in relevant_ids else ' '}#{idx + 1}:{cid[:8]}..."
            for idx, cid in enumerate(expanded_ids[: max(K_VALUES)])
        )
    return " | ".join(
        f"{'*' if str(hit['chunk_id']) in relevant_ids else ' '}#{idx + 1}:{str(hit['chunk_id'])[:8]}...({float(hit.get('score') or 0.0):.4f})"
        for idx, hit in enumerate(hits[: max(K_VALUES)])
    )


def _evaluate_chain(
    *,
    name: str,
    retriever: Retriever,
    queries: list[dict[str, Any]],
    verbose: bool,
) -> dict[str, Any]:
    exact_rows: list[dict[str, Any]] = []
    expanded_rows: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    verbose_rows: list[dict[str, Any]] = []
    top_k = max(K_VALUES)

    for i, query in enumerate(queries, start=1):
        qid = str(query["id"])
        question = str(query["question"])
        relevant_ids = _relevant_child_ids(query)
        try:
            hits = retriever(question, top_k)
        except Exception as exc:
            print(f"  [{name}] [{i}/{len(queries)}] {qid} ERROR: {exc}")
            failures.append({"query_id": qid, "question": question, "error": str(exc)})
            continue

        exact_ids = [str(hit["chunk_id"]) for hit in hits]
        expanded_ids = _expanded_retrieved_ids(hits)
        exact_metrics = _compute_metrics(exact_ids, relevant_ids)
        expanded_metrics = _compute_metrics(expanded_ids, relevant_ids)

        base = {
            "chain": name,
            "query_id": qid,
            "question": question,
            "language": query.get("language", "?"),
            "item_title": query.get("item_title", ""),
            "relevant_count": len(relevant_ids),
        }
        exact_rows.append(
            {
                **base,
                **exact_metrics,
                "retrieved_detail": _retrieved_detail(hits, relevant_ids, expanded=False),
            }
        )
        expanded_rows.append(
            {
                **base,
                **expanded_metrics,
                "retrieved_detail": _retrieved_detail(hits, relevant_ids, expanded=True),
            }
        )

        if verbose:
            hit_chunk_ids = {str(hit["chunk_id"]) for hit in hits if hit.get("chunk_id")}
            text_map = _load_chunk_texts(hit_chunk_ids)
            children_by_chunk = _child_ids_for_chunks(hit_chunk_ids)
            verbose_rows.append(
                {
                    **base,
                    "exact_metrics": exact_metrics,
                    "expanded_metrics": expanded_metrics,
                    "retrieved": [
                        {
                            "rank": rank,
                            "chunk_id": hit["chunk_id"],
                            "score": hit.get("score"),
                            "exact_relevant": str(hit["chunk_id"]) in relevant_ids,
                            "expanded_child_ids": children_by_chunk.get(str(hit["chunk_id"]), []),
                            "text": text_map.get(str(hit["chunk_id"]), "")[:1200],
                        }
                        for rank, hit in enumerate(hits, start=1)
                    ],
                }
            )

        print(
            f"  [{name}] [{i}/{len(queries)}] "
            f"{'OK' if expanded_metrics['hit@10'] else 'XX'} {qid} "
            f"exact R@10={exact_metrics['recall@10']:.2f} "
            f"expanded R@10={expanded_metrics['recall@10']:.2f} "
            f"expanded MRR={expanded_metrics['mrr']:.2f}"
        )

    return {
        "chain": name,
        "exact_rows": exact_rows,
        "expanded_rows": expanded_rows,
        "exact_aggregates": _aggregate(exact_rows),
        "expanded_aggregates": _aggregate(expanded_rows),
        "failures": failures,
        "verbose_rows": verbose_rows,
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "chain",
        "query_id",
        "question",
        "language",
        "item_title",
        "relevant_count",
        *[f"recall@{k}" for k in K_VALUES],
        *[f"precision@{k}" for k in K_VALUES],
        *[f"hit@{k}" for k in K_VALUES],
        *[f"ndcg@{k}" for k in K_VALUES],
        "mrr",
        "first_relevant_rank",
        "retrieved_detail",
    ]
    with open(path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare Prism retrieval chains")
    parser.add_argument("--dataset", type=str, default=str(DEFAULT_DATASET), help="Golden dataset path")
    parser.add_argument(
        "--output-root",
        type=str,
        default=str(RESULTS_DIR),
        help="Directory for retrieval evaluation run outputs",
    )
    parser.add_argument(
        "--chains",
        nargs="+",
        choices=["traditional", "governed", "governed_evidence"],
        default=["traditional", "governed"],
        help="Retrieval chains to evaluate",
    )
    parser.add_argument("--verbose", action="store_true", help="Write verbose JSON with retrieved chunk text")
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        raise SystemExit(f"Dataset not found: {dataset_path}")

    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    queries = dataset.get("queries", [])
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    output_root = Path(args.output_root)
    run_dir = output_root / f"{run_ts}_compare"
    run_dir.mkdir(parents=True, exist_ok=True)

    chain_map = _chain_map()

    print(f"[1/3] Dataset: {dataset_path}")
    print(f"  Queries: {len(queries)}")
    print(f"  Chains: {', '.join(args.chains)}")
    print(f"  Current LLM: {settings.LLM_MODEL}")
    print(f"  Current embedding: {settings.EMBEDDING_MODEL}")

    reports: list[dict[str, Any]] = []
    exact_rows: list[dict[str, Any]] = []
    expanded_rows: list[dict[str, Any]] = []
    verbose_rows: list[dict[str, Any]] = []

    print("\n[2/3] Evaluating...")
    for chain_arg in args.chains:
        chain_name, retriever = chain_map[chain_arg]
        report = _evaluate_chain(name=chain_name, retriever=retriever, queries=queries, verbose=args.verbose)
        reports.append(report)
        exact_rows.extend(report["exact_rows"])
        expanded_rows.extend(report["expanded_rows"])
        verbose_rows.extend(report["verbose_rows"])

    print("\n[3/3] Writing results...")
    exact_csv = run_dir / "detailed_exact.csv"
    expanded_csv = run_dir / "detailed_expanded.csv"
    _write_csv(exact_csv, exact_rows)
    _write_csv(expanded_csv, expanded_rows)

    summary = {
        "meta": {
            "dataset": str(dataset_path),
            "run_at": datetime.now(timezone.utc).isoformat(),
            "total_queries": len(queries),
            "chains": args.chains,
            "llm_model": settings.LLM_MODEL,
            "embedding_model": settings.EMBEDDING_MODEL,
            "traditional_hybrid_params": {
                "rrf_k": RRF_K,
                "vector_weight": VECTOR_WEIGHT,
                "bm25_weight": BM25_WEIGHT,
                "eval_k_values": K_VALUES,
            },
            "governed_evidence_params": _governed_evidence_params(),
        },
        "chains": {
            report["chain"]: {
                "evaluated": len(report["exact_rows"]),
                "failed": len(report["failures"]),
                "exact": report["exact_aggregates"],
                "expanded": report["expanded_aggregates"],
                "overview": {
                    "exact_hit@10_rate": round(
                        sum(row["hit@10"] for row in report["exact_rows"]) / len(report["exact_rows"]), 4
                    )
                    if report["exact_rows"]
                    else 0,
                    "expanded_hit@10_rate": round(
                        sum(row["hit@10"] for row in report["expanded_rows"]) / len(report["expanded_rows"]), 4
                    )
                    if report["expanded_rows"]
                    else 0,
                    "expanded_mrr_zero_count": sum(1 for row in report["expanded_rows"] if row["mrr"] == 0),
                },
                "failures": report["failures"],
            }
            for report in reports
        },
    }
    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.verbose:
        verbose_path = run_dir / "detailed_verbose.json"
        verbose_path.write_text(json.dumps(verbose_rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  Verbose: {verbose_path}")

    print(f"  Exact CSV: {exact_csv}")
    print(f"  Expanded CSV: {expanded_csv}")
    print(f"  Summary: {summary_path}")
    print("\nSummary:")
    for chain_name, chain_summary in summary["chains"].items():
        exact = chain_summary["exact"]
        expanded = chain_summary["expanded"]
        print(
            f"  {chain_name}: "
            f"exact R@10={exact['recall@10']['mean']:.3f}, "
            f"expanded R@10={expanded['recall@10']['mean']:.3f}, "
            f"expanded MRR={expanded['mrr']['mean']:.3f}, "
            f"expanded Hit@10={chain_summary['overview']['expanded_hit@10_rate']:.1%}"
        )


if __name__ == "__main__":
    main()
