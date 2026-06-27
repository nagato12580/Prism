import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./_deep_search_import.db")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database import Base
from backend.app.models import (
    CanonicalKnowledgePoint,
    KnowledgeChunk,
    KnowledgeItem,
    PKUCanonicalLink,
    PKURelation,
    PersonalKnowledgeUnit,
)
from engine.app.agent.deep_search.executors import (
    PkuGraphExpansionExecutor,
    PkuRequeryExecutor,
    ScopeFinderExecutor,
    SourceBacktrackExecutor,
)


def _build_governed_graph():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    item = KnowledgeItem(
        title="Agentic RAG Design",
        content="Agentic RAG uses metadata filters before chunk search.",
        source_type="document",
        user_id="default-user",
    )
    session.add(item)
    session.flush()

    chunk = KnowledgeChunk(
        item_id=item.id,
        chunk_text="Agentic RAG uses metadata filters before chunk search.",
        chunk_type="parent",
    )
    session.add(chunk)
    session.flush()

    ckp = CanonicalKnowledgePoint(
        title="Agentic RAG scope first retrieval",
        canonical_type="method",
        canonical_statement="Agentic RAG should find CKP and PKU scope before chunk search.",
        summary="Scope finder narrows search using CKP, PKU, topic, and metadata.",
        keywords=["agentic", "rag", "scope", "metadata"],
        concepts=["scope finder", "retrieval"],
        user_id="default-user",
        status="stable",
        confidence=0.9,
    )
    session.add(ckp)
    session.flush()

    pku = PersonalKnowledgeUnit(
        source_kind="document_chunk",
        source_id=chunk.id,
        unit_type="method",
        statement="Use CKP and PKU scope before expensive chunk search.",
        normalized_statement="use ckp pku scope before chunk search",
        normalized_statement_hash="pku-1",
        keywords=["ckp", "pku", "scope"],
        concepts=["scope finder"],
        evidence_span="Use CKP and PKU scope before expensive chunk search.",
        user_id="default-user",
        status="active",
        confidence=0.85,
    )
    related = PersonalKnowledgeUnit(
        source_kind="document_chunk",
        source_id=chunk.id,
        unit_type="claim",
        statement="Judge asks for PKU re-query when evidence is incomplete.",
        normalized_statement="judge asks pku requery when evidence incomplete",
        normalized_statement_hash="pku-2",
        keywords=["judge", "pku", "requery"],
        concepts=["judge"],
        evidence_span="Judge asks for PKU re-query when evidence is incomplete.",
        user_id="default-user",
        status="active",
        confidence=0.75,
    )
    session.add_all([pku, related])
    session.flush()

    session.add_all(
        [
            PKUCanonicalLink(
                pku_id=pku.id,
                canonical_id=ckp.id,
                relation_type="supports",
                confidence=0.86,
                user_id="default-user",
            ),
            PKUCanonicalLink(
                pku_id=related.id,
                canonical_id=ckp.id,
                relation_type="related_to",
                confidence=0.65,
                user_id="default-user",
            ),
            PKURelation(
                source_pku_id=pku.id,
                target_pku_id=related.id,
                relation_type="related_to",
                confidence=0.7,
                reason="same retrieval workflow",
                user_id="default-user",
            ),
        ]
    )
    session.commit()
    ids = {
        "ckp": ckp.id,
        "pku": pku.id,
        "related": related.id,
        "chunk": chunk.id,
        "item": item.id,
    }
    session.close()
    return Session, ids


def test_scope_finder_uses_ckp_and_pku_lexical_scope():
    Session, ids = _build_governed_graph()
    scope = ScopeFinderExecutor(Session).run("agentic rag metadata scope", limit=5)

    assert ids["ckp"] in scope.seed_ckp_ids
    assert ids["pku"] in scope.seed_pku_ids
    assert ids["item"] in scope.candidate_item_ids


def test_source_backtrack_emits_source_backed_evidence():
    Session, ids = _build_governed_graph()
    scope = ScopeFinderExecutor(Session).run("agentic rag metadata scope", limit=5)
    evidence = SourceBacktrackExecutor(Session).run(scope)

    assert any(record.pku_id == ids["pku"] for record in evidence)
    first = next(record for record in evidence if record.pku_id == ids["pku"])
    assert first.source_kind == "document_chunk"
    assert first.source_id == ids["chunk"]
    assert first.ckp_id == ids["ckp"]
    assert "scope" in first.statement.lower()


def test_pku_graph_expansion_finds_related_same_layer_evidence():
    Session, ids = _build_governed_graph()
    evidence = PkuGraphExpansionExecutor(Session).run(seed_pku_ids=[ids["pku"]], limit=5)

    assert any(record.pku_id == ids["related"] for record in evidence)
    related = next(record for record in evidence if record.pku_id == ids["related"])
    assert related.strategy == "pku_graph_expansion"
    assert related.relation_type == "related_to"
    assert related.scope_distance == 1


def test_pku_requery_stays_inside_seed_ckp_scope():
    Session, ids = _build_governed_graph()
    evidence = PkuRequeryExecutor(Session).run(
        query="judge requery incomplete evidence",
        seed_ckp_ids=[ids["ckp"]],
        limit=5,
    )

    assert any(record.pku_id == ids["related"] for record in evidence)
    assert all(record.ckp_id == ids["ckp"] for record in evidence)
