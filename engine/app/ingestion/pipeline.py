# prism/engine/app/ingestion/pipeline.py
"""Ingestion pipeline: chunk, embed, store vectors, and index text."""

import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ..config import settings
from ..es_client import CHUNKS_INDEX, get_es
from ..milvus_client import delete_vectors_by_ids, insert_vectors_batch
from .chunker import chunk_parent_child
from .vectorizer import embed_texts

from ..extraction.stage_a import extract_stage_a_parallel
from backend.app.services.entity_extraction import settle_entity_candidates
from backend.app.services.graph_projection import project_item_entities
from backend.app.services.graph_client import GraphClient

_engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
_Session = sessionmaker(bind=_engine)
logger = logging.getLogger("uvicorn.error")


def _chunk_content(chunk) -> str:
    return getattr(chunk, "content", chunk)


def _chunk_page_start(chunk):
    return getattr(chunk, "page_start", None)


def _chunk_page_end(chunk):
    return getattr(chunk, "page_end", None)


def _log_stage(item_id: str, stage: str, **fields) -> None:
    details = " ".join(f"{key}={value}" for key, value in fields.items())
    suffix = f" {details}" if details else ""
    logger.info("[ingest.pipeline] %s item_id=%s stage=%s%s", stage, item_id, stage, suffix)


def _report(progress, stage: str, current: int = 0, total: int = 0) -> None:
    if not progress:
        return
    try:
        progress(stage=stage, current=current, total=total)
    except Exception as exc:
        logger.warning("[ingest.pipeline] progress callback skipped stage=%s error=%s", stage, exc)


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
    response = None
    try:
        response = es.delete_by_query(
            index=CHUNKS_INDEX,
            body={"query": {"term": {"item_id": item_id}}},
            refresh=True,
        )
    except Exception as exc:
        logger.exception("[ingest.pipeline] delete_es_chunks failed item_id=%s error=%s", item_id, exc)
        raise
    body = getattr(response, "body", response)
    getter = body.get if hasattr(body, "get") else None
    timed_out = getter("timed_out", False) if getter else getattr(body, "timed_out", False)
    failures = getter("failures", None) if getter else getattr(body, "failures", None)
    if timed_out or failures:
        raise RuntimeError(f"delete_es_chunks failed item_id={item_id} timed_out={timed_out} failures={failures}")


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
                        "page_start": pc.page_start,
                        "page_end": pc.page_end,
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
                        "content": _chunk_content(child_text),
                        "doc_name": doc_name,
                        "source_type": source_type,
                        "chunk_type": "child",
                        "parent_id": pid,
                        "page_start": _chunk_page_start(child_text),
                        "page_end": _chunk_page_end(child_text),
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
        logger.exception("[ingest.pipeline] index_es failed item_id=%s error=%s", item_id, exc)
        raise


def _run_stage_a_for_item(db, item_id: str, user_id: str) -> None:
    """Stage A: LLM-extract entities for every child chunk, settle to MySQL, project to Neo4j.

    Failures are logged and swallowed so graph/extraction issues never break ingestion.
    """
    if not settings.ENTITY_EXTRACT_ENABLED:
        return
    try:
        from backend.app.models import EntityMention, EntityRelation
        from backend.app.models.knowledge_item import KnowledgeChunk

        # Clean mentions/relations from any previous ingest of this item so
        # re-ingest (which creates fresh chunk UUIDs) doesn't leave orphans.
        # EntityRelation.source_id and EntityMention.source_id share the same
        # value space (the chunk id), so delete relations by chunk id first.
        stale_chunk_ids = [
            cid
            for (cid,) in (
                db.query(EntityMention.source_id)
                .filter(EntityMention.item_id == item_id, EntityMention.source_kind == "document_chunk")
                .all()
            )
        ]
        if stale_chunk_ids:
            db.query(EntityRelation).filter(
                EntityRelation.source_kind == "document_chunk",
                EntityRelation.source_id.in_(stale_chunk_ids),
            ).delete(synchronize_session=False)
            db.query(EntityMention).filter(
                EntityMention.item_id == item_id,
                EntityMention.source_kind == "document_chunk",
            ).delete(synchronize_session=False)
            db.flush()

        chunks = (
            db.query(KnowledgeChunk)
            .filter(KnowledgeChunk.item_id == item_id, KnowledgeChunk.chunk_type == "child")
            .all()
        )
        if not chunks:
            return
        chunk_inputs = [(c.id, c.chunk_text or "") for c in chunks]
        _log_stage(item_id, "stage_a_extract", chunks=len(chunk_inputs))
        per_chunk = extract_stage_a_parallel(chunk_inputs)

        for chunk in chunks:
            candidates = per_chunk.get(chunk.id, [])
            if not candidates:
                continue
            settle_entity_candidates(
                db,
                candidates,
                source_kind="document_chunk",
                source_id=chunk.id,
                item_id=item_id,
                chunk_id=chunk.id,
                user_id=user_id,
            )
        db.commit()
        _log_stage(item_id, "stage_a_settled")

        _project_item_entities_to_graph(db, item_id, user_id)
    except Exception as exc:
        logger.warning("[ingest.pipeline] stage_a_failed item_id=%s error=%s", item_id, exc)


