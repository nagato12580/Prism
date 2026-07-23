import io
import json
import zipfile
import pytest

from backend.app.models import (
    EvaluationDataset,
    EvaluationDatasetItem,
    KnowledgeChunk,
    KnowledgeFile,
    KnowledgeItem,
    KnowledgeTopic,
    KnowledgeEntity,
)
from backend.app.models.entity import EntityMention, EntityRelation


def _topic(db, **kwargs):
    values = {
        "tenant_id": "tenant-a",
        "owner_user_id": "alice",
        "name": "Safe KB",
        "active_index_generation": "index-7",
        "active_graph_generation": "graph-3",
    }
    values.update(kwargs)
    topic = KnowledgeTopic(**values)
    db.add(topic)
    db.commit()
    return topic


def _existing_map():
    return {
        "status": "ready",
        "nodes": [
            {
                "id": "root",
                "title": "Root",
                "children": [
                    {"id": "file-a", "file_uid": "file-a", "title": "A", "children": []},
                    {"id": "file-b", "file_uid": "file-b", "title": "B", "children": []},
                ],
            }
        ],
    }


def _flatten_file_uids(nodes):
    result = []
    for node in nodes:
        if node.get("file_uid"):
            result.append(node["file_uid"])
        result.extend(_flatten_file_uids(node.get("children", [])))
    return result


def test_mindmap_delete_only_update_does_not_call_llm(monkeypatch):
    from engine.app.knowledge.enrichment import apply_mindmap_diff

    monkeypatch.setattr(
        "engine.app.knowledge.enrichment.call_llm",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("LLM must not run")),
    )
    updated = apply_mindmap_diff(_existing_map(), added=[], deleted=["file-a"], renamed=[])

    assert _flatten_file_uids(updated["nodes"]) == ["file-b"]


def test_mindmap_rename_only_is_deterministic(monkeypatch):
    from engine.app.knowledge.enrichment import apply_mindmap_diff

    monkeypatch.setattr(
        "engine.app.knowledge.enrichment.call_llm",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("LLM must not run")),
    )
    updated = apply_mindmap_diff(
        _existing_map(),
        added=[],
        deleted=[],
        renamed=[{"file_uid": "file-b", "title": "Renamed", "relative_path": "guides/renamed.md"}],
    )

    leaf = updated["nodes"][0]["children"][1]
    assert leaf["file_uid"] == "file-b"
    assert leaf["title"] == "Renamed"
    assert leaf["relative_path"] == "guides/renamed.md"


def test_file_change_marks_questions_stale_and_delete_updates_mindmap(db_session):
    from engine.app.knowledge.enrichment import mark_enrichment_stale

    topic = _topic(db_session)
    topic.mindmap = {**_existing_map(), "version": 2}
    topic.mindmap_version = 2
    topic.sample_questions = {
        "status": "ready",
        "version": 3,
        "questions": ["How does A work?"],
        "index_generation": "index-7",
    }
    topic.sample_questions_version = 3
    db_session.commit()

    mark_enrichment_stale(
        db_session,
        topic.kb_uid,
        reason="file_deleted",
        deleted_file_uids=["file-a"],
    )
    db_session.refresh(topic)

    assert topic.sample_questions["status"] == "stale"
    assert topic.sample_questions["stale_reason"] == "file_deleted"
    assert topic.sample_questions["input_revision"] == 1
    assert _flatten_file_uids(topic.mindmap["nodes"]) == ["file-b"]
    assert topic.mindmap["input_revision"] == 1
    assert topic.mindmap_version == 3


def test_input_change_creates_stale_envelopes_and_revisions_are_monotonic(db_session):
    from engine.app.knowledge.enrichment import mark_enrichment_stale

    topic = _topic(db_session)
    assert topic.mindmap is None
    assert topic.sample_questions is None

    mark_enrichment_stale(db_session, topic.kb_uid, reason="file_added")
    db_session.refresh(topic)

    assert topic.mindmap == {
        "status": "stale",
        "stale_reason": "file_added",
        "version": 0,
        "input_revision": 1,
        "nodes": [],
    }
    assert topic.sample_questions == {
        "status": "stale",
        "stale_reason": "file_added",
        "version": 0,
        "input_revision": 1,
        "questions": [],
    }

    mark_enrichment_stale(db_session, topic.kb_uid, reason="file_content_changed")
    db_session.refresh(topic)

    assert topic.mindmap["input_revision"] == 2
    assert topic.sample_questions["input_revision"] == 2


def test_generation_store_preserves_current_input_revision(db_session):
    from engine.app.knowledge.enrichment import store_mindmap, store_sample_questions

    topic = _topic(db_session)
    topic.mindmap = {"status": "generating", "input_revision": 8, "nodes": []}
    topic.sample_questions = {"status": "generating", "input_revision": 13, "questions": []}
    db_session.commit()

    mindmap = store_mindmap(
        db_session,
        topic,
        nodes=[],
        index_generation="index-7",
        graph_generation="graph-3",
        model="model",
        prompt_version="v1",
    )
    questions = store_sample_questions(
        db_session,
        topic,
        questions=["Still current?"],
        index_generation="index-7",
        graph_generation="graph-3",
        model="model",
        prompt_version="v1",
    )

    assert mindmap["input_revision"] == 8
    assert questions["input_revision"] == 13


