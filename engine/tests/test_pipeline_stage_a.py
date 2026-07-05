import os

if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "sqlite:///./_t.db"

from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database import Base
from backend.app.models import EntityMention, KnowledgeChunk, KnowledgeEntity, KnowledgeItem
from backend.app.services.entity_extraction import EntityCandidate
from engine.app.ingestion import chunker as chunker_module
import engine.app.ingestion.pipeline as pl


def _sqlite_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _seed_item(Session, content):
    session = Session()
    item = KnowledgeItem(
        title="混合检索说明",
        content=content,
        summary="",
        source_type="manual",
        user_id="default-user",
    )
    session.add(item)
    session.commit()
    item_id = item.id
    session.close()
    return item_id


def test_ingest_item_writes_stage_a_entities_and_mentions(monkeypatch):
    content = "混合检索是一种结合向量检索与关键词检索的方法。"
    parents = chunker_module.chunk_parent_child(content)
    child_texts = []
    for pc in parents:
        for child in pc.children:
            child_texts.append(getattr(child, "content", child))
    assert child_texts, "seed content should produce at least one child chunk"

    Session = _sqlite_session_factory()
    item_id = _seed_item(Session, content)

    monkeypatch.setattr(pl, "_Session", Session)
    monkeypatch.setattr(pl, "embed_texts", lambda texts: [[0.0] * 8 for _ in texts])
    monkeypatch.setattr(pl, "insert_vectors_batch", lambda rows: None, raising=False)
    monkeypatch.setattr(pl, "delete_vectors_by_ids", lambda chunk_ids: None, raising=False)
    monkeypatch.setattr(pl, "_delete_es_chunks_by_item", lambda item_id: None)
    monkeypatch.setattr(pl, "_bulk_index_chunks_es", lambda **kwargs: len(child_texts))

    def fake_extract_stage_a_parallel(chunks, max_workers=None):
        result = {}
        for cid, _text in chunks:
            result[cid] = [
                EntityCandidate(
                    kind="entity",
                    entity_type="concept",
                    surface_text="混合检索",
                    normalized_key="x",
                    aliases=["x"],
                    confidence=0.85,
                    extraction_method="llm_stage_a:INFERRED",
                )
            ]
        return result

    monkeypatch.setattr(pl, "extract_stage_a_parallel", fake_extract_stage_a_parallel)
    monkeypatch.setattr(pl, "_project_item_entities_to_graph", lambda db, item_id, user_id: None)

    count = pl.ingest_item(item_id)

    session = Session()
    try:
        assert count == len(child_texts)
        entities = session.query(KnowledgeEntity).all()
        mentions = session.query(EntityMention).filter(EntityMention.item_id == item_id).all()
        assert len(entities) >= 1
        assert len(mentions) >= 1
        assert any(e.entity_type == "concept" and e.canonical_name == "混合检索" for e in entities)
        assert any(m.extraction_method.startswith("llm_stage_a") for m in mentions)

        child_count = (
            session.query(KnowledgeChunk)
            .filter(KnowledgeChunk.item_id == item_id, KnowledgeChunk.chunk_type == "child")
            .count()
        )
        assert child_count == len(child_texts)
    finally:
        session.close()


def test_reingest_does_not_orphan_mentions(monkeypatch):
    """Re-ingest creates fresh chunk UUIDs; Stage A must clean this item's old
    document_chunk mentions (and their relations) instead of accumulating orphans.
    """
    content = "混合检索是一种结合向量检索与关键词检索的方法。"
    parents = chunker_module.chunk_parent_child(content)
    child_texts = []
    for pc in parents:
        for child in pc.children:
            child_texts.append(getattr(child, "content", child))
    assert child_texts, "seed content should produce at least one child chunk"

    Session = _sqlite_session_factory()
    item_id = _seed_item(Session, content)

    monkeypatch.setattr(pl, "_Session", Session)
    monkeypatch.setattr(pl, "embed_texts", lambda texts: [[0.0] * 8 for _ in texts])
    monkeypatch.setattr(pl, "insert_vectors_batch", lambda rows: None, raising=False)
    monkeypatch.setattr(pl, "delete_vectors_by_ids", lambda chunk_ids: None, raising=False)
    monkeypatch.setattr(pl, "_delete_es_chunks_by_item", lambda item_id: None)
    monkeypatch.setattr(pl, "_bulk_index_chunks_es", lambda **kwargs: len(child_texts))

    def fake_extract_stage_a_parallel(chunks, max_workers=None):
        result = {}
        for cid, _text in chunks:
            result[cid] = [
                EntityCandidate(
                    kind="entity",
                    entity_type="concept",
                    surface_text="混合检索",
                    normalized_key="x",
                    aliases=["x"],
                    confidence=0.85,
                    extraction_method="llm_stage_a:INFERRED",
                )
            ]
        return result

    monkeypatch.setattr(pl, "extract_stage_a_parallel", fake_extract_stage_a_parallel)
    monkeypatch.setattr(pl, "_project_item_entities_to_graph", lambda db, item_id, user_id: None)

    # First ingest.
    pl.ingest_item(item_id)

    session = Session()
    try:
        first_count = (
            session.query(EntityMention)
            .filter(EntityMention.item_id == item_id, EntityMention.source_kind == "document_chunk")
            .count()
        )
    finally:
        session.close()
    assert first_count >= 1

    # Re-ingest the same item -> new chunk UUIDs -> Stage A runs again.
    pl.ingest_item(item_id)

    session = Session()
    try:
        second_count = (
            session.query(EntityMention)
            .filter(EntityMention.item_id == item_id, EntityMention.source_kind == "document_chunk")
            .count()
        )
        # No accumulation: same number of mentions as after the first ingest.
        assert second_count == first_count

        # No mention references a chunk id that no longer exists in KnowledgeChunk.
        live_chunk_ids = {
            cid
            for (cid,) in (
                session.query(KnowledgeChunk.id)
                .filter(KnowledgeChunk.item_id == item_id, KnowledgeChunk.chunk_type == "child")
                .all()
            )
        }
        mentions = (
            session.query(EntityMention)
            .filter(EntityMention.item_id == item_id, EntityMention.source_kind == "document_chunk")
            .all()
        )
        for m in mentions:
            assert m.source_id in live_chunk_ids, (
                f"orphan mention source_id={m.source_id} not in live chunk ids {live_chunk_ids}"
            )
    finally:
        session.close()
