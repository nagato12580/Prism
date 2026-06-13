# prism/engine/app/ingestion/pipeline.py
"""摄入管线：读取条目 → 分块 → 向量化 → 存 Milvus + MySQL。"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from ..config import settings
from .chunker import chunk_text
from .vectorizer import embed_texts
from ..milvus_client import insert_vectors

# Engine 独立 DB session（不依赖 FastAPI 依赖注入）
_engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
_Session = sessionmaker(bind=_engine)


def ingest_item(item_id: str) -> int:
    """处理一个知识条目，返回生成的 chunk 数量。"""
    from backend.app.models.knowledge_item import KnowledgeItem, KnowledgeChunk

    db = _Session()
    try:
        item = db.query(KnowledgeItem).filter(KnowledgeItem.id == item_id).first()
        if not item or not item.content:
            return 0

        # 删除旧 chunk（重新摄入时）
        db.query(KnowledgeChunk).filter(KnowledgeChunk.item_id == item_id).delete()

        # 分块
        chunks = chunk_text(item.content)
        if not chunks:
            return 0

        # 批量向量化
        embeddings = embed_texts(chunks)

        # 存储每个 chunk
        for idx, (chunk_text_content, emb) in enumerate(zip(chunks, embeddings)):
            chunk = KnowledgeChunk(
                item_id=item_id,
                chunk_text=chunk_text_content,
                chunk_index=idx,
            )
            db.add(chunk)
            db.flush()  # 获取 chunk.id

            # 存入 Milvus
            insert_vectors(chunk_id=chunk.id, item_id=item_id, embedding=emb)

        # 生成摘要（简单版：取前 200 字）
        item.summary = item.content[:200]
        db.commit()
        return len(chunks)
    finally:
        db.close()
