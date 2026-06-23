# prism/engine/app/ingestion/pipeline.py
"""Ingestion pipeline: chunk, embed, store vectors, index text, settle governance."""

import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ..config import settings
from ..es_client import CHUNKS_INDEX, get_es
from ..milvus_client import insert_vectors
from .chunker import chunk_parent_child
from .vectorizer import embed_texts

_engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
_Session = sessionmaker(bind=_engine)
logger = logging.getLogger("uvicorn.error")


def _log_stage(item_id: str, stage: str, **fields) -> None:
    details = " ".join(f"{key}={value}" for key, value in fields.items())
    suffix = f" {details}" if details else ""
    logger.info("[ingest.pipeline] %s item_id=%s stage=%s%s", stage, item_id, stage, suffix)


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
    except Exception as exc:
        logger.warning("[ingest.pipeline] delete_es_chunks skipped item_id=%s error=%s", item_id, exc)


def _bulk_index_chunks_es(
    item_id: str,
    topic_id: str | None,
    doc_name: str,
    source_type: str,
    parent_chunks,
    parent_id_map_by_index: dict[int, str],
    child_id_map_by_position: dict[tuple[int, int], str],
    child_parent_id_map: dict[tuple[int, int], str],
) -> int:
    es = get_es()
    now = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
    docs = []
    for parent_index, pc in enumerate(parent_chunks):
        parent_id = parent_id_map_by_index.get(parent_index, "")
        if parent_id:
            docs.append(
                {
                    "_index": CHUNKS_INDEX,
                    "_id": parent_id,
                    "_source": {
                        "chunk_id": parent_id,
                        "item_id": item_id,
                        "topic_id": topic_id,
                        "content": pc.content,
                        "doc_name": doc_name,
                        "source_type": source_type,
                        "chunk_type": "parent",
                        "parent_id": None,
                        "created_at": now,
                    },
                }
            )
        for child_index, child_text in enumerate(pc.children):
            child_position = (parent_index, child_index)
            cid = child_id_map_by_position.get(child_position, "")
            pid = child_parent_id_map.get(child_position, "")
            docs.append(
                {
                    "_index": CHUNKS_INDEX,
                    "_id": cid,
                    "_source": {
                        "chunk_id": cid,
                        "item_id": item_id,
                        "topic_id": topic_id,
                        "content": child_text,
                        "doc_name": doc_name,
                        "source_type": source_type,
                        "chunk_type": "child",
                        "parent_id": pid,
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
    except Exception as exc:
        logger.warning("[ingest.pipeline] index_es skipped item_id=%s error=%s", item_id, exc)
        return 0


def ingest_item(item_id: str) -> int:
    """Process one knowledge item and return the number of child chunks."""
    from backend.app.models.knowledge_item import KnowledgeChunk, KnowledgeItem
    from backend.app.services.knowledge_governance import (
        clear_document_item_governance,
        settle_document_item_to_governance,
    )

    started_at = time.monotonic()
    db = _Session()
    try:
        _log_stage(item_id, "start")
        item = db.query(KnowledgeItem).filter(KnowledgeItem.id == item_id).first()
        if not item or not item.content:
            _log_stage(item_id, "empty_item")
            return 0

        _log_stage(item_id, "cleanup")
        clear_document_item_governance(db, item_id)
        db.query(KnowledgeChunk).filter(KnowledgeChunk.item_id == item_id).delete()

        _log_stage(item_id, "chunking", chars=len(item.content or ""))
        parents = chunk_parent_child(item.content)
        if not parents:
            _log_stage(item_id, "no_parent_chunks")
            return 0

        child_texts = []
        for pc in parents:
            child_texts.extend(pc.children)

        if not child_texts:
            _log_stage(item_id, "no_child_chunks", parents=len(parents))
            return 0

        _log_stage(item_id, "embedding", parents=len(parents), children=len(child_texts))
        embeddings = embed_texts(child_texts)
        _log_stage(item_id, "embedding_done", vectors=len(embeddings))

        _log_stage(item_id, "resolve_topic")
        topic_id, doc_name, source_type = _resolve_topic_info(db, item_id)

        _log_stage(item_id, "delete_es_chunks")
        _delete_es_chunks_by_item(item_id)

        parent_id_map_by_index: dict[int, str] = {}
        child_id_map_by_position: dict[tuple[int, int], str] = {}
        child_parent_id_map: dict[tuple[int, int], str] = {}

        _log_stage(item_id, "store_mysql_chunks", parents=len(parents), children=len(child_texts))
        for parent_index, pc in enumerate(parents):
            parent = KnowledgeChunk(
                item_id=item_id,
                chunk_text=pc.content,
                chunk_index=parent_index,
                chunk_type="parent",
            )
            db.add(parent)
            db.flush()
            parent_id_map_by_index[parent_index] = parent.id

            for child_index, child_text in enumerate(pc.children):
                child = KnowledgeChunk(
                    item_id=item_id,
                    chunk_text=child_text,
                    chunk_index=child_index,
                    chunk_type="child",
                    parent_id=parent.id,
                )
                db.add(child)
                db.flush()
                child_position = (parent_index, child_index)
                child_id_map_by_position[child_position] = child.id
                child_parent_id_map[child_position] = parent.id

        _log_stage(item_id, "store_milvus", vectors=len(embeddings))
        child_embedding_index = 0
        for parent_index, pc in enumerate(parents):
            for child_index, _child_text in enumerate(pc.children):
                cid = child_id_map_by_position[(parent_index, child_index)]
                emb = embeddings[child_embedding_index]
                insert_vectors(chunk_id=cid, item_id=item_id, embedding=emb)
                child_embedding_index += 1

        _log_stage(item_id, "index_es", parents=len(parents), children=len(child_texts))
        es_count = _bulk_index_chunks_es(
            item_id=item_id,
            topic_id=topic_id,
            doc_name=doc_name,
            source_type=source_type,
            parent_chunks=parents,
            parent_id_map_by_index=parent_id_map_by_index,
            child_id_map_by_position=child_id_map_by_position,
            child_parent_id_map=child_parent_id_map,
        )
        _log_stage(item_id, "index_es_done", indexed=es_count)

        item.summary = item.content[:200]
        _log_stage(item_id, "settle_governance")
        settle_document_item_to_governance(db, item_id)
        _log_stage(item_id, "commit")
        db.commit()
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        _log_stage(item_id, "done", children=len(child_texts), elapsed_ms=elapsed_ms)
        return len(child_texts)
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        logger.exception("[ingest.pipeline] failed item_id=%s elapsed_ms=%s error=%s", item_id, elapsed_ms, exc)
        db.rollback()
        raise
    finally:
        db.close()