def _project_item_entities_to_graph(db, item_id: str, user_id: str) -> None:
    try:
        client = GraphClient()
        try:
            project_item_entities(db, client, item_id=item_id, user_id=user_id)
        finally:
            client.close()
    except Exception as exc:
        logger.warning("[ingest.pipeline] graph_projection_failed item_id=%s error=%s", item_id, exc)


def ingest_item(item_id: str, progress=None) -> int:
    """Process one knowledge item and return the number of child chunks."""
    from backend.app.models.knowledge_item import KnowledgeChunk, KnowledgeItem
    from backend.app.services.knowledge_governance import clear_document_item_governance

    started_at = time.monotonic()
    db = _Session()
    try:
        _log_stage(item_id, "start")
        item = db.query(KnowledgeItem).filter(KnowledgeItem.id == item_id).first()
        if not item or not item.content:
            _log_stage(item_id, "empty_item")
            return 0

        content = item.content
        item_summary = content[:200]

        _log_stage(item_id, "resolve_topic")
        topic_id, doc_name, source_type = _resolve_topic_info(db, item_id)

        _log_stage(item_id, "chunking", chars=len(content or ""))
        _report(progress, "chunking", 0, 0)
        parents = chunk_parent_child(content)
        if not parents:
            _log_stage(item_id, "no_parent_chunks")
            return 0

        child_texts = []
        for pc in parents:
            child_texts.extend(_chunk_content(child) for child in pc.children)

        if not child_texts:
            _log_stage(item_id, "no_child_chunks", parents=len(parents))
            return 0

        _log_stage(item_id, "embedding", parents=len(parents), children=len(child_texts))
        _report(progress, "embedding", 0, len(child_texts))
        embeddings = embed_texts(child_texts)
        if len(embeddings) != len(child_texts):
            raise RuntimeError(
                f"Embedding count mismatch for item_id={item_id}: "
                f"expected={len(child_texts)} actual={len(embeddings)}"
            )
        _report(progress, "embedding", len(embeddings), len(child_texts))
        _log_stage(item_id, "embedding_done", vectors=len(embeddings))

        parent_id_map_by_index: dict[int, str] = {}
        child_id_map_by_position: dict[tuple[int, int], str] = {}
        child_parent_id_map: dict[tuple[int, int], str] = {}

        _log_stage(item_id, "cleanup")
        clear_document_item_governance(db, item_id)
        old_child_chunk_ids = [
            chunk_id
            for (chunk_id,) in (
                db.query(KnowledgeChunk.id)
                .filter(KnowledgeChunk.item_id == item_id, KnowledgeChunk.chunk_type == "child")
                .all()
            )
        ]
        db.query(KnowledgeChunk).filter(KnowledgeChunk.item_id == item_id).delete()

        _log_stage(item_id, "store_mysql_chunks", parents=len(parents), children=len(child_texts))
        _report(progress, "store_mysql_chunks", 0, len(child_texts))
        for parent_index, pc in enumerate(parents):
            parent = KnowledgeChunk(
                item_id=item_id,
                chunk_text=pc.content,
                chunk_index=parent_index,
                chunk_type="parent",
                extra_meta={"page_start": pc.page_start, "page_end": pc.page_end},
            )
            db.add(parent)
            db.flush()
            parent_id_map_by_index[parent_index] = parent.id

            for child_index, child_text in enumerate(pc.children):
                child = KnowledgeChunk(
                    item_id=item_id,
                    chunk_text=_chunk_content(child_text),
                    chunk_index=child_index,
                    chunk_type="child",
                    parent_id=parent.id,
                    extra_meta={
                        "page_start": _chunk_page_start(child_text),
                        "page_end": _chunk_page_end(child_text),
                    },
                )
                db.add(child)
                db.flush()
                child_position = (parent_index, child_index)
                child_id_map_by_position[child_position] = child.id
                child_parent_id_map[child_position] = parent.id

        item.summary = item_summary
        db.flush()
        db.commit()
        _report(progress, "store_mysql_chunks", len(child_texts), len(child_texts))

        _log_stage(item_id, "delete_es_chunks")
        _delete_es_chunks_by_item(item_id)

        _log_stage(item_id, "store_milvus", vectors=len(embeddings))
        _report(progress, "store_milvus", 0, len(embeddings))
        vector_rows = []
        child_embedding_index = 0
        for parent_index, pc in enumerate(parents):
            for child_index, _child_text in enumerate(pc.children):
                cid = child_id_map_by_position[(parent_index, child_index)]
                emb = embeddings[child_embedding_index]
                vector_rows.append({"chunk_id": cid, "item_id": item_id, "embedding": emb})
                child_embedding_index += 1
        delete_vectors_by_ids(old_child_chunk_ids)
        insert_vectors_batch(vector_rows)
        _report(progress, "store_milvus", len(vector_rows), len(embeddings))

        _log_stage(item_id, "index_es", parents=len(parents), children=len(child_texts))
        _report(progress, "index_es", 0, len(child_texts))
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
        _report(progress, "index_es", len(child_texts), len(child_texts))

        _log_stage(item_id, "commit")
        db.commit()

        user_id = (item.user_id if hasattr(item, "user_id") else None) or "default-user"
        _run_stage_a_for_item(db, item_id, user_id)

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
