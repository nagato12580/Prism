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
from engine.app.agent.tools.base import ToolContext, build_enabled_tools
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
    tool = governed_tool._build_governed_knowledge_search(ctx)

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
    tool = governed_tool._build_governed_knowledge_search(ctx)

    payload = json.loads(tool.invoke({"query": "personal knowledge search graph design principles", "limit": 5}))

    assert payload["status"] == "success"
    assert payload["knowledge_results"][0]["title"] == "Personal knowledge search and graph design principles"
    assert payload["sources"][0]["source_kind"] == "personal_asset_unit"
    assert ctx.stats_holder["governed_knowledge_search"]["knowledge_hit_count"] == 1


def test_governed_evidence_uses_ckp_vector_candidates(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    item = KnowledgeItem(
        title="Vector CKP evidence",
        content="Beam search keeps several candidate sequences.",
        source_type="manual",
        user_id="default-user",
    )
    session.add(item)
    session.flush()
    parent = KnowledgeChunk(
        item_id=item.id,
        chunk_text="Beam search keeps several candidate sequences.",
        chunk_type="parent",
    )
    session.add(parent)
    session.flush()
    child = KnowledgeChunk(
        item_id=item.id,
        parent_id=parent.id,
        chunk_text="Beam search keeps several candidate sequences.",
        chunk_type="child",
        chunk_index=0,
    )
    ckp = CanonicalKnowledgePoint(
        title="Sequence decoding strategy",
        canonical_type="topic",
        canonical_statement="Decoding strategies maintain candidate sequences.",
        summary="Beam search evidence.",
        keywords=["decoding"],
        concepts=["sequence"],
        user_id="default-user",
        confidence=0.9,
    )
    session.add_all([child, ckp])
    session.flush()
    ckp_id = ckp.id
    parent_id = parent.id
    child_id = child.id
    pku = PersonalKnowledgeUnit(
        source_kind="document_chunk",
        source_id=parent.id,
        unit_type="claim",
        statement="Beam search keeps several candidate sequences.",
        normalized_statement="beam search keeps several candidate sequences",
        normalized_statement_hash="beam-search-hash",
        evidence_span="Beam search keeps several candidate sequences.",
        keywords=["beam", "search"],
        user_id="default-user",
        confidence=0.8,
    )
    session.add(pku)
    session.flush()
    session.add(
        PKUCanonicalLink(
            pku_id=pku.id,
            canonical_id=ckp.id,
            relation_type="about",
            role="evidence",
            confidence=0.7,
            user_id="default-user",
        )
    )
    session.commit()
    session.close()

    monkeypatch.setattr(governed_tool, "_Session", Session)
    monkeypatch.setattr(governed_tool, "search_ckp_vectors", lambda **kwargs: [{"ckp_id": ckp_id, "score": 0.92}])
    monkeypatch.setattr(governed_tool, "search_pku_vectors", lambda **kwargs: [])

    _terms, bundles, _knowledge = governed_tool._query_governed_evidence("beam search candidates", limit=5)

    assert bundles[0]["canonical_id"] == ckp_id
    assert bundles[0]["retrieval_mode"] == "governed_evidence"
    assert bundles[0]["raw_sources"][0]["chunk_id"] == parent_id
    assert bundles[0]["expanded_sources"][0]["chunk_id"] == child_id


def test_governed_evidence_falls_back_to_lexical_when_vector_search_fails(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    item = KnowledgeItem(
        title="Metadata filter reference",
        content="Metadata filter can restrict retrieval results by source or project.",
        source_type="manual",
        user_id="default-user",
    )
    session.add(item)
    session.flush()
    chunk = KnowledgeChunk(
        item_id=item.id,
        chunk_text="Metadata filter can restrict retrieval results by source or project.",
        chunk_type="parent",
    )
    ckp = CanonicalKnowledgePoint(
        title="Metadata filter retrieval",
        canonical_type="claim",
        canonical_statement="Metadata filters restrict retrieval results.",
        summary="Metadata filters scope retrieval.",
        keywords=["metadata", "filter", "retrieval"],
        concepts=["metadata filter"],
        user_id="default-user",
        confidence=0.86,
    )
    session.add_all([chunk, ckp])
    session.flush()
    ckp_id = ckp.id
    pku = PersonalKnowledgeUnit(
        source_kind="document_chunk",
        source_id=chunk.id,
        unit_type="claim",
        statement="Metadata filter can restrict retrieval results by source or project.",
        normalized_statement="metadata filter restricts retrieval results by source or project",
        normalized_statement_hash="metadata-filter-hash",
        evidence_span="Metadata filter can restrict retrieval results by source or project.",
        keywords=["metadata", "filter"],
        user_id="default-user",
        confidence=0.8,
    )
    session.add(pku)
    session.flush()
    session.add(
        PKUCanonicalLink(
            pku_id=pku.id,
            canonical_id=ckp.id,
            relation_type="about",
            role="evidence",
            confidence=0.8,
            user_id="default-user",
        )
    )
    session.commit()
    session.close()

    monkeypatch.setattr(governed_tool, "_Session", Session)

    def fail_vector_search(**kwargs):
        raise RuntimeError("milvus down")

    monkeypatch.setattr(governed_tool, "search_ckp_vectors", fail_vector_search)
    monkeypatch.setattr(governed_tool, "search_pku_vectors", lambda **kwargs: [])

    _terms, bundles, _knowledge = governed_tool._query_governed_evidence("metadata filter", limit=5)

    assert bundles[0]["canonical_id"] == ckp_id
    assert bundles[0]["retrieval_mode"] == "governed_evidence"


def test_governed_evidence_reranks_linked_pkus_by_query_relevance(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    item = KnowledgeItem(
        title="C++ storage rules",
        content="Database table storage engine must use InnoDB.",
        source_type="manual",
        user_id="default-user",
    )
    session.add(item)
    session.flush()
    general_parent = KnowledgeChunk(
        item_id=item.id,
        chunk_text="General coding guideline.",
        chunk_type="parent",
    )
    relevant_parent = KnowledgeChunk(
        item_id=item.id,
        chunk_text="Database table storage engine must use InnoDB.",
        chunk_type="parent",
    )
    session.add_all([general_parent, relevant_parent])
    session.flush()
    relevant_child = KnowledgeChunk(
        item_id=item.id,
        parent_id=relevant_parent.id,
        chunk_text="Database table storage engine must use InnoDB.",
        chunk_type="child",
        chunk_index=0,
    )
    ckp = CanonicalKnowledgePoint(
        title="C++ database table storage rules",
        canonical_type="claim",
        canonical_statement="Database tables follow storage engine rules.",
        summary="Database table storage engine rules.",
        keywords=["database", "storage", "engine"],
        concepts=["database"],
        user_id="default-user",
        confidence=0.9,
    )
    session.add_all([relevant_child, ckp])
    session.flush()
    general_pku = PersonalKnowledgeUnit(
        source_kind="document_chunk",
        source_id=general_parent.id,
        unit_type="claim",
        statement="General coding guideline.",
        normalized_statement="general coding guideline",
        normalized_statement_hash="general-guideline-hash",
        evidence_span="General coding guideline.",
        keywords=["coding"],
        user_id="default-user",
        confidence=0.95,
    )
    relevant_pku = PersonalKnowledgeUnit(
        source_kind="document_chunk",
        source_id=relevant_parent.id,
        unit_type="claim",
        statement="Database table storage engine must use InnoDB.",
        normalized_statement="database table storage engine must use innodb",
        normalized_statement_hash="innodb-hash",
        evidence_span="Database table storage engine must use InnoDB.",
        keywords=["database", "storage", "engine", "innodb"],
        user_id="default-user",
        confidence=0.6,
    )
    session.add_all([general_pku, relevant_pku])
    session.flush()
    relevant_pku_id = relevant_pku.id
    relevant_parent_id = relevant_parent.id
    relevant_child_id = relevant_child.id
    session.add_all(
        [
            PKUCanonicalLink(
                pku_id=general_pku.id,
                canonical_id=ckp.id,
                relation_type="about",
                role="high_confidence_irrelevant",
                confidence=0.95,
                user_id="default-user",
            ),
            PKUCanonicalLink(
                pku_id=relevant_pku.id,
                canonical_id=ckp.id,
                relation_type="about",
                role="lower_confidence_relevant",
                confidence=0.6,
                user_id="default-user",
            ),
        ]
    )
    session.commit()
    session.close()

    monkeypatch.setattr(governed_tool, "_Session", Session)
    monkeypatch.setattr(governed_tool, "search_ckp_vectors", lambda **kwargs: [])
    monkeypatch.setattr(governed_tool, "search_pku_vectors", lambda **kwargs: [])

    _terms, bundles, _knowledge = governed_tool._query_governed_evidence("database storage engine innodb", limit=5)

    bundle = bundles[0]
    assert bundle["linked_pkus"][0]["pku_id"] == relevant_pku_id
    assert bundle["raw_sources"][0]["chunk_id"] == relevant_parent_id
    assert bundle["raw_sources"][0]["score"] == bundle["linked_pkus"][0]["evidence_score"]
    assert bundle["raw_sources"][1]["score"] == bundle["linked_pkus"][1]["evidence_score"]
    assert bundle["expanded_sources"][0]["source_kind"] == "document_chunk"
    assert bundle["expanded_sources"][0]["chunk_type"] == "child"
    assert bundle["expanded_sources"][0]["parent_chunk_id"] == relevant_parent_id
    assert bundle["expanded_sources"][0]["chunk_id"] == relevant_child_id


def test_governed_evidence_recalls_ckp_from_matching_pku_text(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    item = KnowledgeItem(
        title="Fine grained evidence",
        content="The minimum viable text classification dataset contains 200 samples.",
        source_type="manual",
        user_id="default-user",
    )
    session.add(item)
    session.flush()
    parent = KnowledgeChunk(
        item_id=item.id,
        chunk_text="The minimum viable text classification dataset contains 200 samples.",
        chunk_type="parent",
    )
    session.add(parent)
    session.flush()
    child = KnowledgeChunk(
        item_id=item.id,
        parent_id=parent.id,
        chunk_text="The minimum viable text classification dataset contains 200 samples.",
        chunk_type="child",
        chunk_index=0,
    )
    ckp = CanonicalKnowledgePoint(
        title="Model adaptation data planning",
        canonical_type="topic",
        canonical_statement="Training data planning should match the task.",
        summary="General guidance about data planning.",
        keywords=["planning"],
        concepts=["adaptation"],
        user_id="default-user",
        confidence=0.7,
    )
    session.add_all([child, ckp])
    session.flush()
    ckp_id = ckp.id
    child_id = child.id
    pku = PersonalKnowledgeUnit(
        source_kind="document_chunk",
        source_id=parent.id,
        unit_type="claim",
        statement="The minimum viable text classification dataset contains 200 samples.",
        normalized_statement="minimum viable text classification dataset contains 200 samples",
        normalized_statement_hash="text-classification-200",
        evidence_span="minimum viable text classification dataset contains 200 samples",
        keywords=["text", "classification", "dataset", "samples"],
        user_id="default-user",
        confidence=0.9,
    )
    session.add(pku)
    session.flush()
    session.add(
        PKUCanonicalLink(
            pku_id=pku.id,
            canonical_id=ckp.id,
            relation_type="about",
            role="fine_grained_evidence",
            confidence=0.8,
            user_id="default-user",
        )
    )
    session.commit()
    session.close()

    monkeypatch.setattr(governed_tool, "_Session", Session)
    monkeypatch.setattr(governed_tool, "search_ckp_vectors", lambda **kwargs: [])
    monkeypatch.setattr(governed_tool, "search_pku_vectors", lambda **kwargs: [])

    _terms, bundles, _knowledge = governed_tool._query_governed_evidence("text classification samples", limit=5)

    assert bundles[0]["canonical_id"] == ckp_id
    assert bundles[0]["expanded_sources"][0]["chunk_id"] == child_id


def test_governed_evidence_uses_pku_vector_hits_to_recall_ckp(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    item = KnowledgeItem(
        title="Quiet source",
        content="The source uses terminology that does not overlap the query.",
        source_type="manual",
        user_id="default-user",
    )
    session.add(item)
    session.flush()
    parent = KnowledgeChunk(
        item_id=item.id,
        chunk_text="The source uses terminology that does not overlap the query.",
        chunk_type="parent",
    )
    session.add(parent)
    session.flush()
    child = KnowledgeChunk(
        item_id=item.id,
        parent_id=parent.id,
        chunk_text="The source uses terminology that does not overlap the query.",
        chunk_type="child",
        chunk_index=0,
    )
    ckp = CanonicalKnowledgePoint(
        title="Quiet canonical point",
        canonical_type="topic",
        canonical_statement="This canonical point has no lexical overlap.",
        summary="No lexical overlap here.",
        keywords=["quiet"],
        concepts=["quiet"],
        user_id="default-user",
        confidence=0.7,
    )
    session.add_all([child, ckp])
    session.flush()
    pku = PersonalKnowledgeUnit(
        source_kind="document_chunk",
        source_id=parent.id,
        unit_type="claim",
        statement="The source uses terminology that does not overlap the query.",
        normalized_statement="source terminology without query overlap",
        normalized_statement_hash="pku-vector-only",
        evidence_span="The source uses terminology that does not overlap the query.",
        keywords=["quiet"],
        user_id="default-user",
        confidence=0.8,
    )
    session.add(pku)
    session.flush()
    ckp_id = ckp.id
    pku_id = pku.id
    child_id = child.id
    session.add(
        PKUCanonicalLink(
            pku_id=pku.id,
            canonical_id=ckp.id,
            relation_type="about",
            role="vector_only_evidence",
            confidence=0.7,
            user_id="default-user",
        )
    )
    session.commit()
    session.close()

    monkeypatch.setattr(governed_tool, "_Session", Session)
    monkeypatch.setattr(governed_tool, "search_ckp_vectors", lambda **kwargs: [])
    monkeypatch.setattr(governed_tool, "search_pku_vectors", lambda **kwargs: [{"pku_id": pku_id, "score": 0.93}])

    _terms, bundles, _knowledge = governed_tool._query_governed_evidence("needle phrase only vector knows", limit=5)

    assert bundles[0]["canonical_id"] == ckp_id
    assert bundles[0]["linked_pkus"][0]["pku_id"] == pku_id
    assert bundles[0]["linked_pkus"][0]["pku_vector_score"] == 0.93
    assert "pku_vector" in " ".join(bundles[0]["match_reasons"])
    assert bundles[0]["expanded_sources"][0]["chunk_id"] == child_id


def test_governed_evidence_degrades_when_pku_vector_search_fails(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    item = KnowledgeItem(
        title="Metadata filter reference",
        content="Metadata filter can restrict retrieval results by source or project.",
        source_type="manual",
        user_id="default-user",
    )
    session.add(item)
    session.flush()
    chunk = KnowledgeChunk(
        item_id=item.id,
        chunk_text="Metadata filter can restrict retrieval results by source or project.",
        chunk_type="parent",
    )
    ckp = CanonicalKnowledgePoint(
        title="Metadata filter retrieval",
        canonical_type="claim",
        canonical_statement="Metadata filters restrict retrieval results.",
        summary="Metadata filters scope retrieval.",
        keywords=["metadata", "filter", "retrieval"],
        concepts=["metadata filter"],
        user_id="default-user",
        confidence=0.86,
    )
    session.add_all([chunk, ckp])
    session.flush()
    ckp_id = ckp.id
    pku = PersonalKnowledgeUnit(
        source_kind="document_chunk",
        source_id=chunk.id,
        unit_type="claim",
        statement="Metadata filter can restrict retrieval results by source or project.",
        normalized_statement="metadata filter restricts retrieval results by source or project",
        normalized_statement_hash="metadata-filter-pku-vector-fail",
        evidence_span="Metadata filter can restrict retrieval results by source or project.",
        keywords=["metadata", "filter"],
        user_id="default-user",
        confidence=0.8,
    )
    session.add(pku)
    session.flush()
    session.add(
        PKUCanonicalLink(
            pku_id=pku.id,
            canonical_id=ckp.id,
            relation_type="about",
            role="evidence",
            confidence=0.8,
            user_id="default-user",
        )
    )
    session.commit()
    session.close()

    monkeypatch.setattr(governed_tool, "_Session", Session)
    monkeypatch.setattr(governed_tool, "search_ckp_vectors", lambda **kwargs: [])

    def fail_pku_vector_search(**kwargs):
        raise RuntimeError("pku vector service unavailable")

    monkeypatch.setattr(governed_tool, "search_pku_vectors", fail_pku_vector_search)

    _terms, bundles, _knowledge = governed_tool._query_governed_evidence("metadata filter", limit=5)

    assert bundles[0]["canonical_id"] == ckp_id
    assert bundles[0]["retrieval_mode"] == "governed_evidence"


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
