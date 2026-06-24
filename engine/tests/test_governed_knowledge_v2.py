"""Governed Knowledge V2 工具测试 — 向量优先检索：chunk 向量召回 → 反查 PKU → 聚合 CKP。"""
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
import engine.app.agent.tools.governed_knowledge_v2 as v2_tool


def _build_db_with_governance():
    """构造含 parent/child chunk + PKU + CKP + Link 的内存 DB。"""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    item = KnowledgeItem(
        title="Metadata filter reference",
        content="Metadata filter can restrict retrieval results by source or project.",
        source_type="manual",
        category="RAG",
        tags=["metadata", "filter"],
        user_id="default-user",
    )
    session.add(item)
    session.flush()

    parent_chunk = KnowledgeChunk(
        item_id=item.id,
        chunk_text="Metadata filter can restrict retrieval results by source or project.",
        chunk_type="parent",
    )
    session.add(parent_chunk)
    session.flush()

    child_chunk = KnowledgeChunk(
        item_id=item.id,
        chunk_text="Metadata filter can restrict retrieval results by source or project.",
        chunk_type="child",
        parent_id=parent_chunk.id,
    )
    session.add(child_chunk)
    session.flush()

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
    session.add(ckp)
    session.flush()

    # PKU 的 source_id = parent_chunk.id（入库时从 parent 抽取）
    doc_pku = PersonalKnowledgeUnit(
        source_kind="document_chunk",
        source_id=parent_chunk.id,
        unit_type="definition",
        statement="Metadata filter can restrict retrieval results by source or project.",
        normalized_statement="metadata filter restricts retrieval results by source or project",
        normalized_statement_hash="doc-hash",
        modality="fact",
        keywords=["metadata", "filter", "retrieval"],
        user_id="default-user",
    )
    session.add(doc_pku)
    session.flush()

    session.add(
        PKUCanonicalLink(
            pku_id=doc_pku.id,
            canonical_id=ckp.id,
            relation_type="defines",
            role="external_reference",
            confidence=0.8,
            user_id="default-user",
        )
    )
    session.commit()
    _child_id = child_chunk.id
    _parent_id = parent_chunk.id
    _ckp_id = ckp.id
    session.close()

    return Session, _child_id, _parent_id, _ckp_id


def test_v2_vector_first_finds_ckp_via_chunk_pku_chain(monkeypatch):
    """向量召回 child chunk → 映射 parent → 反查 PKU → 聚合 CKP → 证据包。"""
    Session, child_chunk_id, parent_chunk_id, ckp_id = _build_db_with_governance()

    # mock 向量检索：返回 child chunk
    fake_hits = [{"chunk_id": child_chunk_id, "item_id": "item-1", "score": 0.92}]
    monkeypatch.setattr(v2_tool, "embed_query", lambda q: [0.1] * 1024)
    monkeypatch.setattr(v2_tool, "search_vectors", lambda emb, top_k=20: fake_hits)
    monkeypatch.setattr(v2_tool, "_ensure_milvus", lambda: True)
    monkeypatch.setattr(v2_tool, "_Session", Session)

    # V2 默认不启用，用 overrides 开启
    ctx = ToolContext(rag_runner=None, citations=[], stats_holder={})
    tools = build_enabled_tools(ctx, overrides={"governed_knowledge_v2": True})
    tool = next(t for t in tools if t.name == "governed_knowledge_v2")

    payload = json.loads(tool.invoke({"query": "metadata filter retrieval", "limit": 5}))

    assert payload["status"] == "success"
    assert payload["retrieval_path"] == "vector_first"
    assert len(payload["chunk_hits"]) == 1
    assert payload["chunk_hits"][0]["chunk_id"] == child_chunk_id

    # CKP 通过 chunk→parent→PKU→CKP 链路被找到
    assert len(payload["canonical_results"]) == 1
    assert payload["canonical_results"][0]["title"] == "Personal knowledge retrieval uses metadata filters"

    # 证据包含 linked_pkus 和 raw_sources
    bundle = payload["evidence_bundle"][0]
    assert len(bundle["linked_pkus"]) >= 1
    assert bundle["linked_pkus"][0]["source_kind"] == "document_chunk"
    assert any(s["source_kind"] == "document_chunk" for s in bundle["raw_sources"])

    assert ctx.stats_holder["governed_knowledge_v2"]["hit_count"] == 1
    assert ctx.stats_holder["governed_knowledge_v2"]["chunk_hit_count"] == 1


def test_v2_no_governance_data_returns_chunk_hits_only(monkeypatch):
    """chunk 命中但无 PKU/CKP 时，仍返回 chunk 命中 + 资产兜底。"""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    item = KnowledgeItem(
        title="Standalone doc",
        content="Some content without governance.",
        source_type="manual",
        user_id="default-user",
    )
    session.add(item)
    session.flush()
    chunk = KnowledgeChunk(item_id=item.id, chunk_text="Some content without governance.", chunk_type="child")
    session.add(chunk)
    session.commit()
    _chunk_id = chunk.id
    _item_id = item.id
    session.close()

    fake_hits = [{"chunk_id": _chunk_id, "item_id": _item_id, "score": 0.75}]
    monkeypatch.setattr(v2_tool, "embed_query", lambda q: [0.1] * 1024)
    monkeypatch.setattr(v2_tool, "search_vectors", lambda emb, top_k=20: fake_hits)
    monkeypatch.setattr(v2_tool, "_ensure_milvus", lambda: True)
    monkeypatch.setattr(v2_tool, "_Session", Session)

    ctx = ToolContext(rag_runner=None, citations=[], stats_holder={})
    tools = build_enabled_tools(ctx, overrides={"governed_knowledge_v2": True})
    tool = next(t for t in tools if t.name == "governed_knowledge_v2")

    payload = json.loads(tool.invoke({"query": "standalone content", "limit": 5}))

    assert payload["status"] == "success"
    assert len(payload["chunk_hits"]) == 1
    assert len(payload["canonical_results"]) == 0
    assert payload["retrieval_path"] == "vector_first"


def test_v2_no_chunk_hits_returns_insufficient(monkeypatch):
    """向量召回和 BM25 回退均为空时返回 insufficient。"""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    monkeypatch.setattr(v2_tool, "embed_query", lambda q: [0.1] * 1024)
    monkeypatch.setattr(v2_tool, "search_vectors", lambda emb, top_k=20: [])
    monkeypatch.setattr(v2_tool, "_ensure_milvus", lambda: False)
    monkeypatch.setattr(v2_tool, "_Session", Session)

    # mock hybrid_search 回退也返回空
    import engine.app.agent.tools.governed_knowledge_v2 as v2_mod
    monkeypatch.setattr("engine.app.retrieval.hybrid.hybrid_search", lambda *a, **k: [])

    ctx = ToolContext(rag_runner=None, citations=[], stats_holder={})
    tools = build_enabled_tools(ctx, overrides={"governed_knowledge_v2": True})
    tool = next(t for t in tools if t.name == "governed_knowledge_v2")

    payload = json.loads(tool.invoke({"query": "nothing matches", "limit": 5}))

    assert payload["status"] == "insufficient"
    assert len(payload["chunk_hits"]) == 0
