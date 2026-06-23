# prism/engine/eval/generate_queries.py
"""Generate a retrieval golden dataset from ingested parent chunks.

Examples:
    python -m engine.eval.generate_queries
    python -m engine.eval.generate_queries --item-ids id1 id2 --sample-size 40 --output evaluation/datasets/formal_docs_v1.json
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

SAMPLE_SIZE = 60
TOP_K_EVAL = 20
OUTPUT_PATH = Path(__file__).resolve().parent / "golden_dataset.json"
DEFAULT_EVAL_DATASET_DIR = _project_root / "evaluation" / "datasets"

_engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
_Session = sessionmaker(bind=_engine)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Prism retrieval golden dataset")
    parser.add_argument(
        "--item-ids",
        nargs="+",
        default=None,
        help="Limit sampling to specific KnowledgeItem IDs.",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=SAMPLE_SIZE,
        help=f"Number of parent chunks to sample. Default: {SAMPLE_SIZE}",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(OUTPUT_PATH),
        help=f"Output dataset JSON path. Default: {OUTPUT_PATH}",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible sampling and language choice.",
    )
    return parser.parse_args(argv)


def _prepare_output_path(output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        backup = output_path.with_suffix(f"{output_path.suffix}.bak")
        print(f"[!] Existing dataset will be backed up to {backup}", flush=True)
        backup.write_text(output_path.read_text(encoding="utf-8"), encoding="utf-8")


def _sample_parents(sample_size: int, item_ids: list[str] | None = None) -> list[dict[str, Any]]:
    db = _Session()
    try:
        where_item = ""
        params: dict[str, Any] = {}
        if item_ids:
            placeholders = []
            for index, item_id in enumerate(item_ids):
                key = f"item_id_{index}"
                placeholders.append(f":{key}")
                params[key] = item_id
            where_item = f"AND kc.item_id IN ({', '.join(placeholders)})"

        rows = db.execute(
            text(
                f"""
                SELECT
                    kc.id AS parent_id,
                    kc.chunk_text,
                    kc.item_id,
                    ki.title AS item_title,
                    COUNT(child.id) AS child_count
                FROM knowledge_chunk kc
                JOIN knowledge_item ki ON ki.id = kc.item_id
                JOIN knowledge_chunk child ON child.parent_id = kc.id
                WHERE kc.chunk_type = 'parent'
                {where_item}
                GROUP BY kc.id, kc.chunk_text, kc.item_id, ki.title
                HAVING child_count > 0
                """
            ),
            params,
        ).fetchall()

        total = len(rows)
        if total == 0:
            print("[!] No parent chunks with child chunks found. Ingest/vectorize documents first.", flush=True)
            return []

        actual_sample = min(sample_size, total)
        sampled = random.sample(rows, actual_sample)

        results: list[dict[str, Any]] = []
        for row in sampled:
            children = (
                db.query(KnowledgeChunk)
                .filter(
                    KnowledgeChunk.parent_id == row.parent_id,
                    KnowledgeChunk.chunk_type == "child",
                )
                .order_by(KnowledgeChunk.chunk_index.asc(), KnowledgeChunk.created_at.asc(), KnowledgeChunk.id.asc())
                .all()
            )
            results.append(
                {
                    "parent_id": row.parent_id,
                    "chunk_text": row.chunk_text,
                    "item_id": row.item_id,
                    "item_title": row.item_title,
                    "child_count": row.child_count,
                    "child_ids": [child.id for child in children],
                    "child_texts": [child.chunk_text for child in children],
                }
            )

        print(f"[*] Candidate parents: {total}, sampled: {actual_sample}", flush=True)
        print(f"[*] Average child chunks per sampled parent: {sum(r['child_count'] for r in results) / actual_sample:.1f}", flush=True)
        return results
    finally:
        db.close()


def _generate_question(chunk_text: str, item_title: str, index: int) -> tuple[str, str]:
    lang = "zh" if random.random() < 0.8 else "en"
    lang_instruction = "Generate a natural English question" if lang == "en" else "生成一个自然的中文提问"

    prompt = f"""你是一个检索质量评估数据生成器。给定一段文档内容，请生成一个能用该文档回答的问题。