def test_generation_snapshots_are_versioned(db_session):
    from engine.app.knowledge.enrichment import store_mindmap, store_sample_questions

    topic = _topic(db_session)
    first = store_mindmap(
        db_session,
        topic,
        nodes=_existing_map()["nodes"],
        index_generation="index-7",
        graph_generation="graph-3",
        model="model-public-name",
        prompt_version="mindmap-v1",
    )
    second = store_mindmap(
        db_session,
        topic,
        nodes=_existing_map()["nodes"],
        index_generation="index-8",
        graph_generation="graph-4",
        model="model-public-name",
        prompt_version="mindmap-v2",
    )
    questions = store_sample_questions(
        db_session,
        topic,
        questions=["What changed?"],
        index_generation="index-8",
        graph_generation="graph-4",
        model="model-public-name",
        prompt_version="questions-v1",
    )

    assert first["version"] == 1
    assert second["version"] == 2
    assert second["index_generation"] == "index-8"
    assert second["graph_generation"] == "graph-4"
    assert second["model"] == "model-public-name"
    assert second["prompt_version"] == "mindmap-v2"
    assert questions["version"] == 1
    assert questions["index_generation"] == "index-8"


def test_active_index_generation_change_marks_questions_stale(db_session):
    from engine.app.indexing.publisher import activate_generation

    topic = _topic(db_session)
    topic.sample_questions = {
        "status": "ready",
        "version": 1,
        "questions": ["Old generation question?"],
        "index_generation": "index-7",
    }
    topic.sample_questions_version = 1
    db_session.commit()

    activate_generation(db_session, topic.kb_uid, "index-8", expected_old="index-7")
    db_session.refresh(topic)

    assert topic.sample_questions["status"] == "stale"
    assert topic.sample_questions["stale_reason"] == "active_index_generation_changed"
    assert topic.sample_questions["input_revision"] == 1
    assert topic.mindmap["status"] == "stale"
    assert topic.mindmap["input_revision"] == 1


def test_active_graph_generation_helper_marks_both_enrichments_stale(db_session):
    from engine.app.knowledge.enrichment import activate_graph_generation

    topic = _topic(db_session)
    topic.mindmap = {"status": "ready", "version": 1, "nodes": []}
    topic.sample_questions = {"status": "ready", "version": 1, "questions": []}
    db_session.commit()

    activate_graph_generation(db_session, topic.kb_uid, "graph-4", expected_old="graph-3")
    db_session.refresh(topic)

    assert topic.active_graph_generation == "graph-4"
    assert topic.mindmap["status"] == "stale"
    assert topic.sample_questions["status"] == "stale"
    assert topic.mindmap["input_revision"] == 1
    assert topic.sample_questions["input_revision"] == 1


def test_enrichment_llm_propagates_hard_timeout_and_disables_retries(monkeypatch):
    from engine.app.knowledge.enrichment import call_llm

    seen = {}
    def fake_chat(messages, **kwargs):
        seen.update(kwargs)
        return '{"questions":["Bounded?"]}'
    monkeypatch.setattr("engine.app.llm.client.chat", fake_chat)

    call_llm("sample_questions", {"representative_chunks": []}, model="m", prompt_version="v1")

    assert seen["timeout_seconds"] == 90
    assert seen["max_retries"] == 0


def test_openai_chat_applies_per_request_timeout_and_zero_sdk_retries(monkeypatch):
    import engine.app.llm.client as llm_client

    seen = {}
    class Completions:
        def create(self, **kwargs):
            return type("Response", (), {"choices": [type("Choice", (), {"message": type("Message", (), {"content": "ok"})()})()]})()
    class Client:
        chat = type("Chat", (), {"completions": Completions()})()
        def with_options(self, **kwargs):
            seen.update(kwargs)
            return self
    monkeypatch.setattr(llm_client, "_get_client", lambda: Client())

    assert llm_client.chat([], model="m", timeout_seconds=90, max_retries=0) == "ok"
    assert seen == {"timeout": 90, "max_retries": 0}


def test_representative_chunks_are_stratified_and_strictly_bounded():
    from engine.app.knowledge.enrichment import select_representative_chunks

    chunks = [
        {
            "chunk_uid": f"a-{index}",
            "file_uid": "file-a",
            "title_path": ["Guide", f"Section {index}"],
            "text": "a" * 80,
        }
        for index in range(8)
    ] + [
        {
            "chunk_uid": "b-0",
            "file_uid": "file-b",
            "title_path": ["Reference", "API"],
            "text": "b" * 80,
        },
        {
            "chunk_uid": "c-0",
            "file_uid": "file-c",
            "title_path": ["Tutorial"],
            "text": "c" * 80,
        },
    ]

    selected = select_representative_chunks(chunks, max_chunks=3, max_chars=150, per_chunk_chars=60)

    assert {row["file_uid"] for row in selected} == {"file-a", "file-b", "file-c"}
    assert len(selected) == 3
    assert sum(len(row["summary"]) for row in selected) <= 150
    assert all(len(row["summary"]) <= 60 for row in selected)


