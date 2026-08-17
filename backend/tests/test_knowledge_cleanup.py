from backend.app.models import (
    KnowledgeChunk,
    KnowledgeFile,
    KnowledgeItem,
    KnowledgeJob,
    KnowledgeTopic,
    PersonalAssetUnit,
)
from backend.app.models.entity import EntityMention, EntityRelation, KnowledgeEntity
from backend.app.utils.time import local_now


class FakeExternalIndex:
    def __init__(self, *, fail_once=False):
        self.fail_once = fail_once
        self.calls = []

    def delete_file(self, tenant_id, kb_uid, file_uid):
        self.calls.append((tenant_id, kb_uid, file_uid))
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("external delete failed")


class FakeStorage:
    def __init__(self):
        self.uris = {"local://tenant/kb/file/source.md"}

    def delete(self, uri):
        self.uris.discard(uri)

    def exists(self, uri):
        return uri in self.uris


def _seed_cleanup(db_session):
    topic = KnowledgeTopic(tenant_id="tenant-a", owner_user_id="alice", name="KB")
    db_session.add(topic)
    db_session.flush()
    item = KnowledgeItem(
        tenant_id="tenant-a", kb_uid=topic.kb_uid, title="Doc", content="body"
    )
    db_session.add(item)
    db_session.flush()
    file_row = KnowledgeFile(
        tenant_id="tenant-a",
        kb_uid=topic.kb_uid,
        file_uid="file-a",
        item_id=item.id,
        storage_uri="local://tenant/kb/file/source.md",
        original_filename="source.md",
        deleted_at=local_now(),
    )
    db_session.add(file_row)
    db_session.add(
        KnowledgeChunk(
            tenant_id="tenant-a",
            kb_uid=topic.kb_uid,
            file_uid=file_row.file_uid,
            item_id=item.id,
            generation="gen-a",
            chunk_text="chunk",
        )
    )
    job = KnowledgeJob(
        tenant_id="tenant-a",
        kb_uid=topic.kb_uid,
        file_uid=file_row.file_uid,
        idempotency_key="delete-file-a",
        job_type="delete",
        status="processing",
    )
    db_session.add(job)
    db_session.commit()
    return file_row, item, job


def test_cleanup_resumes_after_es_failure(db_session):
    from backend.app.services.knowledge_cleanup import KnowledgeCleanupService

    file_row, item, job = _seed_cleanup(db_session)
    milvus = FakeExternalIndex()
    es = FakeExternalIndex(fail_once=True)
    storage = FakeStorage()
    cleanup = KnowledgeCleanupService(db_session, milvus, es, storage)
    file_id = file_row.id
    item_id = item.id

    first = cleanup.run(file_row.file_uid, job_id=job.id)

    assert first.status == "failed"
    assert first.checkpoint == "milvus_deleted"
    assert milvus.calls == [("tenant-a", file_row.kb_uid, file_row.file_uid)]
    assert storage.exists(file_row.storage_uri) is True

    second = cleanup.run(file_row.file_uid, job_id=job.id)

    assert second.status == "succeeded"
    assert second.checkpoint == "rows_deleted"
    assert len(milvus.calls) == 1
    assert storage.exists(file_row.storage_uri) is False
    assert db_session.get(KnowledgeFile, file_id) is None
    assert db_session.get(KnowledgeItem, item_id) is None
    db_session.refresh(job)
    assert job.result["checkpoint"] == "rows_deleted"


def test_cleanup_graph_step_uses_scoped_document_facts_and_projects_delete(db_session):
    from backend.app.services.knowledge_cleanup import KnowledgeCleanupService

    file_row, item, job = _seed_cleanup(db_session)
    chunk = db_session.query(KnowledgeChunk).filter_by(file_uid=file_row.file_uid).one()
    entity = KnowledgeEntity(entity_type="concept", canonical_name="Scoped", normalized_key="scoped")
    db_session.add(entity)
    db_session.flush()
    own = EntityMention(entity_id=entity.id, source_kind="document_chunk", source_id=chunk.id,
                        item_id=item.id, chunk_id=chunk.id, surface_text="own", normalized_key="own")
    wrong_kind = EntityMention(entity_id=entity.id, source_kind="conversation", source_id=chunk.id,
                               item_id=item.id, chunk_id=chunk.id, surface_text="other", normalized_key="other")
    own_rel = EntityRelation(subject_entity_id=entity.id, predicate="mentions", object_literal="x",
                             source_kind="document_chunk", source_id=chunk.id)
    wrong_rel = EntityRelation(subject_entity_id=entity.id, predicate="mentions", object_literal="y",
                               source_kind="conversation", source_id=chunk.id)
    db_session.add_all([own, wrong_kind, own_rel, wrong_rel])
    db_session.commit()
    item_id, own_id, own_rel_id = item.id, own.id, own_rel.id
    wrong_kind_id, wrong_rel_id = wrong_kind.id, wrong_rel.id

    class Graph:
        calls = []
        def delete_item_sources_all_generations(self, tenant_id, kb_uid, item_id):
            self.calls.append((tenant_id, kb_uid, item_id))

    graph = Graph()
    result = KnowledgeCleanupService(db_session, FakeExternalIndex(), FakeExternalIndex(), FakeStorage(), graph_client=graph).run(
        file_row.file_uid, job_id=job.id
    )

    assert result.status == "succeeded"
    assert graph.calls == [("tenant-a", file_row.kb_uid, item_id)]
    assert db_session.get(EntityMention, own_id) is None
    assert db_session.get(EntityRelation, own_rel_id) is None
    assert db_session.get(EntityMention, wrong_kind_id) is not None
    assert db_session.get(EntityRelation, wrong_rel_id) is not None


