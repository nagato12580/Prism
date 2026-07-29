# Multi-View RAG Evaluation Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone 4-step CLI pipeline that evaluates retrieval quality and end-to-end answer quality for 6 multi-view clustering papers, outputting a comprehensive Markdown report.

**Architecture:** Four independent Python CLI scripts under `engine/eval/` — dataset generation, retrieval evaluation, answer evaluation with LLM-as-Judge, and report generation. Each reads/writes JSON/CSV from `engine/eval/results/<timestamp>/`. Retrieval reuse existing `scoped_text_hybrid_search`; answer evaluation calls Engine's HTTP `/chat/answer` endpoint with a signed knowledge scope.

**Tech Stack:** Python 3.12+, sqlalchemy, pymysql, httpx, csv, json, dataclasses, pytest

## Global Constraints

- All code goes under `engine/eval/`; no modification to existing production files.
- Dataset format is backward-compatible with v1 (`relevant_children` field).
- Database access is read-only (no INSERT/UPDATE/DELETE).
- All LLM calls use existing `engine/app/llm/client.py::chat`.
- 100% Chinese questions.
- Results directory per run: `engine/eval/results/<YYYY-MM-DD_HHMM>/`.

---

### Task 1: Dataset Generation Script

**Files:**
- Create: `engine/eval/generate_queries_v2.py`
- Test: `engine/tests/test_generate_queries_v2.py`

**Interfaces:**
- Produces: `golden_dataset_v2.json` at `engine/eval/results/<ts>/golden_dataset_v2.json`
- Produces: CLI entry point `main()` — usage: `python -m engine.eval.generate_queries_v2 [--output PATH] [--seed 42]`
- Produces: `load_paper_parents(db)` → `list[dict]` — loads parent chunks for the 6 multi-view papers
- Produces: `generate_question(chunk_text, paper_title, question_type, index)` → `tuple[str, str]` — (question, language)
- Produces: `label_gold_chunks(question, parent_text, children)` → `list[dict]` — gold chunk labels
- Produces: `build_dataset(parents, question_types)` → `dict` — complete golden dataset

#### Paper Selection

The 6 multi-view papers are hardcoded by item_id (queried from `knowledge_item` where `source_ref LIKE '%.pdf'` and keyword filters on title for multi-view clustering papers). In practice, all 6 PDFs currently in the DB are multi-view clustering papers.

- [ ] **Step 1: Write failing test for `load_paper_parents`**

Create `engine/tests/test_generate_queries_v2.py`:

```python
import os, sys
from pathlib import Path
import pytest

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from dotenv import load_dotenv
load_dotenv(_project_root.parent / ".env")


def test_load_paper_parents_returns_six_papers():
    """All 6 multi-view papers should be loaded with parent chunks."""
    from engine.eval.generate_queries_v2 import load_paper_parents

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    db = sessionmaker(bind=engine)()

    try:
        parents = load_paper_parents(db)
        # 6 papers
        paper_ids = {p["item_id"] for p in parents}
        assert len(paper_ids) == 6, f"Expected 6 papers, got {len(paper_ids)}"

        # Each paper has at least one parent with children
        for paper_id in paper_ids:
            paper_parents = [p for p in parents if p["item_id"] == paper_id]
            assert len(paper_parents) > 0, f"Paper {paper_id} has no parents"
            for p in paper_parents:
                assert len(p["child_ids"]) > 0, f"Parent {p['parent_id']} has no children"
    finally:
        db.close()


def test_generate_question_returns_chinese():
    """Generated question should be in Chinese."""
    from engine.eval.generate_queries_v2 import generate_question

    chunk_text = """多视图子空间聚类是一种将多视图数据集成到统一框架中的方法。
    该方法通过学习每个视图的自我表示矩阵来捕获数据的子空间结构。"""

    question, lang = generate_question(chunk_text, "Test Paper", "fact", 0)
    assert lang == "zh"
    assert len(question) > 5
    # Should contain Chinese characters
    assert any('一' <= c <= '鿿' for c in question)


def test_label_gold_chunks_identifies_direct_chunks():
    """Gold chunk labeling should identify directly relevant chunks."""
    from engine.eval.generate_queries_v2 import label_gold_chunks

    question = "多视图子空间聚类的核心方法是什么？"
    parent_text = "多视图子空间聚类通过学习每个视图的自我表示矩阵来集成多视图数据。"
    children = [
        {"chunk_id": "c1", "chunk_text": "该方法通过学习每个视图的自我表示矩阵来捕获子空间结构。"},
        {"chunk_id": "c2", "chunk_text": "实验使用了三个基准数据集进行评估。"},
        {"chunk_id": "c3", "chunk_text": "对比方法包括谱聚类和深度聚类。"},
    ]

    labels = label_gold_chunks(question, parent_text, children)
    assert len(labels) == 3

    # c1 should be "direct" (directly answers the question)
    c1 = next(l for l in labels if l["chunk_id"] == "c1")
    assert c1["relevance"] in ("direct", "partial", "context")

    # All labels should have valid relevance values
    for label in labels:
        assert label["relevance"] in ("direct", "partial", "context")
        assert "chunk_id" in label
```

- [ ] **Step 2: Run tests and verify failure**

```bash
cd engine && DATABASE_URL=mysql+pymysql://root:CHANGE-ME@localhost:13306/prism_db python -m pytest tests/test_generate_queries_v2.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'engine.eval.generate_queries_v2'`

- [ ] **Step 3: Implement `load_paper_parents`**

Create `engine/eval/generate_queries_v2.py`:

```python
# prism/engine/eval/generate_queries_v2.py
"""Step 1: Generate a v2 golden dataset from multi-view clustering papers.

Usage:
    python -m engine.eval.generate_queries_v2 [--output PATH] [--seed 42]
"""
import argparse
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from backend.app.models.knowledge_item import KnowledgeChunk
from engine.app.config import settings
from engine.app.llm.client import chat

SAMPLE_SIZE_PER_PAPER = 14
CROSS_PAPER_COUNT = 13
OUTPUT_DIR = Path(__file__).resolve().parent / "results"

_engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
_Session = sessionmaker(bind=_engine)

# The 6 multi-view clustering paper IDs (from DB)
PAPER_IDS = [
    "c5f89f1f-fd12-4a0c-8f89-171696a0a620",  # Deep Contrastive Multi-View...
    "3f11ebc6-896d-4150-afe4-57464e395c23",  # 3746027.3754701.pdf
    "397509cf-25ad-4fd3-b53c-5af2e1af1ebf",  # s10044-025-01455-4.pdf
    "430254e3-cf42-4d7d-9906-0f25669c97e5",  # 11521_AF_UMC...
    "91be4c32-d302-4b31-aaad-3616bc00c4be",  # 33725-Article Text...
    "c1bb57c9-57d1-483e-a574-131a11c669ba",  # The_Name_of_the_Title_Is_Hope
]

QUESTION_TYPES = {
    "fact": 34,
    "concept": 17,
    "method_compare": 13,
    "data_detail": 8,
    "cross_paper": 13,
}

TYPE_DESCRIPTIONS = {
    "fact": "事实查询：询问具体的事实、数值、参数设置或实验结果（例如'XX方法使用了什么损失函数？'）",
    "concept": "概念解释：要求解释一个概念、方法或术语的含义（例如'什么是对比学习？'）",
    "method_compare": "方法对比：要求比较两种或多种方法/策略的异同（例如'XX和YY的特征提取有什么不同？'）",
    "data_detail": "数据细节：询问实验数据、数据集组成或评估指标的具体细节（例如'实验使用了哪些数据集？'）",
    "cross_paper": "跨论文对比：需要综合多篇论文的信息来回答（例如'论文A的方法与论文B的方法在聚类性能上有什么差异？'）",
}


def load_paper_parents(db) -> list[dict[str, Any]]:
    """Load all parent chunks for the 6 multi-view papers."""
    all_parents: list[dict[str, Any]] = []
    for paper_id in PAPER_IDS:
        # Get paper metadata
        paper = db.execute(
            text("SELECT id, title FROM knowledge_item WHERE id = :id"),
            {"id": paper_id},
        ).fetchone()
        if paper is None:
            print(f"  [!] Paper {paper_id} not found, skipping")
            continue

        # Get parent chunks with children
        parent_rows = db.execute(
            text("""
                SELECT
                    kc.id AS parent_id,
                    kc.chunk_text,
                    ki.title AS item_title,
                    COUNT(child.id) AS child_count
                FROM knowledge_chunk kc
                JOIN knowledge_item ki ON ki.id = kc.item_id
                JOIN knowledge_chunk child ON child.parent_id = kc.id
                WHERE kc.item_id = :item_id AND kc.chunk_type = 'parent'
                GROUP BY kc.id, kc.chunk_text, ki.title
                HAVING child_count > 0
            """),
            {"item_id": paper_id},
        ).fetchall()

        for row in parent_rows:
            children = (
                db.query(KnowledgeChunk)
                .filter(
                    KnowledgeChunk.parent_id == row.parent_id,
                    KnowledgeChunk.chunk_type == "child",
                )
                .order_by(KnowledgeChunk.chunk_index.asc(), KnowledgeChunk.id.asc())
                .all()
            )
            all_parents.append({
                "parent_id": row.parent_id,
                "chunk_text": row.chunk_text,
                "item_id": paper_id,
                "item_title": paper.title,
                "child_count": row.child_count,
                "child_ids": [c.id for c in children],
                "child_texts": [c.chunk_text for c in children],
            })

    return all_parents
```