要求：
- {lang_instruction}
- 问题答案必须能在这段文档中找到
- 问题类型尽量多样，包括事实查询、概念解释、对比分析、具体数据询问、规则/流程询问
- 问题长度适中
- 只输出问题本身，不要解释，不要添加前缀

文档来源：{item_title}
文档内容：
{chunk_text[:3000]}

问题："""

    try:
        response = chat([{"role": "user", "content": prompt}])
        question = response.strip().strip('"').strip("'").strip("：").strip(":").strip("?").strip("？")
        for prefix in ["问题：", "问题:", "Question:", "question:"]:
            if question.startswith(prefix):
                question = question[len(prefix) :].strip()
        return question, lang
    except Exception as exc:
        print(f"  [!] LLM call failed index={index}: {exc}", flush=True)
        return "", lang


def _build_dataset(
    *,
    parents: list[dict[str, Any]],
    sample_size: int,
    item_ids: list[str] | None,
    output_path: Path,
) -> dict[str, Any]:
    queries: list[dict[str, Any]] = []
    zh_count = 0
    en_count = 0
    failed = 0

    for index, parent in enumerate(parents):
        question, lang = _generate_question(parent["chunk_text"], parent["item_title"], index)
        if not question:
            failed += 1
            print(f"  [{index + 1}/{len(parents)}] FAILED", flush=True)
            continue

        queries.append(
            {
                "id": f"q{len(queries) + 1:03d}",
                "question": question,
                "language": lang,
                "parent_chunk_id": parent["parent_id"],
                "parent_chunk_text": parent["chunk_text"][:500] + ("..." if len(parent["chunk_text"]) > 500 else ""),
                "relevant_children": [
                    {"chunk_id": child_id, "chunk_text": child_text}
                    for child_id, child_text in zip(parent["child_ids"], parent["child_texts"])
                ],
                "item_id": parent["item_id"],
                "item_title": parent["item_title"],
            }
        )
        if lang == "zh":
            zh_count += 1
        else:
            en_count += 1
        print(f"  [{index + 1}/{len(parents)}] {lang} | {question[:80]}...", flush=True)

    return {
        "meta": {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "total_queries": len(queries),
            "zh_count": zh_count,
            "en_count": en_count,
            "failed_count": failed,
            "sampling_strategy": "random_parent_with_children",
            "sample_size": sample_size,
            "candidate_item_ids": item_ids or [],
            "llm_model": settings.LLM_MODEL,
            "embedding_model": settings.EMBEDDING_MODEL,
            "top_k_eval": TOP_K_EVAL,
            "output_path": str(output_path),
        },
        "queries": queries,
    }


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    random.seed(args.seed)
    output_path = Path(args.output)

    print("=" * 60, flush=True)
    print("Prism retrieval golden dataset generation", flush=True)
    print("=" * 60, flush=True)
    print(f"Output: {output_path}", flush=True)
    print(f"Sample size: {args.sample_size}", flush=True)
    print(f"Item IDs: {args.item_ids or 'ALL'}", flush=True)

    _prepare_output_path(output_path)

    print("\n[1/3] Sampling parent chunks...", flush=True)
    parents = _sample_parents(args.sample_size, args.item_ids)
    if not parents:
        return

    print(f"\n[2/3] Generating questions with {settings.LLM_MODEL}...", flush=True)
    dataset = _build_dataset(
        parents=parents,
        sample_size=args.sample_size,
        item_ids=args.item_ids,
        output_path=output_path,
    )

    print(f"\n[3/3] Writing dataset to {output_path}", flush=True)
    output_path.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")

    meta = dataset["meta"]
    print(
        f"\n[OK] Generated {meta['total_queries']} questions "
        f"(zh={meta['zh_count']}, en={meta['en_count']}, failed={meta['failed_count']})"
    )
    print("Next step: manually review the dataset and remove or fix weak questions.", flush=True)


if __name__ == "__main__":
    main()