def test_cleanup_graph_step_removes_personal_asset_unit_legacy_graph_facts(db_session):
    from backend.app.services.knowledge_cleanup import KnowledgeCleanupService
    from backend.app.services.personal_inbox import PERSONAL_ASSET_UNIT_SOURCE_KIND, PERSONAL_INBOX_SYSTEM_TYPE

    topic = KnowledgeTopic(
        tenant_id="tenant-a",
        owner_user_id="alice",
        user_id="alice",
        name="未归档知识",
        system_type=PERSONAL_INBOX_SYSTEM_TYPE,
    )
    db_session.add(topic)
    db_session.flush()
    unit = PersonalAssetUnit(
        id="unit-clean",
        user_id="alice",
        title="Unit Clean",
        content="Graph cleanup content",
        status="confirmed",
    )
    file_row = KnowledgeFile(
        tenant_id="tenant-a",
        user_id="alice",
        kb_uid=topic.kb_uid,
        topic_id=topic.id,
        file_uid="file-unit-clean",
        original_filename="unit.md",
        storage_uri="local://tenant/kb/file/source.md",
        source_kind=PERSONAL_ASSET_UNIT_SOURCE_KIND,
        source_id=unit.id,
        system_type=PERSONAL_INBOX_SYSTEM_TYPE,
        deleted_at=local_now(),
    )
    job = KnowledgeJob(
        tenant_id="tenant-a",
        kb_uid=topic.kb_uid,
        file_uid=file_row.file_uid,
        idempotency_key="delete-unit-clean",
        job_type="delete",
        status="processing",
    )
    entity = KnowledgeEntity(
        id="entity-unit-clean",
        user_id="alice",
        entity_type="concept",
        canonical_name="Unit Clean",
        normalized_key="unit-clean",
    )
    db_session.add_all([unit, file_row, job, entity])
    db_session.flush()
    mention = EntityMention(
        id="mention-unit-clean",
        entity_id=entity.id,
        source_kind=PERSONAL_ASSET_UNIT_SOURCE_KIND,
        source_id=unit.id,
        item_id=unit.id,
        surface_text="Unit Clean",
        normalized_key="unit-clean",
    )
    relation = EntityRelation(
        id="relation-unit-clean",
        subject_entity_id=entity.id,
        predicate="related_to",
        object_literal="cleanup",
        source_kind=PERSONAL_ASSET_UNIT_SOURCE_KIND,
        source_id=unit.id,
    )
    db_session.add_all([mention, relation])
    db_session.commit()

    class Graph:
        calls = []

        def delete_personal_asset_unit_graph(self, unit_id, *, user_id, entity_ids=None):
            self.calls.append((unit_id, user_id, tuple(entity_ids or ())))

    graph = Graph()
    result = KnowledgeCleanupService(
        db_session,
        FakeExternalIndex(),
        FakeExternalIndex(),
        FakeStorage(),
        graph_client=graph,
    ).run(file_row.file_uid, job_id=job.id)

    assert result.status == "succeeded"
    assert graph.calls == [("unit-clean", "alice", ("entity-unit-clean",))]
    assert db_session.get(EntityMention, "mention-unit-clean") is None
    assert db_session.get(EntityRelation, "relation-unit-clean") is None
    assert db_session.get(KnowledgeEntity, "entity-unit-clean") is None


def test_graph_failure_rolls_back_mysql_facts_and_keeps_es_checkpoint(db_session):
    from backend.app.services.knowledge_cleanup import KnowledgeCleanupService
    file_row, item, job = _seed_cleanup(db_session)
    chunk = db_session.query(KnowledgeChunk).filter_by(file_uid=file_row.file_uid).one()
    entity = KnowledgeEntity(entity_type="concept", canonical_name="Retry", normalized_key="retry")
    db_session.add(entity); db_session.flush()
    mention = EntityMention(entity_id=entity.id, source_kind="document_chunk", source_id=chunk.id,
                            item_id=item.id, chunk_id=chunk.id, surface_text="retry", normalized_key="retry")
    db_session.add(mention); db_session.commit()
    mention_id = mention.id

    class FailingGraph:
        def delete_item_sources_all_generations(self, tenant_id, kb_uid, item_id):
            raise RuntimeError("neo4j unavailable")

    cleanup = KnowledgeCleanupService(db_session, FakeExternalIndex(), FakeExternalIndex(), FakeStorage(), graph_client=FailingGraph())
    result = cleanup.run(file_row.file_uid, job_id=job.id)
    assert result.status == "failed"
    assert result.checkpoint == "es_deleted"
    assert db_session.get(EntityMention, mention_id) is not None


