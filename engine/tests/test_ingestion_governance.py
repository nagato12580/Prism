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

        links = session.query(PKUCanonicalLink).all()
        assert len(links) == 1
        assert links[0].role == "external_reference"
        assert session.query(CanonicalKnowledgePoint).count() == 1
    finally:
        session.close()