def test_safe_export_has_only_relative_bounded_entries_and_no_secrets_or_vectors(db_session):
    from engine.app.knowledge.enrichment import build_knowledge_export

    topic = _topic(
        db_session,
        name="C:\\private\\Safe KB",
        embedding_profile={"model": "embed-public", "api_key": "DO-NOT-EXPORT"},
        parser_config={"preset": "default", "provider_payload": {"token": "SECRET"}},
        retrieval_config={"top_k": 8, "dense_weight": float("inf"), "internal_url": "http://internal.invalid"},
    )
    item = KnowledgeItem(
        tenant_id=topic.tenant_id,
        kb_uid=topic.kb_uid,
        title="Manual",
        normalized_markdown="# Parsed manual\nSafe text.",
        source_ref="C:\\private\\source.md",
    )
    db_session.add(item)
    db_session.flush()
    file_row = KnowledgeFile(
        tenant_id=topic.tenant_id,
        kb_uid=topic.kb_uid,
        topic_id=topic.id,
        item_id=item.id,
        file_uid="public-file-uid",
        original_filename="../unsafe.md",
        relative_path="../private/unsafe.md",
        storage_uri="file:///C:/private/storage/object",
        file_path="C:\\private\\storage\\object",
        media_type="document",
    )
    db_session.add(file_row)
    entity = KnowledgeEntity(
        user_id="alice", entity_type="concept", canonical_name="Safe Entity",
        normalized_key="safe-entity",
    )
    db_session.add(entity)
    db_session.flush()
    db_session.add(EntityMention(
        entity_id=entity.id, source_kind="document_item", source_id=item.id,
        item_id=item.id, surface_text="Safe Entity", normalized_key="safe-entity",
    ))
    db_session.add(EntityRelation(
        subject_entity_id=entity.id, predicate="documents", object_literal="Safe",
        source_kind="document_item", source_id=item.id, evidence_span="Safe evidence",
        extra_meta={"provider_payload": {"api_key": "NESTED-SECRET"}},
    ))
    dataset = EvaluationDataset(
        tenant_id=topic.tenant_id,
        kb_uid=topic.kb_uid,
        name="Regression",
        created_by="alice",
    )
    db_session.add(dataset)
    db_session.flush()
    db_session.add(
        EvaluationDatasetItem(
            dataset_id=dataset.id,
            tenant_id=topic.tenant_id,
            kb_uid=topic.kb_uid,
            ordinal=0,
            query="What is safe?",
            gold_chunk_uids=["chunk-public"],
            gold_answer="Safe.",
        )
    )
    db_session.commit()

    payload = build_knowledge_export(
        db_session, topic, max_files=10, max_entries=30,
        max_total_bytes=200_000, spool_max_size=64,
    )

    assert payload._rolled is True
    with zipfile.ZipFile(payload) as archive:
        names = archive.namelist()
        assert "manifest.json" in names
        assert "config.json" in names
        assert "files.json" in names
        assert any(name.startswith("documents/") and name.endswith(".md") for name in names)
        assert any(name.startswith("evaluation/") and name.endswith(".jsonl") for name in names)
        assert "graph/entities.jsonl" in names
        assert "graph/relations.jsonl" in names
        for info in archive.infolist():
            assert not info.filename.startswith(("/", "\\"))
            assert ".." not in info.filename.split("/")
            assert info.file_size <= 200_000
        exported = b"\n".join(archive.read(name) for name in names).decode("utf-8")

    lowered = exported.lower()
    assert "do-not-export" not in lowered
    assert "secret" not in lowered
    assert "api_key" not in lowered
    assert "provider_payload" not in lowered
    assert "infinity" not in lowered
    assert "storage_uri" not in lowered
    assert "file_path" not in lowered
    assert "c:\\private" not in lowered
    assert '"name":"safe kb"' in lowered
    assert '"vector"' not in lowered
    payload.close()


def test_export_streams_queries_without_all_and_rejects_oversized_field(db_session, monkeypatch):
    from sqlalchemy.orm import Query
    from engine.app.knowledge.enrichment import build_knowledge_export

    topic = _topic(db_session)
    item = KnowledgeItem(
        tenant_id=topic.tenant_id, kb_uid=topic.kb_uid, title="Huge",
        normalized_markdown="x" * 5000,
    )
    db_session.add(item)
    db_session.flush()
    db_session.add(KnowledgeFile(
        tenant_id=topic.tenant_id, kb_uid=topic.kb_uid, topic_id=topic.id,
        item_id=item.id, file_uid="huge-file", original_filename="huge.md", media_type="document",
    ))
    db_session.commit()
    monkeypatch.setattr(Query, "all", lambda self: (_ for _ in ()).throw(AssertionError("all() is forbidden")))

    with pytest.raises(ValueError, match="entry budget"):
        build_knowledge_export(db_session, topic, max_entry_bytes=1024, max_total_bytes=20_000)
