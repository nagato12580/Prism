# prism/engine/app/retrieval/bm25_search.py
"""BM25 风格关键词检索：jieba 分词 + SQL LIKE 匹配。"""
import jieba
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from ..config import settings

_engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
_Session = sessionmaker(bind=_engine)


def bm25_search(query: str, top_k: int = 10) -> list[dict]:
    """关键词检索，返回 [{chunk_id, item_id, score}]。score 为命中关键词数的简单评分。"""
    from backend.app.models.knowledge_item import KnowledgeChunk

    tokens = [t for t in jieba.cut(query) if t.strip() and len(t) > 1]
    if not tokens:
        return []

    db = _Session()
    try:
        results = []
        chunks = db.query(KnowledgeChunk).all()
        for chunk in chunks:
            score = sum(chunk.chunk_text.count(token) for token in tokens)
            if score > 0:
                results.append({
                    "chunk_id": chunk.id,
                    "item_id": chunk.item_id,
                    "score": float(score),
                })
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]
    finally:
        db.close()
