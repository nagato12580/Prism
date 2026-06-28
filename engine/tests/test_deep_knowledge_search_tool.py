import json
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
    PersonalKnowledgeUnit,
)
from engine.app.agent.tools.base import BUILTIN_REGISTRY, ToolContext, build_enabled_tools
import engine.app.agent.tools.deep_knowledge_search as deep_tool


def _build_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    item = KnowledgeItem(
        title="Deep search design",
        content="Deep search uses scope-first retrieval and judge-directed follow-up.",
        source_type="document",
        user_id="default-user",
    )
    session.add(item)
    session.flush()
    chunk = KnowledgeChunk(
        item_id=item.id,
        chunk_text="Deep search uses scope-first retrieval and judge-directed follow-up.",
        chunk_type="parent",
    )
    session.add(chunk)
    session.flush()
    ckp = CanonicalKnowledgePoint(
        title="Deep search uses scope first",
        canonical_type="method",
        canonical_statement="Deep search should scope CKP and PKU before chunk search.",
        summary="The searcher starts with governed scope and deepens evidence only when needed.",
        keywords=["deep", "search", "scope", "judge"],
        concepts=["deep search"],
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
        statement="Deep search uses scope-first retrieval and judge-directed follow-up.",
        normalized_statement="deep search scope first judge directed followup",
        normalized_statement_hash="pku-deep",
        evidence_span="Deep search uses scope-first retrieval and judge-directed follow-up.",
        keywords=["deep", "scope", "judge"],
        user_id="default-user",
        status="active",
        confidence=0.88,
    )
    session.add(pku)
    session.flush()
    session.add(
        PKUCanonicalLink(
            pku_id=pku.id,
            canonical_id=ckp.id,
            relation_type="supports",
            confidence=0.86,
            user_id="default-user",
        )
    )
    session.commit()
    session.close()
    return Session


def test_deep_knowledge_search_is_registered_but_default_disabled():
    assert "deep_knowledge_search" in BUILTIN_REGISTRY

    ctx = ToolContext(rag_runner=None, citations=[], stats_holder={})
    names = {tool.name for tool in build_enabled_tools(ctx)}

    assert "deep_knowledge_search" not in names


def test_deep_knowledge_search_returns_judged_evidence(monkeypatch):
    Session = _build_db()
    monkeypatch.setattr(deep_tool, "_Session", Session)

    ctx = ToolContext(rag_runner=None, citations=[], stats_holder={})
    tools = build_enabled_tools(ctx, overrides={"deep_knowledge_search": True})
    tool = next(tool for tool in tools if tool.name == "deep_knowledge_search")

    payload = json.loads(
        tool.invoke({"query": "how does deep search use scope and judge", "depth": "standard", "limit": 6})
    )

    assert payload["status"] in {"success", "partial"}
    assert payload["retrieval_path"] == "scope_first_deep_search"
    assert payload["iterations"] >= 1
    assert payload["judge"]["overall_score"] > 0
    assert len(payload["evidence"]) >= 1
    assert len(payload["sources"]) >= 1
    assert len(payload["trace_steps"]) >= 3
    assert any(step["agent"] == "SearcherAgent" for step in payload["trace_steps"])
    assert any(step["agent"] == "JudgeAgent" for step in payload["trace_steps"])
    assert all("label" in step and "detail" in step for step in payload["trace_steps"])
    assert payload["stats"]["trace_step_count"] == len(payload["trace_steps"])
    assert payload["stats"]["deep_trace_steps"] == payload["trace_steps"]
    assert ctx.citations == payload["sources"]
    assert ctx.stats_holder["deep_knowledge_search"]["evidence_count"] == len(payload["evidence"])