- [ ] **Step 4: Run tests — only `test_load_paper_parents` should pass**

```bash
cd engine && python -m pytest tests/test_generate_queries_v2.py::test_load_paper_parents_returns_six_papers -v
```

Expected: PASS

- [ ] **Step 5: Implement question generation and gold labeling**

Add to `generate_queries_v2.py`:

```python
def generate_question(
    chunk_text: str,
    paper_title: str,
    question_type: str,
    index: int,
) -> tuple[str, str]:
    """Generate a single Chinese question from a chunk."""
    description = TYPE_DESCRIPTIONS.get(question_type, TYPE_DESCRIPTIONS["fact"])

    prompt = f"""你是一个检索质量评估数据生成器。给定一段学术论文内容，请生成一个能用该文档回答的问题。

要求：
- 生成一个自然的中文提问
- {description}
- 问题答案必须能在这段文档中找到
- 问题长度适中（10-50字）
- 只输出问题本身，不要解释，不要添加前缀

论文：{paper_title}
文档内容：
{chunk_text[:3000]}

问题："""

    try:
        response = chat([{"role": "user", "content": prompt}])
        question = response.strip().strip('"').strip("'").strip("：").strip(":").strip("?").strip("？")
        for prefix in ["问题：", "问题:", "Question:", "question:"]:
            if question.startswith(prefix):
                question = question[len(prefix):].strip()
        return question, "zh"
    except Exception as exc:
        print(f"  [!] LLM call failed index={index}: {exc}", flush=True)
        return "", "zh"


def label_gold_chunks(
    question: str,
    parent_text: str,
    children: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Use LLM to label child chunks by relevance to the question."""
    enumerated = "\n".join(
        f"[{i}] chunk_id={c['chunk_id']}\n    text: {c['chunk_text'][:300]}"
        for i, c in enumerate(children)
    )

    prompt = f"""你是一个检索评估标注器。给定一个问题和一组候选文本片段，请标注每个片段对问题的相关性。

问题：{question}

父块内容（上下文）：
{parent_text[:2000]}

候选子块：
{enumerated}

请判断每个子块的相关性等级：
- "direct": 直接包含答案的关键信息
- "partial": 包含部分答案或重要背景
- "context": 只提供上下文，不直接回答问题

输出 JSON 数组，格式：
[{{"chunk_id": "xxx", "relevance": "direct"}}, ...]

只输出 JSON，不要解释。"""

    try:
        response = chat([{"role": "user", "content": prompt}])
        # Extract JSON from response
        json_start = response.find("[")
        json_end = response.rfind("]") + 1
        if json_start >= 0 and json_end > json_start:
            labels = json.loads(response[json_start:json_end])
            valid = [l for l in labels if isinstance(l, dict) and "chunk_id" in l]
            return [{"chunk_id": l["chunk_id"], "relevance": l.get("relevance", "context")}
                    for l in valid]
        return [{"chunk_id": c["chunk_id"], "relevance": "context"} for c in children]
    except Exception as exc:
        print(f"  [!] Labeling failed: {exc}", flush=True)
        return [{"chunk_id": c["chunk_id"], "relevance": "context"} for c in children]
```

- [ ] **Step 6: Run tests — question generation and labeling should pass**

```bash
cd engine && python -m pytest tests/test_generate_queries_v2.py -v
```

Expected: All tests PASS

Note: `test_generate_question_returns_chinese` and `test_label_gold_chunks_identifies_direct_chunks` will make real LLM calls.

- [ ] **Step 7: Implement `build_dataset` and `main`**

Add to `generate_queries_v2.py`:

