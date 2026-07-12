# prism/engine/eval/run_governed_eval.py
"""Step 3: Governed Knowledge V2 评测 — A/B 对比 hybrid_search(baseline) vs 向量优先 v2。

用法:
    cd engine && python -m eval.run_governed_eval [--dataset path/to/golden.json] [--verbose]

评测两条链路在同一黄金数据集上的表现：
  A (baseline): hybrid_search (向量+BM25 RRF) — 现有 chunk 级检索
  B (v2):       governed_v2 向量召回 → 反查 PKU → 聚合 CKP — 新方案

输出:
    eval/results/<timestamp>_governed/
        comparison.csv      — 每个 query 的 A/B 指标对比
        summary.json        — 聚合统计 + A/B 对比
        detailed_verbose.json (--verbose) — 含检索结果正文
"""
import csv
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from sqlalchemy import create_engine as _ce
from sqlalchemy.orm import sessionmaker as _sm

from backend.app.models.knowledge_governance import (
    CanonicalKnowledgePoint,
    PKUCanonicalLink,
    PersonalKnowledgeUnit,
)
from backend.app.models.knowledge_item import KnowledgeChunk
from engine.app.config import settings
from engine.app.retrieval.hybrid import hybrid_search, RRF_K, VECTOR_WEIGHT, BM25_WEIGHT
from engine.app.agent.tools.governed_knowledge_v2 import _query_governed_v2

# ─── 配置 ──────────────────────────────────────────────
DEFAULT_DATASET = Path(__file__).resolve().parent / "golden_dataset.json"
RESULTS_DIR = Path(__file__).resolve().parent / "results"
K_VALUES = [5, 10, 20]
TOP_K_CHUNKS = 20  # v2 向量召回的 chunk 数量


# ─── 指标计算（复用 run_retrieval.py 的逻辑） ──────────

def _compute_metrics(retrieved_ids, relevant_ids, k_values=K_VALUES):
    max_k = max(k_values)
    retrieved = retrieved_ids[:max_k]
    relevant = set(relevant_ids)
    metrics = {}
    first_relevant_rank = None
    for rank, cid in enumerate(retrieved, start=1):
        if cid in relevant:
            first_relevant_rank = rank
            break
    metrics["first_relevant_rank"] = first_relevant_rank
    metrics["mrr"] = 1.0 / first_relevant_rank if first_relevant_rank else 0.0
    for k in k_values:
        top_k = retrieved[:k]
        hits = sum(1 for cid in top_k if cid in relevant)
        recall = hits / len(relevant_ids) if relevant_ids else 0.0
        precision = hits / k
        hit = 1 if hits > 0 else 0
        dcg = sum(1.0 / math.log2(rank + 1) for rank, cid in enumerate(top_k, start=1) if cid in relevant)
        idcg = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(relevant_ids), k) + 1))
        ndcg = dcg / idcg if idcg > 0 else 0.0
        metrics[f"recall@{k}"] = recall
        metrics[f"precision@{k}"] = precision
        metrics[f"hit@{k}"] = hit
        metrics[f"ndcg@{k}"] = ndcg
    return metrics


