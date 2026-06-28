from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import pytest

from backend.app.database import Base
from backend.app.models import (
    CanonicalKnowledgePoint,
    KnowledgeChunk,
    KnowledgeItem,
    PKUCanonicalLink,
    PersonalKnowledgeUnit,
)
import engine.app.ingestion.pipeline as pipeline
from engine.app.ingestion.chunker import ParentChunk


class _FakeIndices:
    def refresh(self, index):
        return None


class _FakeES:
    indices = _FakeIndices()

    def delete_by_query(self, *args, **kwargs):
        return None


class _FailingDeleteES:
    indices = _FakeIndices()

    def __init__(self, response=None, exc=None):
        self.response = response
        self.exc = exc

    def delete_by_query(self, *args, **kwargs):
        if self.exc:
            raise self.exc
        return self.response


class _ObjectApiLikeResponse:
    def __init__(self, body):
        self.body = body

    def get(self, key, default=None):
        return self.body.get(key, default)


def _create_memory_item(content="Vectorization should finish before governance. " * 100):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    session = Session()
    item = KnowledgeItem(
        title="Fast vectorization",
        content=content,
        summary="",
        source_type="manual",
        user_id="default-user",
    )
    session.add(item)
    session.commit()
    item_id = item.id
    session.close()
    return Session, item_id


def _parent_with_children(*children):
    parent = ParentChunk("parent text")
    parent.children = list(children)
    return parent


def test_ingest_item_skips_document_governance_and_uses_batch_vectors(monkeypatch):
    Session, item_id = _create_memory_item()
    parent = _parent_with_children("child one", "child two")
    batch_calls = []
    progress_calls = []
    vector_cleanup_calls = []

    monkeypatch.setattr(pipeline, "_Session", Session)
    monkeypatch.setattr(pipeline, "chunk_parent_child", lambda content: [parent])
    monkeypatch.setattr(pipeline, "embed_texts", lambda texts: [[0.1], [0.2]])
    monkeypatch.setattr(pipeline, "insert_vectors_batch", lambda rows: batch_calls.append(rows), raising=False)
    monkeypatch.setattr(pipeline, "delete_vectors_by_item", lambda item_id: vector_cleanup_calls.append(item_id), raising=False)
    monkeypatch.setattr(pipeline, "_bulk_index_chunks_es", lambda **kwargs: 2)
    monkeypatch.setattr(pipeline, "_delete_es_chunks_by_item", lambda item_id: None)

    def fail_governance(*args, **kwargs):
        raise AssertionError("governance must not run in ingest_item")

    monkeypatch.setattr(
        "backend.app.services.knowledge_governance.settle_document_item_to_governance",
        fail_governance,
        raising=False,
    )
    monkeypatch.setattr(pipeline, "settle_document_item_to_governance", fail_governance, raising=False)

    count = pipeline.ingest_item(item_id, progress=lambda **kwargs: progress_calls.append(kwargs))

    session = Session()
    try:
        assert count == 2
        child_ids = {
            chunk.id
            for chunk in session.query(KnowledgeChunk).filter_by(item_id=item_id, chunk_type="child").all()
        }
        assert len(batch_calls) == 1
        assert [row["chunk_id"] for row in batch_calls[0]]
        assert {row["chunk_id"] for row in batch_calls[0]} == child_ids
        assert [row["embedding"] for row in batch_calls[0]] == [[0.1], [0.2]]
        assert vector_cleanup_calls == [item_id]
        assert session.query(PersonalKnowledgeUnit).count() == 0
        assert session.query(PKUCanonicalLink).count() == 0
        assert session.query(CanonicalKnowledgePoint).count() == 0
        assert {"chunking", "embedding", "store_mysql_chunks", "store_milvus", "index_es"} <= {
            call["stage"] for call in progress_calls
        }
    finally:
        session.close()