```python
def _assign_types(parents: list[dict], paper_ids: list[str]) -> list[dict]:
    """Assign question types to parents according to the distribution.
    
    Returns parents decorated with an 'assigned_type' key.
    """
    type_pool = []
    for qtype, count in QUESTION_TYPES.items():
        type_pool.extend([qtype] * count)

    random.shuffle(type_pool)

    # Separate single-paper and cross-paper allocations
    single_types = [t for t in type_pool if t != "cross_paper"]
    cross_types = [t for t in type_pool if t == "cross_paper"]

    # Assign single-paper types round-robin across papers
    decorated: list[dict] = []
    paper_parents: dict[str, list[dict]] = {}
    for pid in paper_ids:
        paper_parents[pid] = [p for p in parents if p["item_id"] == pid]

    # Assign non-cross-paper types
    type_idx = 0
    for pid in paper_ids:
        paper_ps = paper_parents[pid]
        sample_count = min(SAMPLE_SIZE_PER_PAPER - 1, len(paper_ps))  # -1 for potential cross-paper
        sampled = random.sample(paper_ps, sample_count)
        for p in sampled:
            if type_idx < len(single_types):
                decorated.append({**p, "assigned_type": single_types[type_idx]})
                type_idx += 1

    # Create cross-paper entries
    for ct in cross_types:
        # Pick 2-3 different papers
        cross_papers = random.sample(paper_ids, min(3, len(paper_ids)))
        cross_parents = []
        for pid in cross_papers:
            available = [p for p in paper_parents[pid] if p not in decorated]
            if available:
                cross_parents.append(random.choice(available))
            else:
                cross_parents.append(random.choice(paper_parents[pid]))

        # Merge into one cross-paper entry
        merged = {
            "parent_id": cross_parents[0]["parent_id"],
            "chunk_text": cross_parents[0]["chunk_text"],
            "item_id": cross_parents[0]["item_id"],
            "item_title": cross_parents[0]["item_title"],
            "child_count": sum(p["child_count"] for p in cross_parents),
            "child_ids": [cid for p in cross_parents for cid in p["child_ids"]],
            "child_texts": [ct for p in cross_parents for ct in p["child_texts"]],
            "assigned_type": "cross_paper",
            "cross_paper_ids": [p["item_id"] for p in cross_parents],
            "cross_paper_titles": [p["item_title"] for p in cross_parents],
            "cross_parent_ids": [p["parent_id"] for p in cross_parents],
            "cross_parent_texts": [p["chunk_text"][:500] for p in cross_parents],
        }
        decorated.append(merged)

    return decorated


def build_dataset(
    parents: list[dict],
    paper_ids: list[str],
    output_path: Path,
) -> dict[str, Any]:
    """Generate questions and gold labels for all parents."""
    decorated = _assign_types(parents, paper_ids)
    queries: list[dict] = []
    type_counts: dict[str, int] = {}
    failed = 0

    for index, parent in enumerate(decorated):
        qtype = parent["assigned_type"]
        cross_ids = parent.get("cross_paper_ids", [parent["item_id"]])

        question, lang = generate_question(
            parent["chunk_text"],
            parent.get("cross_paper_titles", [parent["item_title"]])[0]
            if qtype == "cross_paper" else parent["item_title"],
            qtype,
            index,
        )
        if not question:
            failed += 1
            continue

        # Label gold chunks
        children = [
            {"chunk_id": cid, "chunk_text": ct}
            for cid, ct in zip(parent["child_ids"], parent["child_texts"])
        ]
        labels = label_gold_chunks(question, parent["chunk_text"], children)

        queries.append({
            "id": f"q{len(queries) + 1:03d}",
            "question": question,
            "language": lang,
            "question_type": qtype,
            "scope": "cross_paper" if qtype == "cross_paper" else "single_paper",
            "paper_ids": cross_ids,
            "paper_titles": parent.get("cross_paper_titles", [parent["item_title"]]),
            "parent_chunk_id": parent["parent_id"],
            "parent_chunk_text": parent["chunk_text"][:500] + ("..." if len(parent["chunk_text"]) > 500 else ""),
            "relevant_children": [
                {"chunk_id": l["chunk_id"], "chunk_text": l.get("chunk_text", ""), "relevance": l["relevance"]}
                for l in labels
            ],
            "item_title": parent["item_title"],
        })
        type_counts[qtype] = type_counts.get(qtype, 0) + 1
        print(f"  [{index + 1}/{len(decorated)}] {qtype} | {question[:80]}...", flush=True)

    return {
        "meta": {
            "version": "2.0",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "total_questions": len(queries),
            "question_type_distribution": type_counts,
            "failed_count": failed,
            "sampling_strategy": "stratified_multi_view_papers",
            "papers": [
                {
                    "id": pid,
                    "title": next((p["item_title"] for p in parents if p["item_id"] == pid), "?"),
                    "parent_count": sum(1 for p in parents if p["item_id"] == pid),
                    "child_count": sum(p["child_count"] for p in parents if p["item_id"] == pid),
                }
                for pid in paper_ids
            ],
            "llm_model": settings.LLM_MODEL,
            "embedding_model": settings.EMBEDDING_MODEL,
            "output_path": str(output_path),
        },
        "queries": queries,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate v2 golden dataset from multi-view papers")
    parser.add_argument("--output", type=str, default=None, help="Output path (default: results/<ts>/golden_dataset_v2.json)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    args = parser.parse_args(argv)

    random.seed(args.seed)
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
    run_dir = OUTPUT_DIR / run_ts
    run_dir.mkdir(parents=True, exist_ok=True)
    output_path = Path(args.output) if args.output else (run_dir / "golden_dataset_v2.json")

    print("=" * 60, flush=True)
    print("Prism v2 Golden Dataset Generation (Multi-View Papers)", flush=True)
    print("=" * 60, flush=True)
    print(f"Papers: {len(PAPER_IDS)}", flush=True)
    print(f"Output: {output_path}", flush=True)

    db = _Session()
    try:
        print("\n[1/3] Loading parent chunks...", flush=True)
        parents = load_paper_parents(db)
        print(f"  Loaded {len(parents)} parent chunks across {len(set(p['item_id'] for p in parents))} papers", flush=True)

        print(f"\n[2/3] Generating questions with {settings.LLM_MODEL}...", flush=True)
        dataset = build_dataset(parents, PAPER_IDS, output_path)

        print(f"\n[3/3] Writing dataset...", flush=True)
        output_path.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")

        meta = dataset["meta"]
        print(f"\n[OK] Generated {meta['total_questions']} questions", flush=True)
        print(f"  Distribution: {meta['question_type_distribution']}", flush=True)
        print(f"  Failed: {meta['failed_count']}", flush=True)
    finally:
        db.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 8: Run full test suite**

```bash
cd engine && python -m pytest tests/test_generate_queries_v2.py -v
```

Expected: All tests PASS

- [ ] **Step 9: Commit**

```bash
git add engine/eval/generate_queries_v2.py engine/tests/test_generate_queries_v2.py
git commit -m "feat(eval): add v2 dataset generator for multi-view papers

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Retrieval Evaluation Script

**Files:**
- Create: `engine/eval/run_retrieval_v2.py`
- Test: `engine/tests/test_run_retrieval_v2.py`

**Interfaces:**
- Consumes: `engine/eval/results/<ts>/golden_dataset_v2.json` — the dataset from Task 1
- Consumes: `engine/app/retrieval/unified.py::scoped_text_hybrid_search` — existing retrieval function
- Produces: `retrieval_detailed.csv` + `retrieval_summary.json` in the same timestamp directory
- Produces: `compute_retrieval_metrics(retrieved_ids, relevant_ids, ks)` → `dict` — core metrics computation
- Produces: `aggregate_metrics(results, dimensions)` → `dict` — aggregation by paper/type/channel

This extends the existing `run_retrieval.py` with additional metrics (latency, channel health, token estimation) and grouped aggregation. The existing v1 dataset format (`relevant_children`) is the shared field.

- [ ] **Step 1: Write failing test for metrics computation**

Create `engine/tests/test_run_retrieval_v2.py`:

```python
import json
from pathlib import Path
import sys

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))


def test_compute_retrieval_metrics_perfect_retrieval():
    """Perfect retrieval should yield recall=1.0, precision=1.0, mrr=1.0."""
    from engine.eval.run_retrieval_v2 import compute_retrieval_metrics

    retrieved = ["c1", "c2", "c3", "c4", "c5"]
    relevant = {"c1", "c3"}
    metrics = compute_retrieval_metrics(retrieved, relevant, ks=(5, 10))

    assert metrics["recall@5"] == 1.0
    assert metrics["recall@10"] == 1.0
    assert metrics["precision@5"] == 2 / 5
    assert metrics["mrr"] == 1.0  # c1 is at rank 1
    assert metrics["first_relevant_rank"] == 1
    assert metrics["hit@5"] == 1


def test_compute_retrieval_metrics_empty_gold():
    """Empty gold set should yield all zeros."""
    from engine.eval.run_retrieval_v2 import compute_retrieval_metrics

    retrieved = ["c1", "c2", "c3"]
    relevant = set()
    metrics = compute_retrieval_metrics(retrieved, relevant, ks=(5,))

    assert metrics["recall@5"] == 0.0
    assert metrics["precision@5"] == 0.0
    assert metrics["mrr"] == 0.0
    assert metrics["first_relevant_rank"] is None


def test_compute_retrieval_metrics_no_hit():
    """No relevant chunks retrieved should yield recall=0, mrr=0."""
    from engine.eval.run_retrieval_v2 import compute_retrieval_metrics

    retrieved = ["c1", "c2", "c3"]
    relevant = {"c4", "c5"}
    metrics = compute_retrieval_metrics(retrieved, relevant, ks=(5,))

    assert metrics["recall@5"] == 0.0
    assert metrics["precision@5"] == 0.0
    assert metrics["mrr"] == 0.0
    assert metrics["first_relevant_rank"] is None


def test_aggregate_metrics_by_dimension():
    """Aggregation should compute mean/median/std/min/max per metric per group."""
    from engine.eval.run_retrieval_v2 import aggregate_by_dimension

    results = [
        {"query_id": "q1", "question_type": "fact", "paper_title": "Paper A",
         "recall@10": 0.8, "mrr": 1.0},
        {"query_id": "q2", "question_type": "fact", "paper_title": "Paper A",
         "recall@10": 0.6, "mrr": 0.5},
        {"query_id": "q3", "question_type": "concept", "paper_title": "Paper B",
         "recall@10": 0.4, "mrr": 0.3},
    ]

    by_type = aggregate_by_dimension(results, "question_type", ["recall@10", "mrr"])
    assert "fact" in by_type
    assert "concept" in by_type
    assert by_type["fact"]["recall@10"]["mean"] == 0.7
    assert by_type["fact"]["count"] == 2
```

