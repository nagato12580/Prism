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
