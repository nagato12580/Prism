# prism/engine/eval/generate_queries.py
"""Step 1: 从已向量化的 Parent Chunk 中随机采样，LLM 生成问题 → 黄金数据集。

用法:
    cd engine && python -m eval.generate_queries

输出:
    eval/golden_dataset.json — 待人工核对后成为黄金数据集
"""
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

# 确保项目根目录在 sys.path，以便导入 engine 和 backend 模块
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from engine.app.config import settings
from engine.app.llm.client import chat
from backend.app.models.knowledge_item import KnowledgeChunk, KnowledgeItem

# ─── 配置 ──────────────────────────────────────────────
SAMPLE_SIZE = 60  # 目标采样数
TOP_K_EVAL = 20   # 评估时的 top-k
OUTPUT_PATH = Path(__file__).resolve().parent / "golden_dataset.json"

# ─── 数据库连接 ─────────────────────────────────────────
_engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
_Session = sessionmaker(bind=_engine)


def _prepare_output_path() -> None:
    """确保 golden_dataset.json 不会默默覆盖已有文件。"""
    if OUTPUT_PATH.exists():
        backup = OUTPUT_PATH.with_suffix(".json.bak")
        print(f"[!] 已有 golden_dataset.json 将被备份为 {backup.name}")
        backup.write_text(OUTPUT_PATH.read_text(encoding="utf-8"), encoding="utf-8")


def _sample_parents(sample_size: int) -> list[dict]:
    """随机采样拥有子块的 Parent Chunk，返回包含文本和元信息的列表。"""
    db = _Session()
    try:
        # 查询所有 parent chunk 及其子块数量、item 标题
        rows = db.execute(text("""
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
            GROUP BY kc.id, kc.chunk_text, kc.item_id, ki.title
            HAVING child_count > 0
        """)).fetchall()

        total = len(rows)
        if total == 0:
            print("[!] 没有找到任何拥有子块的 Parent Chunk。请先摄入文档。")
            return []

        actual_sample = min(sample_size, total)
        sampled = random.sample(rows, actual_sample)

        results = []
        for row in sampled:
            # 获取该 parent 的所有子块 ID
            children = db.query(KnowledgeChunk).filter(
                KnowledgeChunk.parent_id == row.parent_id,
                KnowledgeChunk.chunk_type == "child",
            ).all()

            results.append({
                "parent_id": row.parent_id,
                "chunk_text": row.chunk_text,
                "item_id": row.item_id,
                "item_title": row.item_title,
                "child_count": row.child_count,
                "child_ids": [c.id for c in children],
                "child_texts": [c.chunk_text for c in children],
            })

        print(f"[*] 总 Parent: {total}, 采样: {actual_sample}")
        print(f"[*] 平均子块/Parent: {sum(r['child_count'] for r in results) / actual_sample:.1f}")
        return results
    finally:
        db.close()


def _generate_question(chunk_text: str, item_title: str, index: int) -> tuple[str, str]:
    """调用 LLM 根据文档内容生成一个问题。

    Returns:
        (question, language) — language 为 'zh' 或 'en'
    """
    # 80% 中文 / 20% 英文
    lang = "zh" if random.random() < 0.8 else "en"

    if lang == "en":
        lang_instruction = "Generate a natural English question"
    else:
        lang_instruction = "生成一个自然的中文提问"

    prompt = f"""你是一个检索质量评估数据生成器。给定一段文档内容，请生成一个能用该文档回答的问题。

要求：
- {lang_instruction}
- 问题答案必须能在这段文档中找到
- 问题类型多样化：事实查询、概念解释、对比分析、具体数据询问等
- 问题长度适中（10-50 字）
- 只输出问题本身，不要任何解释、标点修饰或前缀

文档来源：{item_title}
文档内容：
{chunk_text[:3000]}

问题："""

    try:
        response = chat([{"role": "user", "content": prompt}])
        question = response.strip().strip('"').strip("'").strip("？").strip("?")
        # 移除可能的 "问题：" 前缀
        for prefix in ["问题：", "问题:", "Question:", "question:"]:
            if question.startswith(prefix):
                question = question[len(prefix):].strip()
        return question, lang
    except Exception as e:
        print(f"  [!] LLM 调用失败 (index={index}): {e}")
        return "", lang


def main():
    print("=" * 60)
    print("Prism 检索评估 — 黄金数据集生成")
    print("=" * 60)

    # 1. 备份已有文件
    _prepare_output_path()

    # 2. 采样 Parent Chunks
    print("\n[1/3] 从数据库采样 Parent Chunks...")
    parents = _sample_parents(SAMPLE_SIZE)
    if not parents:
        return

    # 3. LLM 生成问题
    print(f"\n[2/3] 调用 LLM ({settings.LLM_MODEL}) 生成问题...")
    queries = []
    zh_count = 0
    en_count = 0
    failed = 0

    for i, p in enumerate(parents):
        question, lang = _generate_question(p["chunk_text"], p["item_title"], i)
        if question:
            queries.append({
                "id": f"q{i + 1:03d}",
                "question": question,
                "language": lang,
                "parent_chunk_id": p["parent_id"],
                "parent_chunk_text": p["chunk_text"][:500] + (
                    "..." if len(p["chunk_text"]) > 500 else ""
                ),
                "relevant_children": [
                    {"chunk_id": cid, "chunk_text": ctext}
                    for cid, ctext in zip(p["child_ids"], p["child_texts"])
                ],
                "item_id": p["item_id"],
                "item_title": p["item_title"],
            })
            if lang == "zh":
                zh_count += 1
            else:
                en_count += 1
            print(f"  [{i + 1}/{len(parents)}] {lang} | {question[:60]}...")
        else:
            failed += 1
            print(f"  [{i + 1}/{len(parents)}] FAILED")

    # 4. 保存
    print(f"\n[3/3] 保存到 {OUTPUT_PATH}")
    dataset = {
        "meta": {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "total_queries": len(queries),
            "zh_count": zh_count,
            "en_count": en_count,
            "failed_count": failed,
            "sampling_strategy": "random_parent_with_children",
            "sample_size": SAMPLE_SIZE,
            "llm_model": settings.LLM_MODEL,
            "embedding_model": settings.EMBEDDING_MODEL,
            "top_k_eval": TOP_K_EVAL,
        },
        "queries": queries,
    }

    OUTPUT_PATH.write_text(
        json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"\n[OK] 完成! 生成 {len(queries)} 条问题 (中文: {zh_count}, 英文: {en_count}, 失败: {failed})")
    print(f"  输出: {OUTPUT_PATH}")
    print(f"  下一步: 人工核对 golden_dataset.json，修正/剔除不合格条目")


if __name__ == "__main__":
    random.seed(42)  # 固定随机种子保证可复现
    main()