- [ ] **Step 2: Run tests and verify failure**

```bash
cd engine && python -m pytest tests/test_run_retrieval_v2.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'engine.eval.run_retrieval_v2'`

- [ ] **Step 3: Implement core metrics and aggregation functions**

Create `engine/eval/run_retrieval_v2.py`:

```python
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
from engine.app.config import settings

K_VALUES = (5, 10, 20)
RESULTS_DIR = Path(__file__).resolve().parent / "results"
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
            median = sorted_vals[n // 2]
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
        median = sorted_vals[n // 2]
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
```

- [ ] **Step 4: Run tests — metrics and aggregation should pass**

```bash
cd engine && python -m pytest tests/test_run_retrieval_v2.py -v
```

Expected: 4/4 tests PASS

- [ ] **Step 5: Implement `main` function**

Add to `run_retrieval_v2.py`:

```python
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
        retrieved_items = [
            {"rank": j + 1, "chunk_id": h["chunk_id"], "score": h["score"],
             "relevant": h["chunk_id"] in relevant_ids}
            for j, h in enumerate(hits)
        ]

        metrics = compute_retrieval_metrics(retrieved_ids, relevant_ids)
        channels = _estimate_channel_hits(hits)
        metrics["latency_ms"] = latency_ms
        metrics.update({f"{ch}_hits": count for ch, count in channels.items()})

        result = {
            "query_id": qid,
            "question": question,
            "question_type": q.get("question_type", "?"),
            "paper_title": q.get("paper_titles", [q.get("item_title", "?")])[0],
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
```

- [ ] **Step 6: Run tests — all should pass**

```bash
cd engine && python -m pytest tests/test_run_retrieval_v2.py -v
```

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add engine/eval/run_retrieval_v2.py engine/tests/test_run_retrieval_v2.py
git commit -m "feat(eval): add retrieval v2 evaluation with latency and grouping

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Answer Evaluation Script (LLM-as-Judge)

**Files:**
- Create: `engine/eval/run_answer_eval.py`
- Test: `engine/tests/test_run_answer_eval.py`

**Interfaces:**
- Consumes: `engine/eval/results/<ts>/golden_dataset_v2.json` — input dataset
- Consumes: Engine `/chat/answer` HTTP endpoint (localhost:5180) — real chat pipeline
- Consumes: `engine/app/llm/client.py::chat` — for LLM judge calls
- Consumes: `backend/app/security/knowledge_scope.py::sign_scope` — to sign knowledge scope
- Produces: `answer_detailed.csv`, `answer_summary.json`, `answer_low_scores.csv`, `bad_cases/` directory
- Produces: `build_judge_prompt(question, gold_chunks_text, answer)` → `str`
- Produces: `parse_judge_response(response_text)` → `dict`
- Produces: `parse_ndjson_stream(response)` → `dict` with answer, sources, tokens

- [ ] **Step 1: Write failing tests**

Create `engine/tests/test_run_answer_eval.py`:

```python
from pathlib import Path
import sys

import pytest

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))


def test_build_judge_prompt_includes_all_sections():
    """Judge prompt should include question, gold chunks, answer, and scoring criteria."""
    from engine.eval.run_answer_eval import build_judge_prompt

    question = "什么是多视图聚类？"
    gold_text = "多视图聚类是一种将多个视图的数据进行联合聚类的方法。"
    answer = "多视图聚类是将不同视图的数据进行联合聚类的方法。"

    prompt = build_judge_prompt(question, gold_text, answer)
    assert question in prompt
    assert gold_text in prompt
    assert answer in prompt
    assert "忠实度" in prompt
    assert "相关性" in prompt
    assert "完整性" in prompt
    assert "faithfulness" in prompt  # JSON key
    assert "relevance" in prompt
    assert "completeness" in prompt


def test_parse_judge_response_valid_json():
    """Valid JSON response should be parsed correctly."""
    from engine.eval.run_answer_eval import parse_judge_response

    response = '{"faithfulness": 5, "relevance": 4, "completeness": 3, "rationale": "回答基本准确"}'
    scores = parse_judge_response(response)
    assert scores["faithfulness"] == 5
    assert scores["relevance"] == 4
    assert scores["completeness"] == 3
    assert scores["overall"] == pytest.approx((5 * 0.4 + 4 * 0.3 + 3 * 0.3), rel=1e-2)
    assert "rationale" in scores


def test_parse_judge_response_malformed():
    """Malformed JSON should return error sentinel."""
    from engine.eval.run_answer_eval import parse_judge_response

    response = "这不是 JSON"
    scores = parse_judge_response(response)
    assert scores["faithfulness"] == -1  # error sentinel
    assert scores["relevance"] == -1


def test_parse_ndjson_events_sample():
    """Should parse NDJSON lines into structured events."""
    from engine.eval.run_answer_eval import parse_ndjson_events

    lines = [
        '{"type":"agent_status","data":{"status":"analyzing"}}\n',
        '{"type":"token","data":{"token":"你好"}}\n',
        '{"type":"token","data":{"token":"世界"}}\n',
        '{"type":"sources","data":{"sources":[{"chunk_uid":"c1","excerpt":"text"}]}}\n',
        '{"type":"done","data":{"answer":"你好世界"}}\n',
    ]

    events = parse_ndjson_events(lines)
    assert events["answer"] == "你好世界"
    assert len(events["sources"]) == 1
    assert events["sources"][0]["chunk_uid"] == "c1"
    assert events["token_count"] >= 2
```

- [ ] **Step 2: Run tests and verify failure**

```bash
cd engine && python -m pytest tests/test_run_answer_eval.py -v
```

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement judge prompt, parsing, and NDJSON parsing**

Create `engine/eval/run_answer_eval.py`:

