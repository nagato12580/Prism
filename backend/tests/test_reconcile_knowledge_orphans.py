from backend.app.models import KnowledgeChunk, KnowledgeItem


def test_reconcile_knowledge_orphans_cleans_es_and_item_level_artifacts(db_session, monkeypatch):
    from backend.scripts import reconcile_knowledge_orphans as script

    live_item = KnowledgeItem(id="live-item", tenant_id="tenant-a", kb_uid="kb-a", title="Live", user_id="default-user")
    live_chunk = KnowledgeChunk(id="live-chunk", tenant_id="tenant-a", kb_uid="kb-a", file_uid="file-live", item_id="live-item", chunk_text="live", chunk_type="child")
    db_session.add_all([live_item, live_chunk])
    db_session.commit()

    scanned = [
        {"_id": "live-doc", "_source": {"tenant_id": "tenant-a", "kb_uid": "kb-a", "item_id": "live-item", "chunk_id": "live-chunk"}},
        {"_id": "stale-doc", "_source": {"tenant_id": "tenant-a", "kb_uid": "kb-a", "item_id": "missing-item", "chunk_id": "missing-chunk"}},
    ]
    bulk_actions = []
    milvus_deleted = []
    graph_deleted = []

    monkeypatch.setattr(script.helpers, "scan", lambda *args, **kwargs: iter(scanned))
    monkeypatch.setattr(
        script.helpers,
        "bulk",
        lambda _es, actions, refresh=None: bulk_actions.extend(actions) or (len(actions), []),
    )
    monkeypatch.setattr(script, "delete_vectors_by_item", lambda item_id: milvus_deleted.append(item_id))

    class _FakeGraph:
        def delete_item_sources_all_generations(self, tenant_id, kb_uid, item_id):
            graph_deleted.append((tenant_id, kb_uid, item_id))

        def close(self):
            pass

    monkeypatch.setattr(script, "GraphClient", lambda: _FakeGraph())

    stats = script.reconcile_knowledge_orphans(db_session, es=object())

    assert stats["scanned_es_docs"] == 2
    assert stats["deleted_es_docs"] == 1
    assert bulk_actions == [{"_op_type": "delete", "_index": script.CHUNKS_INDEX, "_id": "stale-doc"}]
    assert milvus_deleted == ["missing-item"]
    assert graph_deleted == [("tenant-a", "kb-a", "missing-item")]


def test_reconcile_knowledge_orphans_only_deletes_stale_chunk_doc_for_live_item(db_session, monkeypatch):
    from backend.scripts import reconcile_knowledge_orphans as script

    live_item = KnowledgeItem(id="live-item", tenant_id="tenant-a", kb_uid="kb-a", title="Live", user_id="default-user")
    live_chunk = KnowledgeChunk(id="live-chunk", tenant_id="tenant-a", kb_uid="kb-a", file_uid="file-live", item_id="live-item", chunk_text="live", chunk_type="child")
    db_session.add_all([live_item, live_chunk])
    db_session.commit()

    scanned = [
        {"_id": "stale-doc", "_source": {"tenant_id": "tenant-a", "kb_uid": "kb-a", "item_id": "live-item", "chunk_id": "missing-chunk"}},
    ]
    bulk_actions = []
    milvus_deleted = []
    graph_deleted = []

    monkeypatch.setattr(script.helpers, "scan", lambda *args, **kwargs: iter(scanned))
    monkeypatch.setattr(
        script.helpers,
        "bulk",
        lambda _es, actions, refresh=None: bulk_actions.extend(actions) or (len(actions), []),
    )
    monkeypatch.setattr(script, "delete_vectors_by_item", lambda item_id: milvus_deleted.append(item_id))

    class _FakeGraph:
        def delete_item_sources_all_generations(self, tenant_id, kb_uid, item_id):
            graph_deleted.append((tenant_id, kb_uid, item_id))

        def close(self):
            pass

    monkeypatch.setattr(script, "GraphClient", lambda: _FakeGraph())

    stats = script.reconcile_knowledge_orphans(db_session, es=object())

    assert stats["deleted_es_docs"] == 1
    assert bulk_actions == [{"_op_type": "delete", "_index": script.CHUNKS_INDEX, "_id": "stale-doc"}]
    assert milvus_deleted == []
    assert graph_deleted == []