def _aggregate(values):
    n = len(values)
    if n == 0:
        return {"mean": 0, "median": 0, "std": 0, "min": 0, "max": 0}
    mean = sum(values) / n
    median = sorted(values)[n // 2]
    variance = sum((v - mean) ** 2 for v in values) / n
    std = math.sqrt(variance)
    return {
        "mean": round(mean, 4),
        "median": round(median, 4),
        "std": round(std, 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
    }


# ─── CKP ground truth 推导 ─────────────────────────────

def _derive_ckp_ground_truth(db, parent_chunk_ids: list[str]) -> set[str]:
    """从 golden 的 parent_chunk_id 推导 CKP ground truth。

    parent_chunk_id → PKU(source_kind='document_chunk', source_id=parent_id) → CKP(canonical_id)
    """
    if not parent_chunk_ids:
        return set()
    pkus = (
        db.query(PersonalKnowledgeUnit)
        .filter(
            PersonalKnowledgeUnit.source_kind == "document_chunk",
            PersonalKnowledgeUnit.source_id.in_(parent_chunk_ids),
            PersonalKnowledgeUnit.status == "active",
        )
        .all()
    )
    if not pkus:
        return set()
    pku_ids = [p.id for p in pkus]
    links = db.query(PKUCanonicalLink).filter(PKUCanonicalLink.pku_id.in_(pku_ids)).all()
    return {link.canonical_id for link in links}


def _load_chunk_texts(chunk_ids: list[str]) -> dict[str, str]:
    eng = _ce(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
    Sess = _sm(bind=eng)
    db = Sess()
    try:
        chunks = db.query(KnowledgeChunk).filter(KnowledgeChunk.id.in_(chunk_ids)).all()
        return {c.id: c.chunk_text for c in chunks}
    finally:
        db.close()


# ─── 主流程 ────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Prism Governed Knowledge V2 评测 (A/B 对比)")
    parser.add_argument("--dataset", type=str, default=str(DEFAULT_DATASET))
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        print(f"[!] 数据集不存在: {dataset_path}")
        sys.exit(1)

    print("=" * 70)
    print("Prism Governed Knowledge V2 评测 — A/B 对比 Benchmark")
    print("=" * 70)
    print(f"\n[1/4] 加载数据集: {dataset_path}")
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    queries = dataset["queries"]
    meta = dataset.get("meta", {})
    print(f"  问题数: {len(queries)}")
    print(f"  当前 Embedding: {settings.EMBEDDING_MODEL}")

    # DB 连接（用于推导 CKP ground truth）
    eng = _ce(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
    Sess = _sm(bind=eng)
    db = Sess()

    print(f"\n[2/4] 执行 A/B 检索 (top_k={max(K_VALUES)})...")
    print(f"  A (baseline): hybrid_search (RRF k={RRF_K}, vec_w={VECTOR_WEIGHT}, bm25_w={BM25_WEIGHT})")
    print(f"  B (v2):       vector-first (top_k_chunks={TOP_K_CHUNKS}) → PKU → CKP")

    results = []
    ckp_gt_count = 0
    ckp_evaluable = 0

    for i, q in enumerate(queries):
        qid = q["id"]
        question = q["question"]
        relevant_ids = {c["chunk_id"] for c in q["relevant_children"]}
        parent_chunk_id = q.get("parent_chunk_id", "")

        # ── A: baseline hybrid_search ──
        try:
            a_hits = hybrid_search(question, top_k=max(K_VALUES))
        except Exception as e:
            a_hits = []
            print(f"  [{i+1}/{len(queries)}] {qid} A-ERROR: {e}")
        a_retrieved = [h["chunk_id"] for h in a_hits]
        a_metrics = _compute_metrics(a_retrieved, relevant_ids)

        # ── B: v2 向量优先 ──
        try:
            b_chunk_hits, b_bundles, b_knowledge, b_raw = _query_governed_v2(
                question, limit=max(K_VALUES), top_k_chunks=TOP_K_CHUNKS
            )
        except Exception as e:
            b_chunk_hits, b_bundles, b_knowledge, b_raw = [], [], [], []
            print(f"  [{i+1}/{len(queries)}] {qid} B-ERROR: {e}")
        b_retrieved = [h["chunk_id"] for h in b_chunk_hits]
        b_metrics = _compute_metrics(b_retrieved, relevant_ids)

        # ── CKP 层评测 ──
        ckp_gt = _derive_ckp_ground_truth(db, [parent_chunk_id]) if parent_chunk_id else set()
        if ckp_gt:
            ckp_evaluable += 1
        b_ckp_ids = {b["canonical_id"] for b in b_bundles}
        ckp_hit = 1 if (ckp_gt and b_ckp_ids & ckp_gt) else 0
        ckp_precision = len(b_ckp_ids & ckp_gt) / len(b_ckp_ids) if b_ckp_ids else 0.0
        ckp_recall = len(b_ckp_ids & ckp_gt) / len(ckp_gt) if ckp_gt else 0.0

        result = {
            "query_id": qid,
            "question": question,
            "language": q.get("language", "?"),
            "item_title": q.get("item_title", ""),
            "relevant_count": len(relevant_ids),
            # A (baseline)
            "a_recall@10": a_metrics["recall@10"],
            "a_recall@20": a_metrics["recall@20"],
            "a_hit@10": a_metrics["hit@10"],
            "a_mrr": a_metrics["mrr"],
            "a_ndcg@10": a_metrics["ndcg@10"],
            # B (v2)
            "b_recall@10": b_metrics["recall@10"],
            "b_recall@20": b_metrics["recall@20"],
            "b_hit@10": b_metrics["hit@10"],
            "b_mrr": b_metrics["mrr"],
            "b_ndcg@10": b_metrics["ndcg@10"],
            # CKP 层
            "ckp_gt_count": len(ckp_gt),
            "ckp_returned": len(b_ckp_ids),
            "ckp_hit": ckp_hit,
            "ckp_precision": round(ckp_precision, 4),
            "ckp_recall": round(ckp_recall, 4),
            # 详情
            "a_chunk_count": len(a_hits),
            "b_chunk_count": len(b_chunk_hits),
            "b_ckp_count": len(b_bundles),
        }
        results.append(result)
        if ckp_gt:
            ckp_gt_count += 1

        a_status = "OK" if a_metrics["hit@10"] else "XX"
        b_status = "OK" if b_metrics["hit@10"] else "XX"
        ckp_tag = f"CKP={len(b_bundles)}(gt={len(ckp_gt)})" if ckp_gt else "CKP=n/a"
        print(
            f"  [{i+1}/{len(queries)}] A:{a_status} B:{b_status} {qid} "
            f"A_R@10={a_metrics['recall@10']:.2f} B_R@10={b_metrics['recall@10']:.2f} "
            f"A_MRR={a_metrics['mrr']:.2f} B_MRR={b_metrics['mrr']:.2f} {ckp_tag} "
            f"| {question[:30]}..."
        )

    db.close()

    # ── 输出 ──
    print(f"\n[3/4] 输出结果...")
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
    run_dir = RESULTS_DIR / f"{run_ts}_governed"
    run_dir.mkdir(parents=True, exist_ok=True)

    # comparison.csv
    csv_path = run_dir / "comparison.csv"
    csv_fields = [
        "query_id", "question", "language", "item_title", "relevant_count",
        "a_recall@10", "a_recall@20", "a_hit@10", "a_mrr", "a_ndcg@10",
        "b_recall@10", "b_recall@20", "b_hit@10", "b_mrr", "b_ndcg@10",
        "ckp_gt_count", "ckp_returned", "ckp_hit", "ckp_precision", "ckp_recall",
        "a_chunk_count", "b_chunk_count", "b_ckp_count",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)
    print(f"  CSV: {csv_path}")

    # summary.json
    metric_keys_a = ["a_recall@5", "a_recall@10", "a_recall@20", "a_precision@10", "a_hit@10", "a_ndcg@10", "a_mrr"]
    metric_keys_b = ["b_recall@5", "b_recall@10", "b_recall@20", "b_precision@10", "b_hit@10", "b_ndcg@10", "b_mrr"]

    # 补充 @5 指标
    for r in results:
        pass  # @5 在 _compute_metrics 里有但没存到 result，这里用已有字段

    summary = {
        "meta": {
            "dataset": str(dataset_path),
            "run_at": datetime.now(timezone.utc).isoformat(),
            "total_queries": len(queries),
            "evaluated": len(results),
            "llm_model": settings.LLM_MODEL,
            "embedding_model": settings.EMBEDDING_MODEL,
            "hybrid_params": {"rrf_k": RRF_K, "vector_weight": VECTOR_WEIGHT, "bm25_weight": BM25_WEIGHT},
            "v2_params": {"top_k_chunks": TOP_K_CHUNKS, "retrieval_path": "vector_first"},
        },
        "baseline_aggregates": {
            m: _aggregate([r[m] for r in results])
            for m in ["a_recall@10", "a_recall@20", "a_hit@10", "a_mrr", "a_ndcg@10"]
        },
        "v2_aggregates": {
            m: _aggregate([r[m] for r in results])
            for m in ["b_recall@10", "b_recall@20", "b_hit@10", "b_mrr", "b_ndcg@10"]
        },
        "ckp_layer": {
            "queries_with_ckp_ground_truth": ckp_evaluable,
            "ckp_hit_rate": round(sum(r["ckp_hit"] for r in results) / ckp_evaluable, 4) if ckp_evaluable else 0,
            "avg_ckp_precision": _aggregate([r["ckp_precision"] for r in results if r["ckp_gt_count"] > 0])["mean"],
            "avg_ckp_recall": _aggregate([r["ckp_recall"] for r in results if r["ckp_gt_count"] > 0])["mean"],
            "avg_ckp_returned": _aggregate([r["ckp_returned"] for r in results])["mean"],
        },
        "comparison": {
            "recall@10_delta_mean": round(
                sum(r["b_recall@10"] - r["a_recall@10"] for r in results) / len(results), 4
            ),
            "mrr_delta_mean": round(
                sum(r["b_mrr"] - r["a_mrr"] for r in results) / len(results), 4
            ),
            "hit@10_rate_a": round(sum(r["a_hit@10"] for r in results) / len(results), 4),
            "hit@10_rate_b": round(sum(r["b_hit@10"] for r in results) / len(results), 4),
        },
    }

    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  JSON: {summary_path}")

    # verbose
    if args.verbose:
        all_chunk_ids = set()
        for r in results:
            pass
        verbose_output = []
        for i, q in enumerate(queries):
            qid = q["id"]
            r = results[i]
            try:
                b_chunk_hits, b_bundles, _, _ = _query_governed_v2(
                    q["question"], limit=max(K_VALUES), top_k_chunks=TOP_K_CHUNKS
                )
            except Exception:
                b_chunk_hits, b_bundles = [], []
            all_chunk_ids.update(h["chunk_id"] for h in b_chunk_hits)
            verbose_output.append({
                "query_id": qid,
                "question": q["question"],
                "b_chunk_hits": [{"chunk_id": h["chunk_id"], "score": h["score"]} for h in b_chunk_hits],
                "b_ckps": [{"canonical_id": b["canonical_id"], "title": b["title"], "score": b["score"]} for b in b_bundles],
            })
        text_map = _load_chunk_texts(list(all_chunk_ids))
        for entry in verbose_output:
            for h in entry["b_chunk_hits"]:
                h["chunk_text"] = text_map.get(h["chunk_id"], "[NOT FOUND]")[:200]
        verbose_path = run_dir / "detailed_verbose.json"
        verbose_path.write_text(json.dumps(verbose_output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  Verbose: {verbose_path}")

    # ── 终端摘要 ──
    print(f"\n[4/4] 评估摘要")
    print(f"{'=' * 70}")
    print(f"评估问题数: {len(results)}/{len(queries)}")
    print()
    print(f"{'指标':<20} {'A(baseline)':<20} {'B(v2 vector-first)':<20} {'Δ':<12}")
    print(f"{'-'*72}")
    for m_label, a_key, b_key in [
        ("Recall@10", "a_recall@10", "b_recall@10"),
        ("Recall@20", "a_recall@20", "b_recall@20"),
        ("Hit@10 rate", None, None),
        ("MRR", "a_mrr", "b_mrr"),
        ("NDCG@10", "a_ndcg@10", "b_ndcg@10"),
    ]:
        if a_key:
            a_mean = summary["baseline_aggregates"][a_key]["mean"]
            b_mean = summary["v2_aggregates"][b_key]["mean"]
            delta = b_mean - a_mean
            print(f"{m_label:<20} {a_mean:<20.4f} {b_mean:<20.4f} {delta:+.4f}")
        else:
            a_rate = summary["comparison"]["hit@10_rate_a"]
            b_rate = summary["comparison"]["hit@10_rate_b"]
            print(f"{m_label:<20} {a_rate:<20.4f} {b_rate:<20.4f} {b_rate-a_rate:+.4f}")

    print()
    ckp = summary["ckp_layer"]
    print(f"CKP 层评测:")
    print(f"  有 CKP ground truth 的问题数: {ckp['queries_with_ckp_ground_truth']}/{len(results)}")
    if ckp["queries_with_ckp_ground_truth"] > 0:
        print(f"  CKP hit rate:     {ckp['ckp_hit_rate']:.4f}")
        print(f"  CKP precision:    {ckp['avg_ckp_precision']:.4f}")
        print(f"  CKP recall:       {ckp['avg_ckp_recall']:.4f}")
        print(f"  Avg CKP returned: {ckp['avg_ckp_returned']:.2f}")
    else:
        print(f"  (黄金数据集中的 chunk 无关联 PKU/CKP，CKP 层指标为 N/A)")

    print(f"\n结果目录: {run_dir}")


if __name__ == "__main__":
    main()
