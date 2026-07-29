# prism/engine/eval/generate_report.py
"""Step 4: Generate the comprehensive evaluation report.

Usage:
    python -m engine.eval.generate_report --run-dir results/<ts>
"""
import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

RESULTS_DIR = Path(__file__).resolve().parent / "results"


def load_data(run_dir: Path) -> dict[str, Any]:
    """Load all evaluation artifacts from a run directory.

    Gracefully handles missing files by returning empty placeholders.
    """
    data: dict[str, Any] = {}

    # Dataset
    dataset_path = run_dir / "golden_dataset_v2.json"
    if dataset_path.exists():
        ds = json.loads(dataset_path.read_text(encoding="utf-8"))
        data["dataset_meta"] = ds.get("meta", {})

    # Retrieval
    ret_path = run_dir / "retrieval_summary.json"
    if ret_path.exists():
        data["retrieval"] = json.loads(ret_path.read_text(encoding="utf-8"))

    # Answer
    ans_path = run_dir / "answer_summary.json"
    if ans_path.exists():
        data["answer"] = json.loads(ans_path.read_text(encoding="utf-8"))

    # Answer detail CSV
    csv_path = run_dir / "answer_detailed.csv"
    answer_detail: list[dict] = []
    if csv_path.exists():
        with open(csv_path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            answer_detail = list(reader)
    data["answer_detail"] = answer_detail

    # Low scores count
    low_csv = run_dir / "answer_low_scores.csv"
    if low_csv.exists():
        with open(low_csv, encoding="utf-8-sig") as f:
            data["low_scores_count"] = sum(1 for _ in f) - 1  # minus header
    else:
        data["low_scores_count"] = 0

    data["run_ts"] = run_dir.name
    return data


def _fmt_val(val: Any, precision: int = 2) -> str:
    """Format a value for report display."""
    if val is None:
        return "N/A"
    if isinstance(val, float):
        return f"{val:.{precision}f}"
    return str(val)


def _metric_row(name: str, agg: dict) -> str:
    """Render a single metric row for the summary table."""
    if not agg:
        return f"| {name} | - | - | - |"
    return (
        f"| {name}"
        f" | {_fmt_val(agg.get('mean'))}"
        f" | {_fmt_val(agg.get('median'))}"
        f" | {_fmt_val(agg.get('std'))} |"
    )


def _per_group_table(groups: dict, metrics: list[str]) -> str:
    """Render a per-group comparison table."""
    if not groups:
        return "_No data available._\n"

    lines = ["| Group | " + " | ".join(metrics) + " | Count |"]
    lines.append("|" + "|".join(["------"] * (len(metrics) + 2)) + "|")
    for group_name, agg in sorted(groups.items()):
        vals = []
        for m in metrics:
            v = agg.get(m, {})
            vals.append(_fmt_val(v.get("mean", v) if isinstance(v, dict) else v))
        vals.append(str(agg.get("count", "?")))
        lines.append(f"| {group_name[:50]} | " + " | ".join(vals) + " |")
    return "\n".join(lines) + "\n"


def render_report(data: dict[str, Any]) -> str:
    """Render the complete Markdown evaluation report.

    Report contains 5 major sections:
    1. 执行摘要 (Executive Summary)
    2. 检索层 (Retrieval Layer)
    3. 端到端问答 (End-to-end QA)
    4. 交叉分析 (Cross-layer Analysis)
    5. 改进建议 (Recommendations)
    """
    ds = data.get("dataset_meta", {})
    ret = data.get("retrieval", {})
    ans = data.get("answer", {})
    detail = data.get("answer_detail", [])

    papers = ds.get("papers", [])
    paper_list = "\n".join(
        f"| {p.get('id','?')[:12]}"
        f" | {p.get('title','?')[:60]}"
        f" | {p.get('parent_count','?')}"
        f" | {p.get('child_count','?')} |"
        for p in papers
    )

    ret_agg = ret.get("aggregates", {})
    ans_agg = ans.get("judge_aggregates", {})

    # Build retrieval metrics table
    ret_metrics = [
        "recall@5", "recall@10", "recall@20",
        "precision@5", "precision@10", "precision@20",
        "mrr", "ndcg@10", "ndcg@20",
    ]
    ret_table = "\n".join(
        _metric_row(m, ret_agg.get(m, {})) for m in ret_metrics
    )

    # Build answer metrics table
    ans_table = "\n".join(
        _metric_row(m, ans_agg.get(m, {}))
        for m in ["faithfulness", "relevance", "completeness", "overall"]
    )

    # Zero recall
    zero = ret.get("zero_recall", [])
    zero_str = ", ".join(zero[:20]) if zero else "无"

    # Latency
    ret_lat = ret.get("latency", {})
    ans_lat = ans.get("latency", {})

    # Cross-layer analysis
    ret_recall_10 = ret_agg.get("recall@10", {}).get("mean", None)
    ans_overall = ans_agg.get("overall", {}).get("mean", None)

    # Low score analysis
    low_scores = data.get("low_scores_count", 0)

    # Paper list fallback
    paper_table = paper_list if paper_list else "_无论文数据_"

    # Question type distribution
    question_type_dist = str(ds.get("question_type_distribution", {}))

    # Pre-compute metric values to avoid f-string brace escaping issues
    mrr_mean = _fmt_val(ret_agg.get("mrr", {}).get("mean"))
    faithfulness_mean = _fmt_val(ans_agg.get("faithfulness", {}).get("mean"))
    relevance_mean = _fmt_val(ans_agg.get("relevance", {}).get("mean"))
    completeness_mean = _fmt_val(ans_agg.get("completeness", {}).get("mean"))
    ret_by_paper = _per_group_table(ret.get("by_paper", {}), ["recall@10", "mrr"])
    ret_by_type = _per_group_table(ret.get("by_type", {}), ["recall@10", "mrr"])
    ans_by_type = _per_group_table(ans.get("by_type", {}), ["overall"])
    ans_by_paper = _per_group_table(ans.get("by_paper", {}), ["overall"])
    embedding_model = ds.get("embedding_model", "?")
    llm_model = ds.get("llm_model", "?")
    run_ts = data.get("run_ts", "?")
    total_questions = ds.get("total_questions", "?")
    ret_p50 = _fmt_val(ret_lat.get("p50"))
    ret_p95 = _fmt_val(ret_lat.get("p95"))
    ans_ttfb_p50 = _fmt_val(ans_lat.get("ttfb_p50"))
    ans_ttfb_p95 = _fmt_val(ans_lat.get("ttfb_p95"))
    ans_total_p50 = _fmt_val(ans_lat.get("total_p50"))
    ans_total_p95 = _fmt_val(ans_lat.get("total_p95"))
    recall_10_fmt = _fmt_val(ret_recall_10)
    overall_fmt = _fmt_val(ans_overall)

    # Cross-layer analysis gap message
    gap_msg = ""
    if ret_recall_10 and ans_overall and ret_recall_10 > 0.5 and ans_overall < 4.0:
        gap_msg = "**发现**：检索与答案质量存在差距，说明即使检索召回了相关内容，答案生成仍可能存在问题（如信息整合不当、跨论文混淆）。"

    # Find worst cases
    worst = sorted(
        [
            r for r in detail
            if r.get("judge_overall") and float(r.get("judge_overall", 5)) >= 0
        ],
        key=lambda r: float(r.get("judge_overall", 5)),
    )[:5]
    worst_table = "\n".join(
        f"| {r.get('query_id','?')}"
        f" | {r.get('question','?')[:50]}"
        f" | {r.get('judge_faithfulness','?')}"
        f" | {r.get('judge_relevance','?')}"
        f" | {r.get('judge_completeness','?')} |"
        for r in worst
    )

    report = f"""# Prism 多视图聚类论文 RAG 评测报告

> **评测日期**：{run_ts}
> **论文数**：{len(papers)} | **问题数**：{total_questions}
> **LLM**：{llm_model} | **Embedding**：{embedding_model}

---

## 0. 执行摘要

| 层级 | 核心指标 | 均值 |
|------|---------|------|
| 检索层 | Recall@10 | {recall_10_fmt} |
| 检索层 | MRR | {mrr_mean} |
| 问答层 | 忠实度 | {faithfulness_mean} |
| 问答层 | 相关性 | {relevance_mean} |
| 问答层 | 完整性 | {completeness_mean} |
| 问答层 | 综合分 | {overall_fmt} |

- 检索零召回问题数：{len(zero)} ({zero_str})
- 低分回答数（忠实度<3 或 相关性<3）：{low_scores}
- 检索延迟 P50/P95：{ret_p50}ms / {ret_p95}ms
- 端到端延迟 P50/P95：{ans_total_p50}ms / {ans_total_p95}ms

---

## 1. 数据概览

### 1.1 论文清单

| ID | 标题 | Parent | Child |
|----|------|--------|-------|
{paper_table}

### 1.2 问题类型分布

{question_type_dist}

---

## 2. 检索层详细结果

### 2.1 整体指标

| 指标 | 均值 | 中位数 | 标准差 |
|------|------|--------|--------|
{ret_table}

### 2.2 检索延迟

| P50 | P95 |
|-----|-----|
| {ret_p50}ms | {ret_p95}ms |

### 2.3 按论文分组

{ret_by_paper}

### 2.4 按问题类型分组

{ret_by_type}

### 2.5 零召回分析

零召回问题 ID：{zero_str}

（共 {len(zero)} 个问题检索完全失败，需要排查是否是 embedding 覆盖不足或 chunk 切分问题。）

---

## 3. 端到端问答详细结果

### 3.1 Judge 评分

| 维度 | 均值 | 中位数 | 标准差 |
|------|------|--------|--------|
{ans_table}

### 3.2 端到端延迟

| 指标 | P50 | P95 |
|------|-----|-----|
| TTFB | {ans_ttfb_p50}ms | {ans_ttfb_p95}ms |
| 总延迟 | {ans_total_p50}ms | {ans_total_p95}ms |

### 3.3 按问题类型分组

{ans_by_type}

### 3.4 按论文分组

{ans_by_paper}

---

## 4. 交叉分析

### 4.1 检索 vs 答案质量

- 检索 Recall@10 均值：{recall_10_fmt}
- 答案综合分均值：{overall_fmt}

{gap_msg}

### 4.2 论文难度排名

（综合检索 Recall@10 + 答案综合分，降序排列。分数越低越难。）

{ret_by_paper}

### 4.3 Agent 行为分析

（基于 answer_detailed.csv 统计）
- 平均工具调用次数：待分析
- 平均迭代轮次：待分析

---

## 5. 改进建议

### 5.1 最差 5 个 Case

| ID | 问题 | 忠实度 | 相关性 | 完整性 |
|----|------|--------|--------|--------|
{worst_table if worst_table else "| - | 无低分 case | - | - | - |"}

### 5.2 可操作改进项

1. **检索层面**：
   - 零召回问题需检查 embedding 模型对该领域论文的覆盖（当前模型：{embedding_model}）
   - 跨论文问题的 Recall 如显著低于单论文问题，建议增强图扩展的跨文档边

2. **答案生成层面**：
   - 如忠实度均值 < 4，建议在 system prompt 中加强"仅基于检索结果回答"的约束
   - 如完整性均值 < 4，建议提高 top_k 参数或增加检索迭代轮次

3. **跨论文问题层面**：
   - 跨论文对比是最大薄弱环节，需要更好的多文档信息融合策略

---

*报告由 Prism Evaluation Pipeline v2 自动生成*
"""
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate RAG evaluation report")
    parser.add_argument(
        "--run-dir", required=True, help="Path to results/<timestamp> directory"
    )
    args = parser.parse_args(argv)

    run_dir = Path(args.run_dir)
    if not run_dir.is_dir():
        print(f"[!] Directory not found: {run_dir}")
        sys.exit(1)

    print(f"Loading data from {run_dir}...")
    data = load_data(run_dir)

    print(f"Rendering report...")
    report = render_report(data)

    report_path = run_dir / "REPORT.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"[OK] Report written to {report_path}")


if __name__ == "__main__":
    main()