def test_ingest_item_embeds_before_mysql_governance_cleanup(monkeypatch):
    Session, item_id = _create_memory_item()
    parent = _parent_with_children("child one")
    calls = []

    monkeypatch.setattr(pipeline, "_Session", Session)
    monkeypatch.setattr(pipeline, "chunk_parent_child", lambda content: [parent])
    monkeypatch.setattr(pipeline, "delete_vectors_by_item", lambda item_id: None, raising=False)
    monkeypatch.setattr(pipeline, "insert_vectors_batch", lambda rows: None)
    monkeypatch.setattr(pipeline, "_bulk_index_chunks_es", lambda **kwargs: 1)
    monkeypatch.setattr(pipeline, "_delete_es_chunks_by_item", lambda item_id: None)

    def embed(texts):
        calls.append("embed")
        return [[0.1]]

    def cleanup(db, received_item_id):
        assert received_item_id == item_id
        calls.append("cleanup")
        return 0

    monkeypatch.setattr(pipeline, "embed_texts", embed)
    monkeypatch.setattr(
        "backend.app.services.knowledge_governance.clear_document_item_governance",
        cleanup,
        raising=False,
    )

    assert pipeline.ingest_item(item_id) == 1
    assert calls == ["embed", "cleanup"]


def test_ingest_item_ignores_progress_callback_failures(monkeypatch):
    Session, item_id = _create_memory_item()
    parent = _parent_with_children("child one")

    monkeypatch.setattr(pipeline, "_Session", Session)
    monkeypatch.setattr(pipeline, "chunk_parent_child", lambda content: [parent])
    monkeypatch.setattr(pipeline, "embed_texts", lambda texts: [[0.1]])
    monkeypatch.setattr(pipeline, "delete_vectors_by_item", lambda item_id: None, raising=False)
    monkeypatch.setattr(pipeline, "insert_vectors_batch", lambda rows: None)
    monkeypatch.setattr(pipeline, "_bulk_index_chunks_es", lambda **kwargs: 1)
    monkeypatch.setattr(pipeline, "_delete_es_chunks_by_item", lambda item_id: None)

    def fail_progress(**kwargs):
        raise RuntimeError("progress store unavailable")

    assert pipeline.ingest_item(item_id, progress=fail_progress) == 1


def test_ingest_item_raises_when_es_bulk_index_fails(monkeypatch):
    import elasticsearch.helpers

    Session, item_id = _create_memory_item()
    parent = _parent_with_children("child one")

    monkeypatch.setattr(pipeline, "_Session", Session)
    monkeypatch.setattr(pipeline, "chunk_parent_child", lambda content: [parent])
    monkeypatch.setattr(pipeline, "embed_texts", lambda texts: [[0.1]])
    monkeypatch.setattr(pipeline, "delete_vectors_by_item", lambda item_id: None, raising=False)
    monkeypatch.setattr(pipeline, "insert_vectors_batch", lambda rows: None)
    monkeypatch.setattr(pipeline, "get_es", lambda: _FakeES())
    monkeypatch.setattr(elasticsearch.helpers, "bulk", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("es bulk down")))

    with pytest.raises(RuntimeError, match="es bulk down"):
        pipeline.ingest_item(item_id)

    session = Session()
    try:
        assert session.query(KnowledgeChunk).filter_by(item_id=item_id, chunk_type="parent").count() == 1
        assert session.query(KnowledgeChunk).filter_by(item_id=item_id, chunk_type="child").count() == 1
        assert session.query(KnowledgeItem).filter_by(id=item_id).one().summary
    finally:
        session.close()


def test_ingest_item_raises_when_es_cleanup_fails(monkeypatch):
    Session, item_id = _create_memory_item()
    parent = _parent_with_children("child one")

    monkeypatch.setattr(pipeline, "_Session", Session)
    monkeypatch.setattr(pipeline, "chunk_parent_child", lambda content: [parent])
    monkeypatch.setattr(pipeline, "embed_texts", lambda texts: [[0.1]])
    monkeypatch.setattr(pipeline, "get_es", lambda: _FailingDeleteES(exc=RuntimeError("delete down")))
    monkeypatch.setattr(pipeline, "delete_vectors_by_item", lambda item_id: None, raising=False)
    monkeypatch.setattr(pipeline, "insert_vectors_batch", lambda rows: None)
    monkeypatch.setattr(pipeline, "_bulk_index_chunks_es", lambda **kwargs: 1)

    with pytest.raises(RuntimeError, match="delete down"):
        pipeline.ingest_item(item_id)


