import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database import Base
from backend.app.models import (
    CanonicalKnowledgePoint,
    KnowledgeChunk,
    KnowledgeItem,
    PKUCanonicalLink,
    PersonalAssetUnit,
    PersonalKnowledgeUnit,
)
from engine.app.agent.tools.base import BUILTIN_REGISTRY, ToolContext, build_enabled_tools
import engine.app.agent.tools.governed_knowledge as governed_tool
import engine.app.agent.tools.knowledge_governance  # noqa: F401
import engine.app.agent.tools.assets  # noqa: F401
import engine.app.agent.tools.knowledge  # noqa: F401
import engine.app.agent.tools.memory  # noqa: F401
import engine.app.agent.tools.clarify  # noqa: F401
import engine.app.agent.tools.datetime  # noqa: F401
import engine.app.agent.tools.web_search  # noqa: F401


def test_governed_knowledge_search_returns_ckp_pku_and_raw_sources(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    unit = PersonalAssetUnit(
        title="Personal retrieval practice",
        summary="Personal knowledge retrieval needs metadata filters.",
        content="Personal knowledge retrieval needs metadata filter assisted search.",
        category="RAG",
        tags=["metadata", "filter"],
        source_asset_ids=["asset-1"],
        user_id="default-user",
        status="confirmed",
    )
    item = KnowledgeItem(
        title="Metadata filter reference",
        content="Metadata filter can restrict retrieval results by source or project.",
        source_type="manual",
        category="RAG",
        tags=["metadata", "filter"],
        user_id="default-user",
    )
    session.add_all([unit, item])
    session.flush()
    chunk = KnowledgeChunk(
        item_id=item.id,
        chunk_text="Metadata filter can restrict retrieval results by source or project.",
        chunk_type="parent",
    )
    ckp = CanonicalKnowledgePoint(
        title="Personal knowledge retrieval uses metadata filters",
        canonical_type="claim",
        canonical_statement="Personal knowledge retrieval uses metadata filters.",
        summary="Personal asset units and document evidence both support metadata filters.",
        keywords=["personal", "metadata", "filter", "retrieval"],
        concepts=["metadata", "filter"],
        user_id="default-user",
        confidence=0.86,
    )
    session.add_all([chunk, ckp])
    session.flush()
    unit_pku = PersonalKnowledgeUnit(
        source_kind="personal_asset_unit",
        source_id=unit.id,
        unit_type="claim",
        statement="Personal knowledge retrieval needs metadata filter assisted search.",
        normalized_statement="personal knowledge retrieval needs metadata filter assisted search",
        normalized_statement_hash="unit-hash",
        modality="fact",
        keywords=["personal", "metadata", "filter"],
        user_id="default-user",
    )
    doc_pku = PersonalKnowledgeUnit(
        source_kind="document_chunk",
        source_id=chunk.id,
        unit_type="definition",
        statement="Metadata filter can restrict retrieval results by source or project.",
        normalized_statement="metadata filter restricts retrieval results by source or project",
        normalized_statement_hash="doc-hash",
        modality="fact",
        keywords=["metadata", "filter", "retrieval"],
        user_id="default-user",
    )
    session.add_all([unit_pku, doc_pku])
    session.flush()
    session.add_all(
        [
            PKUCanonicalLink(
                pku_id=unit_pku.id,
                canonical_id=ckp.id,
                relation_type="same_as",
                role="synthesized_personal_knowledge",
                confidence=0.9,
                user_id="default-user",
            ),
            PKUCanonicalLink(
                pku_id=doc_pku.id,
                canonical_id=ckp.id,
                relation_type="defines",
                role="external_reference",
                confidence=0.8,
                user_id="default-user",
            ),
        ]
    )
    session.commit()
    session.close()

    monkeypatch.setattr(governed_tool, "_Session", Session)
    ctx = ToolContext(rag_runner=None, citations=[], stats_holder={})
    tool = BUILTIN_REGISTRY["governed_knowledge_search"].builder(ctx)

    payload = json.loads(tool.invoke({"query": "personal metadata filter retrieval", "limit": 5}))

    assert payload["status"] == "success"
    assert payload["canonical_results"][0]["title"] == "Personal knowledge retrieval uses metadata filters"
    bundle = payload["evidence_bundle"][0]
    assert {pku["role"] for pku in bundle["linked_pkus"]} == {"synthesized_personal_knowledge", "external_reference"}
    assert {source["source_kind"] for source in bundle["raw_sources"]} == {"personal_asset_unit", "document_chunk"}
    assert len(ctx.citations) == 2
    assert ctx.stats_holder["governed_knowledge_search"]["hit_count"] == 1


def test_governed_knowledge_search_returns_synthesized_knowledge_without_ckp(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    unit = PersonalAssetUnit(
        title="Personal knowledge search and graph design principles",
        summary="Personal knowledge should combine hybrid retrieval, CKP main nodes, and PKU evidence.",
        content="The retrieval layer uses vector, keyword, and metadata filters. The graph layer uses CKP as stable knowledge points and PKU as evidence.",
        category="Knowledge governance",
        tags=["personal knowledge", "retrieval", "graph", "CKP", "PKU"],
        source_asset_ids=[],
        status="confirmed",
        user_id="default-user",
    )
    session.add(unit)
    session.commit()
    session.close()

    monkeypatch.setattr(governed_tool, "_Session", Session)
    ctx = ToolContext(rag_runner=None, citations=[], stats_holder={})
    tool = BUILTIN_REGISTRY["governed_knowledge_search"].builder(ctx)

    payload = json.loads(tool.invoke({"query": "personal knowledge search graph design principles", "limit": 5}))

    assert payload["status"] == "success"
    assert payload["knowledge_results"][0]["title"] == "Personal knowledge search and graph design principles"
    assert payload["sources"][0]["source_kind"] == "personal_asset_unit"
    assert ctx.stats_holder["governed_knowledge_search"]["knowledge_hit_count"] == 1


def test_knowledge_material_search_backtracks_from_pku_to_source_materials(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    item = KnowledgeItem(
        title="Metadata filter field notes",
        content="Metadata filter should be combined with semantic retrieval for personal knowledge.",
        source_type="manual",
        category="RAG",
        tags=["metadata", "filter"],
        user_id="default-user",
    )
    session.add(item)
    session.flush()
    chunk = KnowledgeChunk(
        item_id=item.id,
        chunk_text="Opinion: metadata filter should be combined with semantic retrieval for personal knowledge.",
        chunk_type="parent",
    )
    ckp = CanonicalKnowledgePoint(
        title="Metadata filter retrieval opinions",
        canonical_type="topic",
        canonical_statement="Opinions about combining metadata filters with retrieval.",
        summary="Metadata filters help scope personal knowledge retrieval.",
        keywords=["metadata", "filter", "retrieval"],
        concepts=["metadata filter"],
        user_id="default-user",
        confidence=0.9,
    )
    session.add_all([chunk, ckp])
    session.flush()
    item_id = item.id
    pku = PersonalKnowledgeUnit(
        source_kind="document_chunk",
        source_id=chunk.id,
        unit_type="opinion",
        statement="Metadata filter should be combined with semantic retrieval.",
        normalized_statement="metadata filter should be combined with semantic retrieval",
        normalized_statement_hash="opinion-hash",
        modality="opinion",
        keywords=["metadata", "filter", "retrieval"],
        user_id="default-user",
    )
    session.add(pku)
    session.flush()
    session.add(
        PKUCanonicalLink(
            pku_id=pku.id,
            canonical_id=ckp.id,
            relation_type="about",
            role="topic_member",
            confidence=0.88,
            user_id="default-user",
        )
    )
    session.commit()
    session.close()

    monkeypatch.setattr(governed_tool, "_Session", Session)
    ctx = ToolContext(rag_runner=None, citations=[], stats_holder={})
    tool = next(t for t in build_enabled_tools(ctx) if t.name == "knowledge_material_search")

    payload = json.loads(tool.invoke({"query": "metadata filter", "intent": "opinions", "limit": 5}))

    assert payload["status"] == "success"
    assert payload["materials"][0]["source"]["source_kind"] == "document_chunk"
    assert payload["materials"][0]["source"]["display_type"] == "knowledge_item"
    assert payload["materials"][0]["source"]["display_id"] == item_id
    assert payload["materials"][0]["source"]["display_title"] == "Metadata filter field notes"
    assert payload["materials"][0]["source"]["snippet"].startswith("Opinion: metadata filter")
    assert payload["materials"][0]["source"]["score"] > 0
    assert payload["materials"][0]["matched_pkus"][0]["statement"] == "Metadata filter should be combined with semantic retrieval."
    assert payload["materials"][0]["extracted_opinions"][0]["canonical_title"] == "Metadata filter retrieval opinions"
    assert ctx.stats_holder["knowledge_material_search"]["hit_count"] == 1


def test_knowledge_material_search_lists_personal_asset_unit_as_display_source(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    unit = PersonalAssetUnit(
        title="Metadata filter personal notes",
        summary="Personal note says metadata filters should scope retrieval.",
        content="I think metadata filters should scope retrieval before semantic ranking.",
        category="RAG",
        tags=["metadata", "filter"],
        source_asset_ids=["asset-1"],
        user_id="default-user",
        status="confirmed",
    )
    ckp = CanonicalKnowledgePoint(
        title="Metadata filter personal opinions",
        canonical_type="topic",
        canonical_statement="Personal opinions about metadata filters.",
        summary="User opinions about metadata filter retrieval.",
        keywords=["metadata", "filter", "retrieval"],
        concepts=["metadata filter"],
        user_id="default-user",
        confidence=0.9,
    )
    session.add_all([unit, ckp])
    session.flush()
    unit_id = unit.id
    pku = PersonalKnowledgeUnit(
        source_kind="personal_asset_unit",
        source_id=unit.id,
        unit_type="opinion",
        statement="Metadata filters should scope retrieval before semantic ranking.",
        normalized_statement="metadata filters should scope retrieval before semantic ranking",
        normalized_statement_hash="unit-opinion-hash",
        modality="opinion",
        keywords=["metadata", "filter", "retrieval"],
        user_id="default-user",
    )
    session.add(pku)
    session.flush()
    session.add(
        PKUCanonicalLink(
            pku_id=pku.id,
            canonical_id=ckp.id,
            relation_type="about",
            role="topic_member",
            confidence=0.88,
            user_id="default-user",
        )
    )
    session.commit()
    session.close()

    monkeypatch.setattr(governed_tool, "_Session", Session)
    ctx = ToolContext(rag_runner=None, citations=[], stats_holder={})
    tool = next(t for t in build_enabled_tools(ctx) if t.name == "knowledge_material_search")

    payload = json.loads(tool.invoke({"query": "metadata filter", "intent": "opinions", "limit": 5}))

    source = payload["materials"][0]["source"]
    assert source["source_kind"] == "personal_asset_unit"
    assert source["display_type"] == "personal_asset_unit"
    assert source["display_id"] == unit_id
    assert source["display_title"] == "Metadata filter personal notes"
    assert source["snippet"].startswith("Personal note says metadata filters")
    assert source["score"] > 0
