import logging

from sqlalchemy.orm import Session

from backend.app.models import EntityMention, EntityRelation, KnowledgeChunk, KnowledgeItem
from backend.app.services.graph_client import GraphClient
from backend.app.services.knowledge_governance import clear_document_item_governance
from engine.app.es_client import CHUNKS_INDEX, get_es
from engine.app.milvus_client import delete_vectors_by_item


logger = logging.getLogger("uvicorn.error")


def delete_es_chunks_by_item(item_id: str) -> None:
    if not item_id:
        return

    es = get_es()
    response = es.delete_by_query(
        index=CHUNKS_INDEX,
        body={"query": {"term": {"item_id": item_id}}},
        refresh=True,
    )
    body = getattr(response, "body", response)
    getter = body.get if hasattr(body, "get") else None
    timed_out = getter("timed_out", False) if getter else getattr(body, "timed_out", False)
    failures = getter("failures", None) if getter else getattr(body, "failures", None)
    if timed_out or failures:
        raise RuntimeError(f"delete_es_chunks failed item_id={item_id} timed_out={timed_out} failures={failures}")


def purge_item_derived_artifacts(db: Session, item_id: str) -> None:
    if not item_id:
        return

    item = db.query(KnowledgeItem).filter_by(id=item_id).one_or_none()
    if item is None:
        return
    chunk_ids = [
        chunk_id
        for (chunk_id,) in (
            db.query(KnowledgeChunk.id)
            .filter(KnowledgeChunk.item_id == item_id)
            .all()
        )
    ]

    clear_document_item_governance(db, item_id)

    if chunk_ids:
        db.query(EntityRelation).filter(
            EntityRelation.source_kind == "document_chunk",
            EntityRelation.source_id.in_(chunk_ids),
        ).delete(synchronize_session=False)
        db.query(EntityMention).filter(
            EntityMention.item_id == item_id,
            EntityMention.source_kind == "document_chunk",
        ).delete(synchronize_session=False)
        db.flush()

    delete_vectors_by_item(item_id)
    delete_es_chunks_by_item(item_id)

    graph = GraphClient()
    try:
        graph.delete_item_sources_all_generations(item.tenant_id, item.kb_uid, item_id)
    finally:
        graph.close()

    logger.info(
        "[derived_cleanup] purged item_id=%s chunk_count=%s",
        item_id,
        len(chunk_ids),
    )