@pytest.mark.parametrize(
    "response",
    [
        {"timed_out": True},
        {"failures": [{"id": "old-chunk", "cause": "shard failed"}]},
        _ObjectApiLikeResponse({"timed_out": True}),
        _ObjectApiLikeResponse({"failures": [{"id": "old-chunk", "cause": "shard failed"}]}),
    ],
)
def test_ingest_item_raises_when_es_cleanup_response_has_failures(monkeypatch, response):
    Session, item_id = _create_memory_item()
    parent = _parent_with_children("child one")

    monkeypatch.setattr(pipeline, "_Session", Session)
    monkeypatch.setattr(pipeline, "chunk_parent_child", lambda content: [parent])
    monkeypatch.setattr(pipeline, "embed_texts", lambda texts: [[0.1]])
    monkeypatch.setattr(pipeline, "get_es", lambda: _FailingDeleteES(response=response))
    monkeypatch.setattr(pipeline, "delete_vectors_by_item", lambda item_id: None, raising=False)
    monkeypatch.setattr(pipeline, "insert_vectors_batch", lambda rows: None)
    monkeypatch.setattr(pipeline, "_bulk_index_chunks_es", lambda **kwargs: 1)

    with pytest.raises(RuntimeError, match="delete_es_chunks"):
        pipeline.ingest_item(item_id)


def test_ingest_item_raises_on_embedding_count_mismatch_before_storing_chunks(monkeypatch):
    Session, item_id = _create_memory_item()
    parent = _parent_with_children("child one", "child two")

    monkeypatch.setattr(pipeline, "_Session", Session)
    monkeypatch.setattr(pipeline, "chunk_parent_child", lambda content: [parent])
    monkeypatch.setattr(pipeline, "embed_texts", lambda texts: [[0.1]])
    monkeypatch.setattr(pipeline, "_delete_es_chunks_by_item", lambda item_id: None)
    monkeypatch.setattr(pipeline, "delete_vectors_by_item", lambda item_id: None, raising=False)
    monkeypatch.setattr(pipeline, "insert_vectors_batch", lambda rows: None)
    monkeypatch.setattr(pipeline, "_bulk_index_chunks_es", lambda **kwargs: 1)

    with pytest.raises(RuntimeError, match="Embedding count mismatch"):
        pipeline.ingest_item(item_id)

    session = Session()
    try:
        assert session.query(KnowledgeChunk).filter_by(item_id=item_id).count() == 0
        assert session.query(KnowledgeItem).filter_by(id=item_id).one().summary == ""
    finally:
        session.close()


def test_ingest_item_deletes_existing_milvus_vectors_before_batch_insert(monkeypatch):
    Session, item_id = _create_memory_item()
    parent = _parent_with_children("child one", "child two")
    calls = []

    monkeypatch.setattr(pipeline, "_Session", Session)
    monkeypatch.setattr(pipeline, "chunk_parent_child", lambda content: [parent])
    monkeypatch.setattr(pipeline, "embed_texts", lambda texts: [[0.1], [0.2]])
    monkeypatch.setattr(pipeline, "_bulk_index_chunks_es", lambda **kwargs: 2)
    monkeypatch.setattr(pipeline, "_delete_es_chunks_by_item", lambda item_id: None)
    monkeypatch.setattr(pipeline, "delete_vectors_by_item", lambda item_id: calls.append(("delete", item_id)), raising=False)
    monkeypatch.setattr(pipeline, "insert_vectors_batch", lambda rows: calls.append(("insert", [row["chunk_id"] for row in rows])))

    assert pipeline.ingest_item(item_id) == 2
    assert [call[0] for call in calls] == ["delete", "insert"]
    assert calls[0] == ("delete", item_id)