```python
# prism/engine/eval/run_answer_eval.py
"""Step 3: End-to-end answer evaluation with LLM-as-Judge.

Usage:
    python -m engine.eval.run_answer_eval --dataset results/<ts>/golden_dataset_v2.json
"""
import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from dotenv import load_dotenv
load_dotenv(_project_root / ".env")

from engine.app.config import settings
from engine.app.llm.client import chat
from backend.app.security.knowledge_scope import AuthorizedKnowledgeScope, sign_scope

ENGINE_URL = f"http://localhost:{settings.ENGINE_PORT}"
SCOPE_TTL_SECONDS = 600
RESULTS_DIR = Path(__file__).resolve().parent / "results"
JUDGE_FAITHFULNESS_WEIGHT = 0.4
JUDGE_RELEVANCE_WEIGHT = 0.3
JUDGE_COMPLETENESS_WEIGHT = 0.3


def build_judge_prompt(question: str, gold_chunks_text: str, answer: str) -> str:
    """Build the LLM-as-Judge evaluation prompt."""
    return f"""你是一个 RAG 问答质量评估器。请严格评估以下回答的质量。

## 问题
{question}

## 参考答案依据（来自知识库的相关片段）
{gold_chunks_text[:3000]}

## 模型回答
{answer[:3000]}

## 评估维度（1-5 分，整数）

1. **忠实度 (faithfulness)**：回答是否严格基于提供的知识库内容？
   - 5=完全基于知识库，无任何编造
   - 4=基本基于知识库，极少量合理推断
   - 3=基本基于知识库，有少量不准确或过度推断
   - 2=大量内容无法从知识库验证
   - 1=大量编造、幻觉，或与知识库矛盾

2. **相关性 (relevance)**：回答是否直接、精确地回应了问题？
   - 5=完全切题，直接回应
   - 4=基本切题，少量偏离
   - 3=部分相关，有偏题但大致方向对
   - 2=大部分内容与问题无关
   - 1=答非所问

3. **完整性 (completeness)**：回答是否覆盖了知识库中含有的关键要点？
   - 5=覆盖全部关键要点
   - 4=覆盖大部分要点，遗漏少量次要信息
   - 3=覆盖主要内容，遗漏部分相关信息
   - 2=遗漏大量关键信息
   - 1=几乎没有覆盖知识库要点

## 输出格式
只输出 JSON，不要解释：
{{"faithfulness": <1-5>, "relevance": <1-5>, "completeness": <1-5>, "rationale": "<一句话理由>"}}"""


def parse_judge_response(response_text: str) -> dict[str, Any]:
    """Parse the LLM judge's JSON response. Returns error sentinel (-1) on failure."""
    try:
        json_start = response_text.find("{")
        json_end = response_text.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            data = json.loads(response_text[json_start:json_end])
            faithfulness = int(data.get("faithfulness", -1))
            relevance = int(data.get("relevance", -1))
            completeness = int(data.get("completeness", -1))

            # Clamp to 1-5
            faithfulness = max(1, min(5, faithfulness))
            relevance = max(1, min(5, relevance))
            completeness = max(1, min(5, completeness))

            overall = round(
                faithfulness * JUDGE_FAITHFULNESS_WEIGHT
                + relevance * JUDGE_RELEVANCE_WEIGHT
                + completeness * JUDGE_COMPLETENESS_WEIGHT,
                2,
            )
            return {
                "faithfulness": faithfulness,
                "relevance": relevance,
                "completeness": completeness,
                "overall": overall,
                "rationale": data.get("rationale", ""),
            }
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        print(f"  [!] Judge parse error: {e}", flush=True)

    return {
        "faithfulness": -1,
        "relevance": -1,
        "completeness": -1,
        "overall": -1,
        "rationale": "PARSE_ERROR",
    }


def parse_ndjson_events(lines: list[str]) -> dict[str, Any]:
    """Parse NDJSON chat stream events into structured data."""
    result: dict[str, Any] = {
        "answer": "",
        "sources": [],
        "token_events": 0,
        "tool_calls": 0,
        "status": "unknown",
    }

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        etype = event.get("type", "")
        data = event.get("data", {})

        if etype == "token":
            result["token_events"] += 1
            token_text = data.get("token", "")
            if isinstance(token_text, str):
                result["answer"] += token_text
        elif etype == "sources":
            sources = data.get("sources", [])
            if isinstance(sources, list):
                result["sources"] = sources
        elif etype == "tool_call":
            result["tool_calls"] += 1
        elif etype == "done":
            result["status"] = "done"
            if data.get("answer"):
                result["answer"] = data["answer"]
        elif etype == "error":
            result["status"] = "error"
            result["error"] = data.get("message", "unknown error")

    return result


def _gold_chunks_for_question(q: dict, db=None) -> str:
    """Build the gold chunk text block for the judge prompt.
    
    Uses the chunk_text from relevant_children directly (already populated
    during dataset generation). Falls back to DB load if texts are missing.
    """
    texts: list[str] = []
    for c in q.get("relevant_children", []):
        relevance = c.get("relevance", "context")
        chunk_text = c.get("chunk_text", "")
        if chunk_text:
            prefix = {"direct": "[★关键]", "partial": "[相关]", "context": "[背景]"}.get(relevance, "")
            texts.append(f"{prefix} {chunk_text[:500]}")

    if not texts:
        return "(无参考依据)"

    return "\n\n---\n".join(texts)


def _sign_scope(tenant_id: str, kb_uid: str) -> str:
    """Sign a knowledge scope token for Engine authorization."""
    scope = AuthorizedKnowledgeScope(
        tenant_id=tenant_id,
        allowed_kb_uids=(kb_uid,),
        run_id=f"eval-{datetime.now(timezone.utc).timestamp()}",
    )
    return sign_scope(scope, settings.KNOWLEDGE_SCOPE_SECRET, SCOPE_TTL_SECONDS)


def _aggregate_judge_scores(results: list[dict]) -> dict[str, Any]:
    """Compute aggregate judge score statistics."""
    dims = ["faithfulness", "relevance", "completeness", "overall"]
    valid = [r for r in results if r.get("judge_faithfulness", -1) >= 0]

    agg: dict[str, Any] = {"evaluated": len(valid), "total": len(results)}
    for dim in dims:
        key = f"judge_{dim}"
        values = [r[key] for r in valid if key in r and r[key] is not None]
        if not values:
            continue
        n = len(values)
        mean = sum(values) / n
        sorted_vals = sorted(values)
        agg[dim] = {
            "mean": round(mean, 2),
            "median": sorted_vals[n // 2],
            "min": min(values),
            "max": max(values),
            "dist": {str(i): values.count(i) for i in range(1, 6)},
        }

    return agg
```

- [ ] **Step 4: Run tests — core functions should pass**

```bash
cd engine && python -m pytest tests/test_run_answer_eval.py -v
```

Expected: Tests for `build_judge_prompt`, `parse_judge_response`, `parse_ndjson_events` PASS

- [ ] **Step 5: Implement `main` function**

Add to `run_answer_eval.py`:

