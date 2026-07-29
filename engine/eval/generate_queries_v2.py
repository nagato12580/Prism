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

    # Build lookup for chunk_text from input children
    text_lookup = {c["chunk_id"]: c["chunk_text"] for c in children}

    try:
        response = chat([{"role": "user", "content": prompt}])
        # Extract JSON from response
        json_start = response.find("[")
        json_end = response.rfind("]") + 1
        if json_start >= 0 and json_end > json_start:
            labels = json.loads(response[json_start:json_end])
            valid = [l for l in labels if isinstance(l, dict) and "chunk_id" in l]
            return [{"chunk_id": l["chunk_id"],
                     "chunk_text": text_lookup.get(l["chunk_id"], ""),
                     "relevance": l.get("relevance", "context")}
                    for l in valid]
        return [{"chunk_id": c["chunk_id"],
                 "chunk_text": c["chunk_text"],
                 "relevance": "context"} for c in children]
    except Exception as exc:
        print(f"  [!] Labeling failed: {exc}", flush=True)
        return [{"chunk_id": c["chunk_id"],
                 "chunk_text": c["chunk_text"],
                 "relevance": "context"} for c in children]


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

    if type_idx < len(single_types):
        print(f"  [!] Warning: only allocated {type_idx}/{len(single_types)} single-paper types "
              f"— {len(single_types) - type_idx} question types were not assigned. "
              f"Consider increasing SAMPLE_SIZE_PER_PAPER or reducing question counts.", flush=True)

    # Create cross-paper entries
    used_ids = {d["parent_id"] for d in decorated}
    for ct in cross_types:
        # Pick 2-3 different papers
        cross_papers = random.sample(paper_ids, min(3, len(paper_ids)))
        cross_parents = []
        for pid in cross_papers:
            available = [p for p in paper_parents[pid] if p["parent_id"] not in used_ids]
            if available:
                chosen = random.choice(available)
                cross_parents.append(chosen)
                used_ids.add(chosen["parent_id"])
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
    checkpoint_path: Path | None = None,
) -> dict[str, Any]:
    """Generate questions and gold labels for all parents.

    If checkpoint_path is provided, appends each completed query as a JSON line
    to that file for incremental recovery on failure.
    """
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

        entry = {
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
        }
        queries.append(entry)
        type_counts[qtype] = type_counts.get(qtype, 0) + 1
        print(f"  [{index + 1}/{len(decorated)}] {qtype} | {question[:80]}...", flush=True)

        # Incremental checkpoint
        if checkpoint_path is not None:
            try:
                with open(checkpoint_path, "a", encoding="utf-8") as cp:
                    cp.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception as exc:
                print(f"  [!] Checkpoint write failed: {exc}", flush=True)

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

        checkpoint_path = run_dir / "golden_dataset_v2.partial.jsonl"

        print(f"\n[2/3] Generating questions with {settings.LLM_MODEL}...", flush=True)
        dataset = build_dataset(parents, PAPER_IDS, output_path, checkpoint_path=checkpoint_path)

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
