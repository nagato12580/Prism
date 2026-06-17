# prism/engine/app/ingestion/pipeline.py
"""摄入管线：读取条目 → 父子分块 → 向量化子块 → 存 MySQL + Milvus + ES。

父块（~1024 token）只存 MySQL + ES，不向量化。
子块（~256 token）正常向量化，通过 parent_id 关联父块。
检索时命中子块 → 返回父块完整上下文。
"""
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from ..config import settings
from .chunker import chunk_parent_child
from .vectorizer import embed_texts
from ..milvus_client import insert_vectors
from ..es_client import get_es, CHUNKS_INDEX

# Engine 独立 DB session（不依赖 FastAPI 依赖注入）
_engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
_Session = sessionmaker(bind=_engine)


def _resolve_topic_info(db, item_id: str) -> tuple[str | None, str | None, str | None]:
    from backend.app.models.knowledge_item import KnowledgeFile, KnowledgeItem

    kf = db.query(KnowledgeFile).filter(KnowledgeFile.item_id == item_id).first()
    if kf:
        topic_id = kf.topic_id
        doc_name = kf.title or kf.original_filename or ""
        source_type = kf.media_type or "document"
        return topic_id, doc_name, source_type

    item = db.query(KnowledgeItem).filter(KnowledgeItem.id == item_id).first()
    doc_name = item.title if item else ""
    return None, doc_name, "document"


def _delete_es_chunks_by_item(item_id: str) -> None:
    es = get_es()
    try:
        es.delete_by_query(
            index=CHUNKS_INDEX,
            body={"query": {"term": {"item_id": item_id}}},
            refresh=True,
        )
    except Exception:
        pass


def _bulk_index_chunks_es(
    item_id: str,
    topic_id: str | None,
    doc_name: str,
    source_type: str,
    parent_chunks,  # list of ParentChunk
    chunk_id_map: dict[str, str],  # child_text → chunk_id
    parent_id_map: dict[str, str],  # child chunk_id → parent chunk_id
) -> int:
    """批量写入 parent + child chunk 到 ES。"""
    es = get_es()
    now = datetime.now(timezone.utc).isoformat()
    docs = []
    for pc in parent_chunks:
        parent_id = chunk_id_map.get(pc.content, "")
        if parent_id:
            docs.append({
                "_index": CHUNKS_INDEX, "_id": parent_id,
                "_source": {
                    "chunk_id": parent_id, "item_id": item_id,
                    "topic_id": topic_id, "content": pc.content,
                    "doc_name": doc_name, "source_type": source_type,
                    "chunk_type": "parent", "parent_id": None,
                    "created_at": now,
                },
            })
        for child_text in pc.children:
            cid = chunk_id_map.get(child_text, "")
            pid = parent_id_map.get(cid, "")
            docs.append({
                "_index": CHUNKS_INDEX, "_id": cid,
                "_source": {
                    "chunk_id": cid, "item_id": item_id,
                    "topic_id": topic_id, "content": child_text,
                    "doc_name": doc_name, "source_type": source_type,
                    "chunk_type": "child", "parent_id": pid,
                    "created_at": now,
                },
            })
    if not docs:
        return 0
    from elasticsearch import helpers
    try:
        success, _ = helpers.bulk(es, docs)
        es.indices.refresh(index=CHUNKS_INDEX)
        return success
    except Exception:
        return 0


def ingest_item(item_id: str) -> int:
    """处理一个知识条目，返回生成的 chunk 数量（子块数）。"""
    from backend.app.models.knowledge_item import KnowledgeItem, KnowledgeChunk
    from backend.app.services.knowledge_governance import (
        clear_document_item_governance,
        settle_document_item_to_governance,
    )

    db = _Session()
    try:
        item = db.query(KnowledgeItem).filter(KnowledgeItem.id == item_id).first()
        if not item or not item.content:
            return 0

        # 删除旧治理数据和旧 chunk（重新摄入时）
        clear_document_item_governance(db, item_id)
        db.query(KnowledgeChunk).filter(KnowledgeChunk.item_id == item_id).delete()

        # 父子分块
        parents = chunk_parent_child(item.content)
        if not parents:
            return 0

        # 收集所有子块文本
        child_texts = []
        for pc in parents:
            child_texts.extend(pc.children)

        if not child_texts:
            return 0

        # 批量向量化子块（仅子块）
        embeddings = embed_texts(child_texts)

        # 反查 topic 信息
        topic_id, doc_name, source_type = _resolve_topic_info(db, item_id)

        # 删除 ES 中的旧 chunk
        _delete_es_chunks_by_item(item_id)

        # 存储：父块 + 子块 → MySQL；子块 → Milvus
        chunk_id_map: dict[str, str] = {}  # text → chunk_id
        parent_id_map: dict[str, str] = {}  # child_id → parent_id

        # 先存父块（不向量化）
        for pc in parents:
            parent = KnowledgeChunk(
                item_id=item_id,
                chunk_text=pc.content,
                chunk_index=0,
                chunk_type="parent",
            )
            db.add(parent)
            db.flush()
            chunk_id_map[pc.content] = parent.id

            # 存子块
            for child_text in pc.children:
                child = KnowledgeChunk(
                    item_id=item_id,
                    chunk_text=child_text,
                    chunk_index=0,
                    chunk_type="child",
                    parent_id=parent.id,
                )
                db.add(child)
                db.flush()
                chunk_id_map[child_text] = child.id
                parent_id_map[child.id] = parent.id

        # 子块向量存入 Milvus
        child_idx = 0
        for pc in parents:
            for child_text in pc.children:
                cid = chunk_id_map[child_text]
                emb = embeddings[child_idx]
                insert_vectors(chunk_id=cid, item_id=item_id, embedding=emb)
                child_idx += 1

        # 写入 ES（父子块都写，但只有子块有向量）
        _bulk_index_chunks_es(
            item_id=item_id, topic_id=topic_id,
            doc_name=doc_name, source_type=source_type,
            parent_chunks=parents,
            chunk_id_map=chunk_id_map,
            parent_id_map=parent_id_map,
        )

        # 生成摘要
        item.summary = item.content[:200]
        settle_document_item_to_governance(db, item_id)
        db.commit()
        return len(child_texts)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