def test_reconciler_is_dry_run_by_default_and_apply_repairs_findings(db_session):
    from backend.app.services.knowledge_cleanup import KnowledgeReconciler

    job = KnowledgeJob(
        tenant_id="tenant-a",
        kb_uid="kb-a",
        file_uid="file-a",
        idempotency_key="queued-orphan",
        job_type="parse",
        status="queued",
    )
    db_session.add(job)
    db_session.commit()

    class FakeQueue:
        published = []

        def contains(self, job_id):
            return False

        def publish(self, job_id):
            self.published.append(job_id)

    class FakeArtifacts:
        removed = []

        def stale_generations(self, live_scopes, retention_before):
            return [("tenant-a", "kb-a", "old-gen")]

        def orphan_rows(self, live_scopes):
            return [("tenant-a", "missing-kb", "file-x", "gen-x")]

        def remove(self, finding):
            self.removed.append(finding)

    class FakeStaging:
        removed = []

        def stale_unreferenced(self, referenced_file_uids, older_than):
            return ["staging-file"]

        def remove_staging(self, identity):
            self.removed.append(identity)

    queue = FakeQueue()
    artifacts = FakeArtifacts()
    staging = FakeStaging()
    reconciler = KnowledgeReconciler(db_session, queue, [artifacts], staging)

    dry = reconciler.run()
    assert len(dry.findings) == 4
    assert queue.published == []
    assert artifacts.removed == []
    assert staging.removed == []

    applied = reconciler.run(apply=True)
    assert applied.applied == 4
    assert queue.published == [job.id]
    assert len(artifacts.removed) == 2
    assert staging.removed == ["staging-file"]


def test_reconciler_does_not_publish_queued_job_before_available_at(db_session):
    from datetime import timedelta
    from backend.app.services.knowledge_cleanup import KnowledgeReconciler

    now = local_now()
    job = KnowledgeJob(tenant_id="tenant-a", kb_uid="kb-a", file_uid="file-a",
                       idempotency_key="backoff", job_type="parse", status="queued",
                       available_at=now + timedelta(minutes=5))
    db_session.add(job)
    db_session.commit()

    class Queue:
        published = []
        def contains(self, job_id): return False
        def publish(self, job_id): self.published.append(job_id)
    class Staging:
        def stale_unreferenced(self, referenced, older_than): return []
    queue = Queue()
    result = KnowledgeReconciler(db_session, queue, [], Staging(), now=lambda: now).run(apply=True)
    assert result.findings == ()
    assert queue.published == []


def test_reconcile_command_is_dry_run_unless_apply_is_explicit():
    from backend.scripts.reconcile_knowledge_system import parse_args

    assert parse_args([]).apply is False
    assert parse_args(["--apply"]).apply is True


def test_reconcile_main_closes_owned_reconciler_and_database(monkeypatch):
    from backend.scripts import reconcile_knowledge_system as script
    events = []
    class Reconciler:
        def run(self, **kwargs):
            return type("Result", (), {"findings": (), "applied": 0})()
        def close(self): events.append("clients")
    class DB:
        def close(self): events.append("db")
    class Engine:
        def dispose(self): events.append("engine")
    monkeypatch.setattr(script, "create_engine", lambda *a, **k: Engine())
    monkeypatch.setattr(script, "sessionmaker", lambda bind: lambda: DB())
    monkeypatch.setattr(script, "build_reconciler", lambda db: Reconciler())
    assert script.main([]) == 0
    assert events == ["clients", "db", "engine"]


def test_legacy_milvus_inventory_skips_age_cleanup_but_finds_orphans():
    from datetime import timedelta
    from backend.scripts.reconcile_knowledge_system import MilvusInventory
    class Iterator:
        def __init__(self): self.done = False
        def next(self):
            if self.done: return []
            self.done = True
            return [{"tenant_id": "t", "kb_uid": "kb", "file_uid": "f", "generation": "g"}]
        def close(self): pass
    class Collection:
        schema = type("Schema", (), {"fields": [type("F", (), {"name": n})() for n in ("tenant_id", "kb_uid", "file_uid", "generation")]})()
        def query_iterator(self, **kwargs):
            assert "indexed_at" not in kwargs["output_fields"]
            return Iterator()
    inventory = MilvusInventory(Collection(), active=set())
    cutoff = local_now() - timedelta(days=7)
    assert inventory.stale_generations(set(), cutoff) == []
    assert inventory.orphan_rows(set()) == [("t", "kb", "f", "g")]
