"""一次性脚本：回填 golden_dataset.json 中缺失的 chunk 正文。"""
import json
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_project_root))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from engine.app.config import settings
from backend.app.models.knowledge_item import KnowledgeChunk

DATASET_PATH = Path(__file__).resolve().parent / "golden_dataset.json"

_engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
_Session = sessionmaker(bind=_engine)


def main():
    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    db = _Session()
    try:
        for q in dataset["queries"]:
            # 回填 parent 正文
            parent = db.query(KnowledgeChunk).filter(
                KnowledgeChunk.id == q["parent_chunk_id"]
            ).first()
            if parent:
                q["parent_chunk_text"] = parent.chunk_text[:500] + (
                    "..." if len(parent.chunk_text) > 500 else ""
                )

            # 回填 child 正文：从 UUID 列表转为 [{chunk_id, chunk_text}] 列表
            old_ids = q.pop("relevant_child_ids", [])
            children = []
            for cid in old_ids:
                chunk = db.query(KnowledgeChunk).filter(
                    KnowledgeChunk.id == cid
                ).first()
                children.append({
                    "chunk_id": cid,
                    "chunk_text": chunk.chunk_text if chunk else "[NOT FOUND]",
                })
            q["relevant_children"] = children

    finally:
        db.close()

    # 备份 + 写回
    bak = DATASET_PATH.with_suffix(".json.old")
    DATASET_PATH.rename(bak)
    DATASET_PATH.write_text(
        json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[OK] 已回填 {len(dataset['queries'])} 条问题的 chunk 正文")
    print(f"  旧文件备份: {bak}")


if __name__ == "__main__":
    main()
