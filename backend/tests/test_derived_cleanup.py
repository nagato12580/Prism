from backend.app.models import EntityMention, EntityRelation, KnowledgeChunk, KnowledgeEntity, KnowledgeItem
from backend.app.models.entity import compute_relation_key


def test_purge_item_derived_artifacts_deletes_document_entity_rows_and_calls_external_cleanup(db_session, monkeypatch):
    from backend.app.services import derived_cleanup as cleanup

    item = KnowledgeItem(id="item-1", tenant_id="tenant-a", kb_uid="kb-a", title="Doc", user_id="default-user")
    chunk = KnowledgeChunk(id="chunk-1", tenant_id="tenant-a", kb_uid="kb-a", file_uid="file-a", item_id="item-1", chunk_text="hello", chunk_type="child")
    entity_a = KnowledgeEntity(
        id="entity-a",
        user_id="default-user",
        entity_type="concept",
        canonical_name="Alpha",
        normalized_key="alpha",
    )
    entity_b = KnowledgeEntity(
        id="entity-b",
        user_id="default-user",
        entity_type="concept",
        canonical_name="Beta",
        normalized_key="beta",
    )
    mention = EntityMention(
        entity_id="entity-a",
        source_kind="document_chunk",
        source_id="chunk-1",
        item_id="item-1",
        chunk_id="chunk-1",
        surface_text="Alpha",
        normalized_key="alpha",
    )
    relation = EntityRelation(
        subject_entity_id="entity-a",
        predicate="related_to",
        object_entity_id="entity-b",
        source_kind="document_chunk",
        source_id="chunk-1",
        relation_key=compute_relation_key("entity-a", "related_to", "entity-b", None, "document_chunk", "chunk-1"),
    )
    db_session.add_all([item, chunk, entity_a, entity_b, mention, relation])
    db_session.commit()

    deleted_vectors = []
    deleted_es = []
    deleted_graph = []
    cleared_governance = []

    monkeypatch.setattr(cleanup, "delete_vectors_by_item", lambda item_id: deleted_vectors.append(item_id))
    monkeypatch.setattr(cleanup, "delete_es_chunks_by_item", lambda item_id: deleted_es.append(item_id))
    monkeypatch.setattr(cleanup, "clear_document_item_governance", lambda db, item_id: cleared_governance.append(item_id))

    class _FakeGraph:
        def delete_item_sources_all_generations(self, tenant_id, kb_uid, item_id):
            deleted_graph.append((tenant_id, kb_uid, item_id))

        def close(self):
            pass

    monkeypatch.setattr(cleanup, "GraphClient", lambda: _FakeGraph())

    cleanup.purge_item_derived_artifacts(db_session, "item-1")

    assert cleared_governance == ["item-1"]
    assert deleted_vectors == ["item-1"]
    assert deleted_es == ["item-1"]
    assert deleted_graph == [("tenant-a", "kb-a", "item-1")]
    assert db_session.query(EntityMention).count() == 0
    assert db_session.query(EntityRelation).count() == 0


def test_purge_item_derived_artifacts_handles_item_without_chunks(db_session, monkeypatch):
    from backend.app.services import derived_cleanup as cleanup

    item = KnowledgeItem(id="item-2", tenant_id="tenant-a", kb_uid="kb-a", title="Doc", user_id="default-user")
    db_session.add(item)
    db_session.commit()

    deleted_vectors = []
    deleted_es = []
    deleted_graph = []

    monkeypatch.setattr(cleanup, "delete_vectors_by_item", lambda item_id: deleted_vectors.append(item_id))
    monkeypatch.setattr(cleanup, "delete_es_chunks_by_item", lambda item_id: deleted_es.append(item_id))
    monkeypatch.setattr(cleanup, "clear_document_item_governance", lambda db, item_id: None)

    class _FakeGraph:
        def delete_item_sources_all_generations(self, tenant_id, kb_uid, item_id):
            deleted_graph.append((tenant_id, kb_uid, item_id))

        def close(self):
            pass

    monkeypatch.setattr(cleanup, "GraphClient", lambda: _FakeGraph())

    cleanup.purge_item_derived_artifacts(db_session, "item-2")

    assert deleted_vectors == ["item-2"]
    assert deleted_es == ["item-2"]
    assert deleted_graph == [("tenant-a", "kb-a", "item-2")]
