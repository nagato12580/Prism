from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database import Base
from backend.app.models import (
    CanonicalKnowledgePoint,
    KnowledgeChunk,
    KnowledgeItem,
    PKUCanonicalLink,
    PersonalKnowledgeUnit,
)
from backend.app.services import knowledge_governance as kg
import engine.app.ingestion.pipeline as pipeline
from engine.app.ingestion.chunker import ParentChunk


class _FakeIndices:
    def refresh(self, index):
        return None


class _FakeES:
    indices = _FakeIndices()

    def delete_by_query(self, *args, **kwargs):
        return None


def test_ingest_item_settles_document_chunks_into_governance_layer(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    session = Session()
    item = KnowledgeItem(
        title="Hybrid retrieval notes",
        content="Metadata filtering allows retrieval systems to restrict results by project. Hybrid search combines keyword and vector recall.",
        summary="",
        source_type="manual",
        tags=["retrieval"],
        category="RAG",
        user_id="default-user",
    )
    session.add(item)
    session.commit()
    item_id = item.id
    session.close()

    monkeypatch.setattr(pipeline, "_Session", Session)
    monkeypatch.setattr(pipeline, "embed_texts", lambda texts: [[0.1, 0.2, 0.3] for _ in texts])
    monkeypatch.setattr(pipeline, "insert_vectors", lambda **kwargs: None)
    monkeypatch.setattr(pipeline, "get_es", lambda: _FakeES())
    monkeypatch.setattr(pipeline, "_bulk_index_chunks_es", lambda **kwargs: 1)
    monkeypatch.setattr(
        kg,
        "_extract_document_chunk_pkus_with_llm",
        lambda item, anchor_chunk, previous_chunk=None, next_chunk=None, anchor_index=None: kg.AssetUnitPKUExtraction(
            pkus=[
                kg.ExtractedPKU(
                    local_id="pku_1",
                    statement="Metadata filtering allows retrieval systems to restrict results by project.",
                    unit_type="method",
                    evidence_span="Metadata filtering allows retrieval systems to restrict results by project.",
                    keywords=["metadata", "retrieval"],
                    concepts=["metadata filtering"],
                    entities=[],
                    domains=["RAG"],
                    group="retrieval",
                    confidence=0.9,
                    reason="test extraction",
                    llm_model="test-model",
                )
            ],
            relations=[],
            llm_model="test-model",
        ),
    )
    monkeypatch.setattr(kg, "search_ckp_vectors", lambda **kwargs: [])
    monkeypatch.setattr(kg, "upsert_ckp_vector", lambda ckp: f"test-vector:{ckp.id}")

    count = pipeline.ingest_item(item_id)

    session = Session()
    try:
        assert count >= 1
        chunks = session.query(KnowledgeChunk).filter_by(item_id=item_id).all()
        assert chunks

        pkus = session.query(PersonalKnowledgeUnit).filter_by(source_kind="document_chunk").all()
        assert len(pkus) == 1
        assert pkus[0].source_id in {chunk.id for chunk in chunks}
        assert pkus[0].modality == "fact"
        assert "Metadata filtering" in pkus[0].statement
        assert pkus[0].llm_model == "test-model"

        links = session.query(PKUCanonicalLink).all()
        assert len(links) == 1
        assert links[0].role == "external_reference"
        assert session.query(CanonicalKnowledgePoint).count() == 1
    finally:
        session.close()


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

    vector_calls = []
    es_kwargs = {}

    monkeypatch.setattr(pipeline, "_Session", Session)
    monkeypatch.setattr(pipeline, "chunk_parent_child", lambda content: parents)
    monkeypatch.setattr(pipeline, "embed_texts", lambda texts: [[float(i)] for i, _ in enumerate(texts)])
    monkeypatch.setattr(pipeline, "insert_vectors", lambda **kwargs: vector_calls.append(kwargs))
    monkeypatch.setattr(pipeline, "get_es", lambda: _FakeES())

    def capture_bulk_index(**kwargs):
        es_kwargs.update(kwargs)
        return 1

    monkeypatch.setattr(pipeline, "_bulk_index_chunks_es", capture_bulk_index)
    monkeypatch.setattr(kg, "_extract_document_chunk_pkus_with_llm", lambda *args, **kwargs: kg.AssetUnitPKUExtraction([], []))
    monkeypatch.setattr(kg, "search_ckp_vectors", lambda **kwargs: [])
    monkeypatch.setattr(kg, "upsert_ckp_vector", lambda ckp: f"test-vector:{ckp.id}")

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
        assert [call["chunk_id"] for call in vector_calls] == [
            child_ids_by_position[(0, 0)],
            child_ids_by_position[(0, 1)],
            child_ids_by_position[(1, 0)],
        ]
        assert not {call["chunk_id"] for call in vector_calls} & {parent.id for parent in parent_rows}

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
