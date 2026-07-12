import argparse
from collections.abc import Iterable

from elasticsearch import helpers
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.config import settings
from backend.app.models import KnowledgeChunk, KnowledgeItem
from backend.app.services.graph_client import GraphClient
from engine.app.es_client import CHUNKS_INDEX, get_es
from engine.app.milvus_client import delete_vectors_by_item


def _iter_es_chunk_docs(es) -> Iterable[dict]:
    return helpers.scan(
        es,
        index=CHUNKS_INDEX,
        query={"_source": ["item_id", "chunk_id"], "query": {"match_all": {}}},
    )


def _delete_es_docs(es, doc_ids: list[str]) -> int:
    if not doc_ids:
        return 0
    actions = [{"_op_type": "delete", "_index": CHUNKS_INDEX, "_id": doc_id} for doc_id in doc_ids]
    helpers.bulk(es, actions, refresh=True)
    return len(actions)


def reconcile_knowledge_orphans(db: Session, *, es=None) -> dict[str, int]:
    es = es or get_es()

    live_item_ids = {row[0] for row in db.query(KnowledgeItem.id).all()}
    live_chunk_ids = {row[0] for row in db.query(KnowledgeChunk.id).all()}

    stale_doc_ids: list[str] = []
    missing_item_ids: set[str] = set()
    scanned = 0

    for doc in _iter_es_chunk_docs(es):
        scanned += 1
        source = doc.get("_source") or {}
        item_id = source.get("item_id")
        chunk_id = source.get("chunk_id")
        item_missing = not item_id or item_id not in live_item_ids
        chunk_missing = not chunk_id or chunk_id not in live_chunk_ids
        if not item_missing and not chunk_missing:
            continue
        stale_doc_ids.append(doc.get("_id"))
        if item_missing and item_id:
            missing_item_ids.add(item_id)

    deleted_es_docs = _delete_es_docs(es, [doc_id for doc_id in stale_doc_ids if doc_id])

    graph = GraphClient()
    try:
        for item_id in sorted(missing_item_ids):
            delete_vectors_by_item(item_id)
            graph.delete_item_sources(item_id)
    finally:
        graph.close()

    return {
        "scanned_es_docs": scanned,
        "deleted_es_docs": deleted_es_docs,
        "deleted_item_level_artifacts": len(missing_item_ids),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reconcile orphaned knowledge artifacts in ES/Milvus/graph.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    parse_args(argv)
    engine = create_engine(settings.DATABASE_URL)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        stats = reconcile_knowledge_orphans(db)
    finally:
        db.close()
    print(
        "reconciled knowledge orphans "
        f"scanned_es_docs={stats['scanned_es_docs']} "
        f"deleted_es_docs={stats['deleted_es_docs']} "
        f"deleted_item_level_artifacts={stats['deleted_item_level_artifacts']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