```python
def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Prism End-to-End Answer Evaluation")
    parser.add_argument("--dataset", required=True, help="Path to golden_dataset_v2.json")
    parser.add_argument("--tenant-id", default="default-tenant")
    parser.add_argument("--kb-uid", required=True)
    parser.add_argument("--engine-url", default=ENGINE_URL, help="Engine URL")
    parser.add_argument("--judge-model", default=None, help="LLM model for judging (default: same as LLM_MODEL)")
    parser.add_argument("--skip-llm-judge", action="store_true", help="Skip LLM judging (collect answers only)")
    parser.add_argument("--dry-run", action="store_true", help="Test first 3 queries only")
    args = parser.parse_args(argv)

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        print(f"[!] Dataset not found: {dataset_path}")
        sys.exit(1)

    run_dir = dataset_path.parent
    print("=" * 60)
    print("Prism End-to-End Answer Evaluation")
    print("=" * 60)
    print(f"Dataset: {dataset_path}")
    print(f"Engine: {args.engine_url}")
    print(f"Judge model: {args.judge_model or settings.LLM_MODEL}")
    print(f"Dry run: {args.dry_run}")

    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    queries = dataset["queries"]
    if args.dry_run:
        queries = queries[:3]

    # Get KB info (index_generation, graph_generation) for scope
    from sqlalchemy import create_engine as _ce, text
    from sqlalchemy.orm import sessionmaker as _sm

    db_engine = _ce(settings.DATABASE_URL, pool_pre_ping=True)
    db = _sm(bind=db_engine)()
    topic = db.execute(
        text("SELECT active_index_generation, active_graph_generation FROM knowledge_topic WHERE kb_uid = :kb"),
        {"kb": args.kb_uid},
    ).fetchone()
    db.close()

    if topic is None:
        print(f"[!] KB not found: {args.kb_uid}")
        sys.exit(1)

    # Sign scope
    scope_token = _sign_scope(args.tenant_id, args.kb_uid)

    print(f"\n[1/3] Running answer evaluation ({len(queries)} queries)...")
    results: list[dict] = []
    failures: list[dict] = []
    client = httpx.Client(timeout=120.0)

    for i, q in enumerate(queries):
        qid = q["id"]
        question = q["question"]
        print(f"  [{i + 1}/{len(queries)}] {qid} | {question[:60]}...", flush=True)

        try:
            t0 = time.perf_counter()
            response = client.stream(
                "POST",
                f"{args.engine_url}/chat/answer",
                json={
                    "query": question,
                    "history": [],
                    "deep_search_enabled": q.get("question_type") == "cross_paper",
                    "deep_search_depth": "standard",
                    "rag_max_iterations": 5,
                },
                headers={"x-prism-knowledge-scope": scope_token},
            )
            ttfb_ms = round((time.perf_counter() - t0) * 1000)

            lines = []
            first_line = True
            for line in response.iter_lines():
                if first_line:
                    ttfb_ms = round((time.perf_counter() - t0) * 1000)
                    first_line = False
                lines.append(line + "\n")

            total_latency_ms = round((time.perf_counter() - t0) * 1000)
            events = parse_ndjson_events(lines)

        except Exception as e:
            print(f"    [!] HTTP error: {e}", flush=True)
            failures.append({"query_id": qid, "question": question, "error": str(e)})
            continue

        # LLM Judge
        judge_scores: dict[str, Any] = {}
        if not args.skip_llm_judge and events["answer"]:
            try:
                gold_text = _gold_chunks_for_question(q)
                prompt = build_judge_prompt(question, gold_text, events["answer"])
                judge_response = chat(
                    [{"role": "user", "content": prompt}],
                    model=args.judge_model,
                )
                judge_scores = parse_judge_response(judge_response)
            except Exception as e:
                print(f"    [!] Judge error: {e}", flush=True)
                judge_scores = {"faithfulness": -1, "relevance": -1, "completeness": -1,
                               "overall": -1, "rationale": str(e)}

        result = {
            "query_id": qid,
            "question": question,
            "question_type": q.get("question_type", "?"),
            "paper_title": q.get("paper_titles", [q.get("item_title", "?")])[0],
            "answer": events.get("answer", "")[:2000],
            "source_count": len(events.get("sources", [])),
            "source_chunk_uids": ",".join(s.get("chunk_uid", "") for s in events.get("sources", [])),
            "ttfb_ms": ttfb_ms,
            "total_latency_ms": total_latency_ms,
            "tool_calls": events.get("tool_calls", 0),
            "status": events.get("status", "unknown"),
            "judge_faithfulness": judge_scores.get("faithfulness", -1),
            "judge_relevance": judge_scores.get("relevance", -1),
            "judge_completeness": judge_scores.get("completeness", -1),
            "judge_overall": judge_scores.get("overall", -1),
            "judge_rationale": judge_scores.get("rationale", ""),
        }
        results.append(result)

        score_str = f"F={judge_scores.get('faithfulness','?')} R={judge_scores.get('relevance','?')} C={judge_scores.get('completeness','?')}"
        print(f"    {score_str} | TTFB={ttfb_ms}ms Total={total_latency_ms}ms", flush=True)

    client.close()

    # Write outputs
    print(f"\n[2/3] Writing results...")

    # answer_detailed.csv
    csv_path = run_dir / "answer_detailed.csv"
    csv_fields = [
        "query_id", "question", "question_type", "paper_title",
        "answer", "source_count", "source_chunk_uids",
        "ttfb_ms", "total_latency_ms", "tool_calls", "status",
        "judge_faithfulness", "judge_relevance", "judge_completeness",
        "judge_overall", "judge_rationale",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)
    print(f"  CSV: {csv_path}")

    # answer_summary.json
    summary = {
        "meta": {
            "dataset": str(dataset_path),
            "run_at": datetime.now(timezone.utc).isoformat(),
            "total_queries": len(queries),
            "evaluated": len(results),
            "failed": len(failures),
            "judge_model": args.judge_model or settings.LLM_MODEL,
        },
        "judge_aggregates": _aggregate_judge_scores(results),
        "by_type": {},
        "by_paper": {},
        "latency": {
            "ttfb_p50": None, "ttfb_p95": None,
            "total_p50": None, "total_p95": None,
        },
        "failures": failures,
    }

    # Per-type aggregates
    type_groups: dict[str, list] = {}
    for r in results:
        type_groups.setdefault(r.get("question_type", "?"), []).append(r["judge_overall"])
    for t, scores in type_groups.items():
        valid = [s for s in scores if s is not None and s >= 0]
        if valid:
            summary["by_type"][t] = {"mean": round(sum(valid) / len(valid), 2), "count": len(valid)}

    # Per-paper aggregates
    paper_groups: dict[str, list] = {}
    for r in results:
        paper_groups.setdefault(r.get("paper_title", "?"), []).append(r["judge_overall"])
    for p, scores in paper_groups.items():
        valid = [s for s in scores if s is not None and s >= 0]
        if valid:
            summary["by_paper"][p] = {"mean": round(sum(valid) / len(valid), 2), "count": len(valid)}

    # Latency
    ttfb_vals = sorted([r["ttfb_ms"] for r in results if r.get("ttfb_ms")])
    total_vals = sorted([r["total_latency_ms"] for r in results if r.get("total_latency_ms")])
    if ttfb_vals:
        summary["latency"]["ttfb_p50"] = ttfb_vals[len(ttfb_vals) // 2]
        summary["latency"]["ttfb_p95"] = ttfb_vals[int(len(ttfb_vals) * 0.95)]
    if total_vals:
        summary["latency"]["total_p50"] = total_vals[len(total_vals) // 2]
        summary["latency"]["total_p95"] = total_vals[int(len(total_vals) * 0.95)]

    summary_path = run_dir / "answer_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  JSON: {summary_path}")

    # Low scores
    print(f"\n[3/3] Flagging bad cases...")
    bad_cases_dir = run_dir / "bad_cases"
    bad_cases_dir.mkdir(exist_ok=True)

    low_scores = []
    for r in results:
        faith = r.get("judge_faithfulness", -1)
        rel = r.get("judge_relevance", -1)
        if (faith >= 0 and faith < 3) or (rel >= 0 and rel < 3):
            low_scores.append(r)
            # Write bad case markdown
            case_md = f"""# Bad Case: {r['query_id']}

**Question:** {r['question']}
**Paper:** {r['paper_title']}
**Type:** {r.get('question_type', '?')}

## Answer
{r.get('answer', 'N/A')[:2000]}

## Judge Scores
- Faithfulness: {r.get('judge_faithfulness', '?')}
- Relevance: {r.get('judge_relevance', '?')}
- Completeness: {r.get('judge_completeness', '?')}
- Overall: {r.get('judge_overall', '?')}
- Rationale: {r.get('judge_rationale', '')}

## Sources Cited
{r.get('source_chunk_uids', 'None')}

## Metadata
- TTFB: {r.get('ttfb_ms', '?')}ms
- Total latency: {r.get('total_latency_ms', '?')}ms
- Tool calls: {r.get('tool_calls', '?')}
"""
            (bad_cases_dir / f"{r['query_id']}_bad_case.md").write_text(case_md, encoding="utf-8")

    if low_scores:
        low_csv_path = run_dir / "answer_low_scores.csv"
        with open(low_csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(low_scores)
        print(f"  Low scores: {len(low_scores)} queries flagged, see {low_csv_path}")
    else:
        print(f"  No low-score queries found.")

    # Terminal summary
    ja = summary["judge_aggregates"]
    print(f"\n{'=' * 60}")
    print("Answer Evaluation Summary")
    print(f"{'=' * 60}")
    print(f"Evaluated: {len(results)}/{len(queries)} (failed: {len(failures)})")
    for dim in ["faithfulness", "relevance", "completeness", "overall"]:
        if dim in ja:
            d = ja[dim]
            print(f"Judge {dim}: mean={d['mean']:.1f} median={d['median']} range=[{d['min']},{d['max']}]")
    print(f"Low scores flagged: {len(low_scores)}")
    print(f"Bad cases: {bad_cases_dir}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run tests — all core tests should pass**

```bash
cd engine && python -m pytest tests/test_run_answer_eval.py -v
```

Expected: PASS (4/4)

- [ ] **Step 7: Commit**

```bash
git add engine/eval/run_answer_eval.py engine/tests/test_run_answer_eval.py
git commit -m "feat(eval): add end-to-end answer evaluation with LLM judge

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Report Generation Script

**Files:**
- Create: `engine/eval/generate_report.py`
- Test: `engine/tests/test_generate_report.py`

