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
    PersonalAssetItem,
    PersonalKnowledgeUnit,
)
from engine.app.agent.tools.base import ToolContext, build_enabled_tools
import engine.app.agent.tools.governed_knowledge as governed_tool
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

    asset = PersonalAssetItem(
        raw_text="我认为个人知识库需要 metadata filter 辅助检索。",
        title="个人知识库检索观点",
        body="我认为个人知识库需要 metadata filter 辅助检索。",
        summary="个人知识库需要 metadata filter。",
        asset_kind="opinion",
        category="RAG",
        tags=["metadata", "filter"],
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
    session.add_all([asset, item])
    session.flush()
    chunk = KnowledgeChunk(
        item_id=item.id,
        chunk_text="Metadata filter can restrict retrieval results by source or project.",
        chunk_type="parent",
    )
    ckp = CanonicalKnowledgePoint(
        title="个人知识库适合 metadata filter 辅助检索",
        canonical_type="claim",
        canonical_statement="个人知识库适合 metadata filter 辅助检索。",
        summary="个人观点和文档证据共同支持 metadata filter。",
        keywords=["个人知识库", "metadata", "filter", "检索"],
        concepts=["metadata", "filter"],
        user_id="default-user",
        confidence=0.86,
    )
    session.add_all([chunk, ckp])
    session.flush()
    asset_pku = PersonalKnowledgeUnit(
        source_kind="personal_asset_item",
        source_id=asset.id,
        unit_type="claim",
        statement="个人知识库需要 metadata filter 辅助检索。",
        normalized_statement="个人知识库需要 metadata filter 辅助检索",
        normalized_statement_hash="asset-hash",
        modality="opinion",
        keywords=["个人知识库", "metadata", "filter"],
        user_id="default-user",
    )
    doc_pku = PersonalKnowledgeUnit(
        source_kind="document_chunk",
        source_id=chunk.id,
        unit_type="definition",
        statement="Metadata filter can restrict retrieval results by source or project.",
        normalized_statement="Metadata filter restricts retrieval results by source or project",
        normalized_statement_hash="doc-hash",
        modality="fact",
        keywords=["metadata", "filter", "retrieval"],
        user_id="default-user",
    )
    session.add_all([asset_pku, doc_pku])
    session.flush()
    session.add_all(
        [
            PKUCanonicalLink(
                pku_id=asset_pku.id,
                canonical_id=ckp.id,
                relation_type="same_as",
                role="personal_claim",
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
    tool = next(t for t in build_enabled_tools(ctx) if t.name == "governed_knowledge_search")

    payload = json.loads(tool.invoke({"query": "个人知识库 metadata filter 检索", "limit": 5}))

    assert payload["status"] == "success"
    assert payload["canonical_results"][0]["title"] == "个人知识库适合 metadata filter 辅助检索"
    bundle = payload["evidence_bundle"][0]
    assert {pku["role"] for pku in bundle["linked_pkus"]} == {"personal_claim", "external_reference"}
    assert {source["source_kind"] for source in bundle["raw_sources"]} == {"personal_asset_item", "document_chunk"}
    assert len(ctx.citations) == 2
    assert ctx.stats_holder["governed_knowledge_search"]["hit_count"] == 1
