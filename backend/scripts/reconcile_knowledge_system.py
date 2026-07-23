"""Dry-run-first reconciliation for durable knowledge artifacts."""
import argparse
import json
from datetime import datetime
from pathlib import Path

from elasticsearch import Elasticsearch, helpers
from pymilvus import Collection, connections, utility
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.models import KnowledgeJob, KnowledgeTopic
from backend.app.services.knowledge_cleanup import KnowledgeReconciler
from backend.app.storage.files import LocalFileStorage
from engine.app.config import settings
from engine.app.indexing.es_index import V2_INDEX_NAME
from engine.app.indexing.milvus_index import _connect, _literal
from engine.app.jobs import redis_queue


class QueueInventory:
    def __init__(self, db, client):
        self.db = db
        self.client = client

    def contains(self, job_id):
        for queue in (
            settings.KNOWLEDGE_INGEST_QUEUE,
            settings.KNOWLEDGE_GOVERNANCE_QUEUE,
        ):
            for raw in self.client.lrange(queue, 0, -1):
                try:
                    if json.loads(raw).get("job_id") == job_id:
                        return True
                except (TypeError, ValueError):
                    continue
        return False

    def publish(self, job_id):
        job_type = self.db.query(KnowledgeJob.job_type).filter_by(id=job_id).scalar()
        queue = (
            settings.KNOWLEDGE_GOVERNANCE_QUEUE
            if job_type == "governance"
            else settings.KNOWLEDGE_INGEST_QUEUE
        )
        redis_queue.push_job(self.client, queue, job_id)


def _is_old(value, cutoff):
    if not value:
        return False
    try:
        return datetime.fromisoformat(value).replace(tzinfo=None) < cutoff.replace(tzinfo=None)
    except (TypeError, ValueError):
        return False


class ElasticsearchInventory:
    def __init__(self, client, active):
        self.client = client
        self.active = active

    def _rows(self):
        if not self.client.indices.exists(index=V2_INDEX_NAME):
            return []
        return [hit.get("_source") or {} for hit in helpers.scan(
            self.client, index=V2_INDEX_NAME, query={"query": {"match_all": {}}}
        )]

    def stale_generations(self, live_scopes, retention_before):
        generations = {}
        for row in self._rows():
            key = (row.get("tenant_id"), row.get("kb_uid"), row.get("generation"))
            generations.setdefault(key, []).append(row.get("indexed_at"))
        return [
            key for key, dates in generations.items()
            if key not in self.active and dates and all(_is_old(date, retention_before) for date in dates)
        ]

    def orphan_rows(self, live_scopes):
        return sorted({
            (row.get("tenant_id"), row.get("kb_uid"), row.get("file_uid"), row.get("generation"))
            for row in self._rows()
            if (row.get("tenant_id"), row.get("kb_uid"), row.get("file_uid"), row.get("generation"))
            not in live_scopes
        })

    def remove(self, identity):
        fields = ("tenant_id", "kb_uid", "generation") if len(identity) == 3 else (
            "tenant_id", "kb_uid", "file_uid", "generation"
        )
        values = dict(zip(fields, identity, strict=True))
        self.client.delete_by_query(
            index=V2_INDEX_NAME,
            routing=values["kb_uid"],
            refresh=True,
            query={"bool": {"filter": [{"term": {key: value}} for key, value in values.items()]}},
        )


class MilvusInventory:
    def __init__(self, collection, active):
        self.collection = collection
        self.active = active

    def _rows(self):
        available = {field.name for field in self.collection.schema.fields}
        output_fields = [
            field for field in ("tenant_id", "kb_uid", "file_uid", "generation", "indexed_at")
            if field in available
        ]
        iterator = self.collection.query_iterator(
            batch_size=1000,
            expr='tenant_id != ""',
            output_fields=output_fields,
        )
        rows = []
        try:
            while batch := iterator.next():
                rows.extend(batch)
        finally:
            iterator.close()
        return rows

    def stale_generations(self, live_scopes, retention_before):
        generations = {}
        for row in self._rows():
            key = (row["tenant_id"], row["kb_uid"], row["generation"])
            generations.setdefault(key, []).append(row.get("indexed_at"))
        return [key for key, dates in generations.items() if key not in self.active and dates and all(
            date is not None and _is_old(date, retention_before) for date in dates
        )]

    def orphan_rows(self, live_scopes):
        return sorted({
            (row["tenant_id"], row["kb_uid"], row["file_uid"], row["generation"])
            for row in self._rows()
            if (row["tenant_id"], row["kb_uid"], row["file_uid"], row["generation"])
            not in live_scopes
        })

    def remove(self, identity):
        fields = ("tenant_id", "kb_uid", "generation") if len(identity) == 3 else (
            "tenant_id", "kb_uid", "file_uid", "generation"
        )
        expr = " and ".join(
            f'{key} == "{_literal(value)}"' for key, value in zip(fields, identity, strict=True)
        )
        self.collection.delete(expr, timeout=15)
        self.collection.flush(timeout=15)


def build_reconciler(db):
    active = {
        (topic.tenant_id, topic.kb_uid, topic.active_index_generation)
        for topic in db.query(KnowledgeTopic).filter(KnowledgeTopic.deleted_at.is_(None)).all()
        if topic.active_index_generation
    }
    es_client = Elasticsearch([settings.ES_HOST], request_timeout=15)
    queue = None
    try:
        artifacts = [ElasticsearchInventory(es_client, active)]
        _connect(settings.MILVUS_HOST, settings.MILVUS_PORT)
        for collection_name in utility.list_collections():
            if collection_name.startswith("prism_kb_"):
                artifacts.append(MilvusInventory(Collection(collection_name), active))
        queue = QueueInventory(db, redis_queue.redis_client())
    except Exception:
        es_client.close()
        if queue is not None:
            queue.client.close()
        connections.disconnect("default")
        raise
    reconciler = KnowledgeReconciler(
        db,
        queue,
        artifacts,
        LocalFileStorage(Path(settings.KNOWLEDGE_STORAGE_ROOT)),
    )
    reconciler.close = lambda: (
        es_client.close(), queue.client.close(), connections.disconnect("default")
    )
    return reconciler


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Reconcile knowledge-system drift")
    parser.add_argument("--apply", action="store_true", help="apply discovered repairs")
    parser.add_argument("--retention-days", type=int, default=7)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
    db = sessionmaker(bind=engine)()
    reconciler = build_reconciler(db)
    try:
        result = reconciler.run(
            apply=args.apply, retention_days=args.retention_days
        )
    finally:
        reconciler.close()
        db.close()
        engine.dispose()
    print(json.dumps({"dry_run": not args.apply, "findings": len(result.findings), "applied": result.applied}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