**Interfaces:**
- Consumes: `results/<ts>/golden_dataset_v2.json`, `retrieval_summary.json`, `answer_summary.json`, `answer_detailed.csv`
- Produces: `results/<ts>/REPORT.md`
- Produces: `load_data(run_dir)` → `dict` — loads all input files into a structured dict
- Produces: `render_report(data)` → `str` — renders the complete Markdown report

- [ ] **Step 1: Write failing test**

Create `engine/tests/test_generate_report.py`:

```python
import json
from pathlib import Path
import sys

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))


def test_load_data_reads_all_files(tmp_path):
    """Should load and merge all input JSON/CSV files."""
    from engine.eval.generate_report import load_data

    # Write mock files
    (tmp_path / "golden_dataset_v2.json").write_text(json.dumps({
        "meta": {"total_questions": 3, "version": "2.0"},
        "queries": [
            {"id": "q1", "question": "Q1?", "question_type": "fact"},
            {"id": "q2", "question": "Q2?", "question_type": "concept"},
        ]
    }), encoding="utf-8")
    (tmp_path / "retrieval_summary.json").write_text(json.dumps({
        "aggregates": {"recall@10": {"mean": 0.72}},
        "zero_recall": ["q2"],
    }), encoding="utf-8")
    (tmp_path / "answer_summary.json").write_text(json.dumps({
        "judge_aggregates": {"overall": {"mean": 4.1}},
        "by_type": {"fact": {"mean": 4.2, "count": 1}},
    }), encoding="utf-8")

    data = load_data(tmp_path)
    assert data["dataset_meta"]["total_questions"] == 3
    assert data["retrieval"]["aggregates"]["recall@10"]["mean"] == 0.72
    assert data["answer"]["judge_aggregates"]["overall"]["mean"] == 4.1
    assert "q2" in data["retrieval"]["zero_recall"]


def test_render_report_includes_all_sections():
    """Rendered report should contain all major sections."""
    from engine.eval.generate_report import render_report

    data = {
        "run_ts": "2026-07-29_1430",
        "dataset_meta": {"total_questions": 3, "version": "2.0", "papers": []},
        "retrieval": {
            "aggregates": {"recall@10": {"mean": 0.72, "median": 0.80}},
            "by_paper": {},
            "by_type": {},
            "zero_recall": [],
            "latency": {"p50": 1200, "p95": 3500},
        },
        "answer": {
            "judge_aggregates": {
                "overall": {"mean": 4.1, "median": 4.0},
                "faithfulness": {"mean": 4.2, "median": 4.0},
                "relevance": {"mean": 4.3, "median": 4.0},
                "completeness": {"mean": 3.9, "median": 4.0},
            },
            "by_type": {},
            "by_paper": {},
            "latency": {"total_p50": 8000, "total_p95": 15000},
        },
        "low_scores_count": 5,
        "answer_detail": [],
    }

    report = render_report(data)

    # Must contain all major sections
    assert "# Prism" in report
    assert "执行摘要" in report
    assert "检索层" in report
    assert "端到端问答" in report
    assert "交叉分析" in report
    assert "改进建议" in report
    assert "recall@10" in report
    assert "0.72" in report  # mean recall
    assert "4.1" in report   # mean overall
```

- [ ] **Step 2: Run tests and verify failure**

```bash
cd engine && python -m pytest tests/test_generate_report.py -v
```

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `generate_report.py`**

Create `engine/eval/generate_report.py`:

```python
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
    """Load all evaluation artifacts from a run directory."""
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
    if not agg:
        return f"| {name} | - | - | - |"
    return f"| {name} | {_fmt_val(agg.get('mean'))} | {_fmt_val(agg.get('median'))} | {_fmt_val(agg.get('std'))} |"


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
    """Render the complete Markdown evaluation report."""
    ds = data.get("dataset_meta", {})
    ret = data.get("retrieval", {})
    ans = data.get("answer", {})
    detail = data.get("answer_detail", [])

    papers = ds.get("papers", [])
    paper_list = "\n".join(f"| {p.get('id','?')[:12]} | {p.get('title','?')[:60]} | {p.get('parent_count','?')} | {p.get('child_count','?')} |" for p in papers)

    ret_agg = ret.get("aggregates", {})
    ans_agg = ans.get("judge_aggregates", {})

    # Build retrieval metrics table
    ret_metrics = [
        "recall@5", "recall@10", "recall@20",
        "precision@5", "precision@10", "precision@20",
        "mrr", "ndcg@10", "ndcg@20",
    ]
    ret_table = "\n".join(_metric_row(m, ret_agg.get(m, {})) for m in ret_metrics)

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

    # Find worst cases
    worst = sorted(
        [r for r in detail if r.get("judge_overall") and float(r.get("judge_overall", 5)) >= 0],
        key=lambda r: float(r.get("judge_overall", 5)),
    )[:5]
    worst_table = "\n".join(
        f"| {r.get('query_id','?')} | {r.get('question','?')[:50]} | {r.get('judge_faithfulness','?')} | {r.get('judge_relevance','?')} | {r.get('judge_completeness','?')} |"
        for r in worst
    )

    report = f"""# Prism 多视图聚类论文 RAG 评测报告

> **评测日期**：{data.get('run_ts', '?')}
> **论文数**：{len(papers)} | **问题数**：{ds.get('total_questions', '?')}
> **LLM**：{ds.get('llm_model', '?')} | **Embedding**：{ds.get('embedding_model', '?')}

---

## 0. 执行摘要

| 层级 | 核心指标 | 均值 |
|------|---------|------|
| 检索层 | Recall@10 | {_fmt_val(ret_recall_10)} |
| 检索层 | MRR | {_fmt_val(ret_agg.get('mrr', {}).get('mean'))} |
| 问答层 | 忠实度 | {_fmt_val(ans_agg.get('faithfulness', {}).get('mean'))} |
| 问答层 | 相关性 | {_fmt_val(ans_agg.get('relevance', {}).get('mean'))} |
| 问答层 | 完整性 | {_fmt_val(ans_agg.get('completeness', {}).get('mean'))} |
| 问答层 | 综合分 | {_fmt_val(ans_overall)} |

- 检索零召回问题数：{len(zero)} ({zero_str})
- 低分回答数（忠实度<3 或 相关性<3）：{low_scores}
- 检索延迟 P50/P95：{_fmt_val(ret_lat.get('p50'))}ms / {_fmt_val(ret_lat.get('p95'))}ms
- 端到端延迟 P50/P95：{_fmt_val(ans_lat.get('total_p50'))}ms / {_fmt_val(ans_lat.get('total_p95'))}ms

---

## 1. 数据概览

### 1.1 论文清单

| ID | 标题 | Parent | Child |
|----|------|--------|-------|
{paper_list}

### 1.2 问题类型分布

{dict(ds.get('question_type_distribution', {{}}))}

---

## 2. 检索层详细结果

### 2.1 整体指标

| 指标 | 均值 | 中位数 | 标准差 |
|------|------|--------|--------|
{ret_table}

### 2.2 检索延迟

| P50 | P95 |
|-----|-----|
| {_fmt_val(ret_lat.get('p50'))}ms | {_fmt_val(ret_lat.get('p95'))}ms |

### 2.3 按论文分组

{_per_group_table(ret.get('by_paper', {{}}), ['recall@10', 'mrr'])}

### 2.4 按问题类型分组

{_per_group_table(ret.get('by_type', {{}}), ['recall@10', 'mrr'])}

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
| TTFB | {_fmt_val(ans_lat.get('ttfb_p50'))}ms | {_fmt_val(ans_lat.get('ttfb_p95'))}ms |
| 总延迟 | {_fmt_val(ans_lat.get('total_p50'))}ms | {_fmt_val(ans_lat.get('total_p95'))}ms |

### 3.3 按问题类型分组

{_per_group_table(ans.get('by_type', {{}}), ['overall'])}

### 3.4 按论文分组

{_per_group_table(ans.get('by_paper', {{}}), ['overall'])}

---

## 4. 交叉分析

### 4.1 检索 vs 答案质量

- 检索 Recall@10 均值：{_fmt_val(ret_recall_10)}
- 答案综合分均值：{_fmt_val(ans_overall)}

{"**发现**：检索与答案质量存在差距，说明即使检索召回了相关内容，答案生成仍可能存在问题（如信息整合不当、跨论文混淆）。" if ret_recall_10 and ans_overall and ret_recall_10 > 0.5 and ans_overall < 4.0 else ""}

### 4.2 论文难度排名

（综合检索 Recall@10 + 答案综合分，降序排列。分数越低越难。）

{_per_group_table(ret.get('by_paper', {{}}), ['recall@10', 'mrr'])}

### 4.3 Agent 行为分析

（基于 answer_detailed.csv 统计）
- 平均工具调用次数：待分析
- 平均迭代轮次：待分析

---

## 5. 红旗 & 改进建议

### 5.1 最差 5 个 Case

| ID | 问题 | 忠实度 | 相关性 | 完整性 |
|----|------|--------|--------|--------|
{worst_table if worst_table else "| - | 无低分 case | - | - |"}

### 5.2 可操作改进项

1. **检索层面**：
   - 零召回问题需检查 embedding 模型对该领域论文的覆盖（当前模型：{ds.get('embedding_model', '?')}）
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
    parser.add_argument("--run-dir", required=True, help="Path to results/<timestamp> directory")
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
```

