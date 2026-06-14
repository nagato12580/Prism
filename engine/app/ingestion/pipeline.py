# prism/engine/app/ingestion/pipeline.py
"""摄入管线：读取条目 → 分块 → 向量化 → 存 MySQL + Milvus + ES。"""
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from ..config import settings
from .chunker import chunk_text
from .vectorizer import embed_texts
from ..milvus_client import insert_vectors
from ..es_client import get_es, CHUNKS_INDEX

# Engine 独立 DB session（不依赖 FastAPI 依赖注入）
_engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
_Session = sessionmaker(bind=_engine)


def _resolve_topic_info(db, item_id: str) -> tuple[str | None, str | None, str | None]:
    """通过 knowledge_file 反查 item 的 topic_id、doc_name 和 media_type。"""
    from backend.app.models.knowledge_item import KnowledgeFile, KnowledgeItem

    kf = db.query(KnowledgeFile).filter(KnowledgeFile.item_id == item_id).first()
    if kf:
        topic_id = kf.topic_id
        doc_name = kf.title or kf.original_filename or ""
        source_type = kf.media_type or "document"
        return topic_id, doc_name, source_type

    # fallback: 纯文本知识条目（手动创建，没有 file 记录）
    item = db.query(KnowledgeItem).filter(KnowledgeItem.id == item_id).first()
    doc_name = item.title if item else ""
    return None, doc_name, "document"


def _delete_es_chunks_by_item(item_id: str) -> None:
    """删除 ES 中该 item 的所有旧 chunk（重新摄入前清理）。"""
    es = get_es()
    try:
        resp = es.delete_by_query(
            index=CHUNKS_INDEX,
            body={
                "query": {
                    "term": {"item_id": item_id}
                }
            },
            refresh=True,
        )
    except Exception:
        # ES 删除失败不应阻断摄入主流程
        pass


def _bulk_index_chunks(
    item_id: str,
    topic_id: str | None,
    doc_name: str,
    source_type: str,
    chunks: list[str],
    chunk_ids: list[str],
) -> int:
    """批量写入 chunk 文档到 ES，返回成功条数。"""
    es = get_es()
    now = datetime.now(timezone.utc).isoformat()
    docs = []
    for idx, (chunk_text, chunk_id) in enumerate(zip(chunks, chunk_ids)):
        docs.append(
            {
                "_index": CHUNKS_INDEX,
                "_id": chunk_id,
                "_source": {
                    "chunk_id": chunk_id,
                    "item_id": item_id,
                    "topic_id": topic_id,
                    "content": chunk_text,
                    "doc_name": doc_name,
                    "source_type": source_type,
                    "created_at": now,
                },
            }
        )

    if not docs:
        return 0

    from elasticsearch import helpers
    try:
        success, _ = helpers.bulk(es, docs)
        es.indices.refresh(index=CHUNKS_INDEX)
        return success
    except Exception:
        # ES 写入失败不应阻断摄入主流程
        return 0


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

        # 反查 topic 信息
        topic_id, doc_name, source_type = _resolve_topic_info(db, item_id)

        # 删除 ES 中的旧 chunk
        _delete_es_chunks_by_item(item_id)

        # 存储每个 chunk
        chunk_ids = []
        for idx, (chunk_text_content, emb) in enumerate(zip(chunks, embeddings)):
            chunk = KnowledgeChunk(
                item_id=item_id,
                chunk_text=chunk_text_content,
                chunk_index=idx,
            )
            db.add(chunk)
            db.flush()  # 获取 chunk.id
            chunk_ids.append(chunk.id)

            # 存入 Milvus
            insert_vectors(chunk_id=chunk.id, item_id=item_id, embedding=emb)

        # 写入 ES（全文检索）
        _bulk_index_chunks(
            item_id=item_id,
            topic_id=topic_id,
            doc_name=doc_name,
            source_type=source_type,
            chunks=chunks,
            chunk_ids=chunk_ids,
        )

        # 生成摘要（简单版：取前 200 字）
        item.summary = item.content[:200]
        db.commit()
        return len(chunks)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

