# prism/engine/eval/run_retrieval.py
"""Step 2: 加载黄金数据集 → 执行 hybrid_search → 输出检索评估结果。

用法:
    cd engine && python -m eval.run_retrieval [--dataset path/to/golden.json]

输出:
    eval/results/<timestamp>/
        detailed.csv   — 每个 query 的检索明细和指标
        summary.json   — 聚合统计
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

from engine.app.retrieval.hybrid import RRF_K, VECTOR_WEIGHT, BM25_WEIGHT
from engine.app.retrieval.contracts import SearchScope
from engine.app.retrieval.unified import scoped_text_hybrid_search
from engine.app.config import settings

# ─── 配置 ──────────────────────────────────────────────
DEFAULT_DATASET = Path(__file__).resolve().parent / "golden_dataset.json"
RESULTS_DIR = Path(__file__).resolve().parent / "results"
K_VALUES = [5, 10, 20]  # 在不同截断点评估


# ─── 指标计算 ──────────────────────────────────────────

def _compute_metrics(
    retrieved_ids: list[str],
    relevant_ids: set[str],
    k_values: list[int] = K_VALUES,
) -> dict:
    """对单次检索结果计算所有指标。"""
    max_k = max(k_values)
    retrieved = retrieved_ids[:max_k]
    relevant = set(relevant_ids)

    metrics = {}
    first_relevant_rank = None

    # 找到第一个相关 chunk 的排名 (1-based)
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

        # NDCG@k: 相关=1, 不相关=0
        dcg = sum(
            (1.0 / math.log2(rank + 1))
            for rank, cid in enumerate(top_k, start=1)
            if cid in relevant
        )
        idcg = sum(
            1.0 / math.log2(i + 1)
            for i in range(1, min(len(relevant_ids), k) + 1)
        )
        ndcg = dcg / idcg if idcg > 0 else 0.0

        metrics[f"recall@{k}"] = recall
        metrics[f"precision@{k}"] = precision
        metrics[f"hit@{k}"] = hit
        metrics[f"ndcg@{k}"] = ndcg

    return metrics


def _format_retrieved_list(retrieved: list[dict], relevant_ids: set[str]) -> str:
    """将检索结果格式化为可读字符串，标记是否相关。"""
    parts = []
    for i, r in enumerate(retrieved):
        cid = r["chunk_id"]
        score = r["score"]
        is_rel = "★" if cid in relevant_ids else " "
        parts.append(f"{is_rel}#{i + 1}:{cid[:8]}...({score:.4f})")
    return " | ".join(parts)


def _load_chunk_texts(chunk_ids: list[str]) -> dict[str, str]:
    """批量从 MySQL 加载 chunk 正文。"""
    from sqlalchemy import create_engine as _ce
    from sqlalchemy.orm import sessionmaker as _sm
    from backend.app.models.knowledge_item import KnowledgeChunk

    eng = _ce(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
    Sess = _sm(bind=eng)
    db = Sess()
    try:
        chunks = db.query(KnowledgeChunk).filter(
            KnowledgeChunk.id.in_(chunk_ids)
        ).all()
        return {c.id: c.chunk_text for c in chunks}
    finally:
        db.close()


# ─── 主流程 ────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Prism 检索评估")
    parser.add_argument(
        "--dataset",
        type=str,
        default=str(DEFAULT_DATASET),
        help=f"黄金数据集路径 (默认: {DEFAULT_DATASET})",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="同时输出 detailed_verbose.json，包含检索结果的 chunk 正文",
    )
    parser.add_argument("--tenant-id", required=True); parser.add_argument("--kb-uid", required=True)
    parser.add_argument("--index-generation", required=True); parser.add_argument("--graph-generation")
    args = parser.parse_args()
    scope = SearchScope(tenant_id=args.tenant_id, kb_uid=args.kb_uid, index_generation=args.index_generation, graph_generation=args.graph_generation)

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        print(f"[!] 数据集不存在: {dataset_path}")
        print(f"    请先运行 python -m eval.generate_queries 生成")
        sys.exit(1)

    # 1. 加载数据集
    print("=" * 60)
    print("Prism 检索评估 — 离线 Benchmark")
    print("=" * 60)
    print(f"\n[1/3] 加载数据集: {dataset_path}")
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    queries = dataset["queries"]
    meta = dataset.get("meta", {})
    print(f"  问题数: {len(queries)}")
    print(f"  数据集模型: {meta.get('llm_model', 'unknown')}")
    print(f"  数据集创建: {meta.get('created_at', 'unknown')}")
    print(f"  当前 LLM: {settings.LLM_MODEL}")
    print(f"  当前 Embedding: {settings.EMBEDDING_MODEL}")

    # 2. 逐条检索
    print(f"\n[2/3] 执行混合检索 (top_k={max(K_VALUES)}, RRF k={RRF_K}, "
          f"向量权重={VECTOR_WEIGHT}, BM25权重={BM25_WEIGHT})...")

    results = []
    failures = []

    for i, q in enumerate(queries):
        qid = q["id"]
        question = q["question"]
        # 兼容新旧格式: relevant_children (新) vs relevant_child_ids (旧)
        if "relevant_children" in q:
            relevant_ids = {c["chunk_id"] for c in q["relevant_children"]}
        else:
            relevant_ids = set(q["relevant_child_ids"])

        try:
            hits = scoped_text_hybrid_search(question, scope, top_k=max(K_VALUES))
        except Exception as e:
            print(f"  [{i + 1}/{len(queries)}] {qid} ERROR: {e}")
            failures.append({"query_id": qid, "question": question, "error": str(e)})
            continue

        retrieved_ids = [h["chunk_id"] for h in hits]
        retrieved_items = [
            {"rank": j + 1, "chunk_id": h["chunk_id"], "score": h["score"],
             "relevant": h["chunk_id"] in relevant_ids}
            for j, h in enumerate(hits)
        ]

        metrics = _compute_metrics(retrieved_ids, relevant_ids)

        result = {
            "query_id": qid,
            "question": question,
            "language": q.get("language", "?"),
            "item_title": q.get("item_title", ""),
            "relevant_count": len(relevant_ids),
            **metrics,
            "retrieved_detail": _format_retrieved_list(hits, relevant_ids),
            "retrieved_items": retrieved_items,
        }
        results.append(result)

        status = "OK" if metrics["hit@10"] else "XX"
        print(f"  [{i + 1}/{len(queries)}] {status} {qid} "
              f"R@5={metrics['recall@5']:.2f} R@10={metrics['recall@10']:.2f} "
              f"MRR={metrics['mrr']:.2f} | {question[:40]}...")

    # 3. 输出结果
    print(f"\n[3/3] 输出结果...")
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
    run_dir = RESULTS_DIR / run_ts
    run_dir.mkdir(parents=True, exist_ok=True)

    # 3a. detailed.csv
    csv_path = run_dir / "detailed.csv"
    csv_fields = [
        "query_id", "question", "language", "item_title", "relevant_count",
        *[f"recall@{k}" for k in K_VALUES],
        *[f"precision@{k}" for k in K_VALUES],
        *[f"hit@{k}" for k in K_VALUES],
        *[f"ndcg@{k}" for k in K_VALUES],
        "mrr", "first_relevant_rank", "retrieved_detail",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)
    print(f"  CSV: {csv_path}")

    # 3b. verbose JSON (可选，带检索结果正文)
    if args.verbose:
        verbose_path = run_dir / "detailed_verbose.json"
        print(f"  [verbose] 加载检索结果正文...")
        # 收集所有被检索到的 chunk_id
        all_retrieved_ids = set()
        for r in results:
            for item in r["retrieved_items"]:
                all_retrieved_ids.add(item["chunk_id"])
        text_map = _load_chunk_texts(list(all_retrieved_ids))
        print(f"  [verbose] 加载了 {len(text_map)} 个 chunk 正文")

        verbose_output = []
        for r in results:
            entry = {
                "query_id": r["query_id"],
                "question": r["question"],
                "language": r["language"],
                "item_title": r["item_title"],
                "relevant_count": r["relevant_count"],
                "metrics": {
                    f"recall@{k}": r[f"recall@{k}"] for k in K_VALUES
                },
                "mrr": r["mrr"],
                "retrieved": [],
            }
            for item in r["retrieved_items"]:
                cid = item["chunk_id"]
                entry["retrieved"].append({
                    "rank": item["rank"],
                    "chunk_id": cid,
                    "score": item["score"],
                    "relevant": item["relevant"],
                    "chunk_text": text_map.get(cid, "[NOT FOUND]")[:200],
                })
            verbose_output.append(entry)

        verbose_path.write_text(
            json.dumps(verbose_output, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"  Verbose JSON: {verbose_path}")

    # 3c. summary.json
    agg = {}
    metric_names = [
        *[f"recall@{k}" for k in K_VALUES],
        *[f"precision@{k}" for k in K_VALUES],
        *[f"hit@{k}" for k in K_VALUES],
        *[f"ndcg@{k}" for k in K_VALUES],
        "mrr",
    ]
    for m in metric_names:
        values = [r[m] for r in results]
        n = len(values)
        mean = sum(values) / n if n else 0
        median = sorted(values)[n // 2] if n else 0
        variance = sum((v - mean) ** 2 for v in values) / n if n else 0
        std = math.sqrt(variance)
        agg[m] = {
            "mean": round(mean, 4),
            "median": round(median, 4),
            "std": round(std, 4),
            "min": round(min(values), 4) if values else 0,
            "max": round(max(values), 4) if values else 0,
        }

    # 额外统计
    hit10_queries = sum(1 for r in results if r["hit@10"])
    mrr0_queries = [r for r in results if r["mrr"] == 0]

    summary = {
        "meta": {
            "dataset": str(dataset_path),
            "run_at": datetime.now(timezone.utc).isoformat(),
            "total_queries": len(queries),
            "evaluated": len(results),
            "failed": len(failures),
            "llm_model": settings.LLM_MODEL,
            "embedding_model": settings.EMBEDDING_MODEL,
            "hybrid_params": {
                "rrf_k": RRF_K,
                "vector_weight": VECTOR_WEIGHT,
                "bm25_weight": BM25_WEIGHT,
                "eval_k_values": K_VALUES,
            },
        },
        "aggregates": agg,
        "overview": {
            "hit@10_rate": round(hit10_queries / len(results), 4) if results else 0,
            "mrr_zero_count": len(mrr0_queries),
            "mrr_zero_queries": [r["query_id"] for r in mrr0_queries],
        },
        "failures": failures,
    }

    summary_path = run_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  JSON: {summary_path}")

    # 3c. 终端摘要
    print(f"\n{'=' * 60}")
    print("评估摘要")
    print(f"{'=' * 60}")
    print(f"评估问题数: {len(results)}/{len(queries)} (失败: {len(failures)})")
    for k in K_VALUES:
        r = agg[f"recall@{k}"]
        print(f"Recall@{k:>2}:  均值={r['mean']:.3f}  中位数={r['median']:.3f}  "
              f"σ={r['std']:.3f}  范围=[{r['min']:.3f}, {r['max']:.3f}]")
    print(f"MRR:       均值={agg['mrr']['mean']:.3f}  中位数={agg['mrr']['median']:.3f}  "
          f"σ={agg['mrr']['std']:.3f}")
    print(f"Hit@10:    {summary['overview']['hit@10_rate']:.1%} ({hit10_queries}/{len(results)})")
    print(f"MRR=0:     {len(mrr0_queries)} 个问题完全没命中")
    if mrr0_queries:
        print(f"           IDs: {', '.join(r['query_id'] for r in mrr0_queries)}")
    print(f"\n结果目录: {run_dir}")


if __name__ == "__main__":
    main()