- [ ] **Step 4: Run tests — all should pass**

```bash
cd engine && python -m pytest tests/test_generate_report.py -v
```

Expected: PASS (2/2)

- [ ] **Step 5: Commit**

```bash
git add engine/eval/generate_report.py engine/tests/test_generate_report.py
git commit -m "feat(eval): add report generator with cross-layer analysis

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: End-to-End Dry-Run Verification

**Files:**
- No new files.

Full pipeline verification with `--dry-run` mode.

- [ ] **Step 1: Run dataset generation against real DB**

```bash
cd engine && python -m engine.eval.generate_queries_v2 --seed 42
```

Expected:
- Output directory created under `engine/eval/results/<ts>/`
- `golden_dataset_v2.json` written
- 70-85 questions generated
- Question types match target distribution approximately

Manual check: Inspect 5 random questions + their gold labels for quality.

- [ ] **Step 2: Run retrieval evaluation (dry-run on 3 queries)**

If Engine is not running locally, start it first:
```bash
SKIP_ENGINE=1 python -m backend.run &
python -m engine.run &
```

Then:
```bash
cd engine && python -m engine.eval.run_retrieval_v2 \
  --dataset results/<ts>/golden_dataset_v2.json \
  --tenant-id default-tenant \
  --kb-uid 9141b989-ee70-42f7-bcd3-c2c5ffed68db \
  --index-generation <from-DB> \
  --graph-generation <from-DB>
```

First check the KB's active generations:
```bash
python -c "
import os; from dotenv import load_dotenv; load_dotenv('.env')
from sqlalchemy import create_engine, text
engine = create_engine(os.environ['DATABASE_URL'])
db = engine.connect()
row = db.execute(text(\"SELECT active_index_generation, active_graph_generation FROM knowledge_topic WHERE kb_uid='9141b989-ee70-42f7-bcd3-c2c5ffed68db'\")).fetchone()
print(f'index={row[0]}, graph={row[1]}')
db.close()
"
```

Expected:
- `retrieval_detailed.csv` + `retrieval_summary.json` written
- All 3 dry-run queries have non-zero latency
- Metrics computed correctly

- [ ] **Step 3: Run answer evaluation (dry-run on 3 queries)**

```bash
cd engine && python -m engine.eval.run_answer_eval \
  --dataset results/<ts>/golden_dataset_v2.json \
  --kb-uid 9141b989-ee70-42f7-bcd3-c2c5ffed68db \
  --dry-run
```

Expected:
- 3 queries streamed from Engine
- LLM judge scores returned (1-5 range)
- `answer_detailed.csv` + `answer_summary.json` written

- [ ] **Step 4: Run report generation**

```bash
cd engine && python -m engine.eval.generate_report --run-dir results/<ts>
```

Expected:
- `REPORT.md` written in run directory
- All sections rendered with data

- [ ] **Step 5: Full pipeline run (all 85 questions)**

```bash
# Step 1
cd engine && python -m engine.eval.generate_queries_v2 --seed 42

# Step 2 (replace <ts> and generation IDs)
cd engine && python -m engine.eval.run_retrieval_v2 \
  --dataset results/<ts>/golden_dataset_v2.json \
  --tenant-id default-tenant \
  --kb-uid 9141b989-ee70-42f7-bcd3-c2c5ffed68db \
  --index-generation <idx> --graph-generation <gfx>

# Step 3
cd engine && python -m engine.eval.run_answer_eval \
  --dataset results/<ts>/golden_dataset_v2.json \
  --kb-uid 9141b989-ee70-42f7-bcd3-c2c5ffed68db

# Step 4
cd engine && python -m engine.eval.generate_report --run-dir results/<ts>
```

Expected: Complete `REPORT.md` with all Layer 1 + Layer 2 data.

- [ ] **Step 6: Final commit (if any fixes)**

Only commit if fixes were needed during verification.

```bash
git add <fixed files>
git commit -m "fix(eval): dry-run verification fixes

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review

### Spec Coverage Check

| Spec Requirement | Task(s) | Status |
|-----------------|---------|--------|
| 80+ Chinese questions, 5 types | Task 1 | ✓ |
| Gold chunks auto-labeled by LLM | Task 1 | ✓ |
| Cross-paper questions | Task 1 | ✓ `_assign_types` + `cross_paper_ids` |
| Backward-compatible dataset | Task 1 | ✓ `relevant_children` field |
| Recall/Precision/MRR/NDCG/Hit | Task 2 | ✓ `compute_retrieval_metrics` |
| Latency measurement | Task 2 | ✓ `time.perf_counter()` |
| Channel health tracking | Task 2 | ✓ `_estimate_channel_hits` |
| Grouped by paper/type | Task 2 | ✓ `aggregate_by_dimension` |
| Engine chat/answer call | Task 3 | ✓ HTTP streaming + scope signing |
| LLM-as-Judge 3D scoring | Task 3 | ✓ faithfulness/relevance/completeness |
| Token tracking | Task 3 | ✓ token_events count from NDJSON |
| Bad case collection | Task 3 | ✓ flagged when faith<3 or rel<3 |
| Comprehensive report | Task 4 | ✓ 5-section Markdown |
| Cross-layer analysis | Task 4 | ✓ retrieval vs answer quality |
| 100% Chinese questions | Task 1 | ✓ `lang="zh"` forced |
| Read-only DB access | All | ✓ Only SELECT queries |
| No modification to production | All | ✓ New files only under `engine/eval/` and `engine/tests/` |
| Standalone CLI | All | ✓ Each script has own `main()` + argparse |

### Placeholder Scan

- No TBD, TODO, or incomplete sections.
- All code blocks are concrete implementations.
- All test assertions have expected values.

### Type Consistency

- `relevant_children` field is `[{chunk_id, chunk_text, relevance}]` — consistent across Task 1 (generation), Task 2 (consumption), Task 3 (judge prompt).
- `compute_retrieval_metrics(retrieved_ids: list[str], relevant_ids: set[str], ks: tuple[int,...]) -> dict` — consistent between Task 2 implementation and test.
- `aggregate_by_dimension(results: list[dict], dimension: str, metric_keys: list[str]) -> dict` — consistent.
- `build_judge_prompt(question, gold_chunks_text, answer) -> str` — consistent.
- `parse_judge_response(response_text) -> dict` — returns `{faithfulness, relevance, completeness, overall, rationale}`, used consistently.
- `load_data(run_dir) -> dict` keys: `dataset_meta`, `retrieval`, `answer`, `answer_detail`, `low_scores_count`, `run_ts` — consumed by `render_report`.