def test_ingest_item_uses_positional_chunk_ids_for_duplicate_text(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    session = Session()
    item = KnowledgeItem(
        title="Duplicate chunk notes",
        content="The chunker is monkeypatched for this regression.",
        summary="",
        source_type="manual",
        tags=["duplicates"],
        category="RAG",
        user_id="default-user",
    )
    session.add(item)
    session.commit()
    item_id = item.id
    session.close()

    first_parent = ParentChunk("shared parent text")
    first_parent.children = ["duplicate child text", "shared parent text"]
    second_parent = ParentChunk("duplicate child text")
    second_parent.children = ["duplicate child text"]
    parents = [first_parent, second_parent]

    batch_calls = []
    es_kwargs = {}

    monkeypatch.setattr(pipeline, "_Session", Session)
    monkeypatch.setattr(pipeline, "chunk_parent_child", lambda content: parents)
    monkeypatch.setattr(pipeline, "embed_texts", lambda texts: [[float(i)] for i, _ in enumerate(texts)])
    monkeypatch.setattr(pipeline, "insert_vectors_batch", lambda rows: batch_calls.append(rows), raising=False)
    monkeypatch.setattr(pipeline, "delete_vectors_by_item", lambda item_id: None, raising=False)
    monkeypatch.setattr(pipeline, "get_es", lambda: _FakeES())

    def capture_bulk_index(**kwargs):
        es_kwargs.update(kwargs)
        return 1

    monkeypatch.setattr(pipeline, "_bulk_index_chunks_es", capture_bulk_index)
    monkeypatch.setattr(pipeline, "settle_document_item_to_governance", lambda *args, **kwargs: None, raising=False)

    count = pipeline.ingest_item(item_id)

    session = Session()
    try:
        assert count == 3
        parent_rows = (
            session.query(KnowledgeChunk)
            .filter_by(item_id=item_id, chunk_type="parent")
            .order_by(KnowledgeChunk.chunk_index.asc())
            .all()
        )
        assert [row.chunk_index for row in parent_rows] == [0, 1]

        child_rows = (
            session.query(KnowledgeChunk)
            .filter_by(item_id=item_id, chunk_type="child")
            .order_by(KnowledgeChunk.parent_id.asc(), KnowledgeChunk.chunk_index.asc())
            .all()
        )
        children_by_parent = {
            parent.id: sorted(
                [child for child in child_rows if child.parent_id == parent.id],
                key=lambda child: child.chunk_index,
            )
            for parent in parent_rows
        }
        assert [[child.chunk_index for child in children_by_parent[parent.id]] for parent in parent_rows] == [[0, 1], [0]]
        assert [child.parent_id for child in children_by_parent[parent_rows[0].id]] == [parent_rows[0].id, parent_rows[0].id]
        assert [child.parent_id for child in children_by_parent[parent_rows[1].id]] == [parent_rows[1].id]

        child_ids_by_position = {
            (parent_index, child.chunk_index): child.id
            for parent_index, parent in enumerate(parent_rows)
            for child in children_by_parent[parent.id]
        }
        assert len(batch_calls) == 1
        assert [row["chunk_id"] for row in batch_calls[0]] == [
            child_ids_by_position[(0, 0)],
            child_ids_by_position[(0, 1)],
            child_ids_by_position[(1, 0)],
        ]
        assert not {row["chunk_id"] for row in batch_calls[0]} & {parent.id for parent in parent_rows}

        assert es_kwargs["parent_id_map_by_index"] == {0: parent_rows[0].id, 1: parent_rows[1].id}
        assert es_kwargs["child_id_map_by_position"] == child_ids_by_position
    finally:
        session.close()


def test_ingest_item_logs_progress_and_failures(monkeypatch, caplog):
    import logging

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    session = Session()
    item = KnowledgeItem(
        title="Logging notes",
        content="Logging should reveal the failing ingestion stage.",
        source_type="manual",
        user_id="default-user",
    )
    session.add(item)
    session.commit()
    item_id = item.id
    session.close()

    parent = ParentChunk("parent")
    parent.children = ["child"]

    monkeypatch.setattr(pipeline, "_Session", Session)
    monkeypatch.setattr(pipeline, "chunk_parent_child", lambda content: [parent])

    def fail_embed(texts):
        raise RuntimeError("embedding provider unavailable")

    monkeypatch.setattr(pipeline, "embed_texts", fail_embed)

    caplog.set_level(logging.INFO, logger="uvicorn.error")

    try:
        pipeline.ingest_item(item_id)
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected RuntimeError")

    logs = caplog.text
    assert "[ingest.pipeline] start" in logs
    assert "stage=embedding" in logs
    assert "[ingest.pipeline] failed" in logs
    assert "embedding provider unavailable" in logs
