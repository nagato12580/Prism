import json

from engine.app.agent.rag.agentic import AgenticRagResult
from engine.app.agent.tools.base import BUILTIN_REGISTRY, ToolContext, build_enabled_tools
import engine.app.agent.tools.assets as asset_tools
import engine.app.agent.tools.governed_knowledge  # noqa: F401
import engine.app.agent.tools.knowledge  # noqa: F401
import engine.app.agent.tools.memory as memory_tools
import engine.app.agent.tools.clarify  # noqa: F401
import engine.app.agent.tools.datetime  # noqa: F401
import engine.app.agent.tools.web_search  # noqa: F401


class FakeRagRunner:
    def run(self, query: str):
        return AgenticRagResult(
            status="sufficient",
            summary=f"evidence for {query}",
            evidence=[{"chunk_id": "c1", "text": "hello"}],
            sources=[{"chunk_id": "c1", "item_id": "i1", "score": 0.9}],
            iterations=1,
        )


def test_builtin_registry_contains_initial_tools():
    assert {"governed_knowledge_search", "knowledge_search", "asset_search", "asset_overview", "asset_related", "memory_search", "clarify_user", "datetime", "web_search"}.issubset(
        BUILTIN_REGISTRY
    )
    assert BUILTIN_REGISTRY["web_search"].default_enabled is False


def test_build_enabled_tools_skips_disabled_web_search():
    ctx = ToolContext(rag_runner=FakeRagRunner(), citations=[], stats_holder={})
    tools = build_enabled_tools(ctx)
    names = {tool.name for tool in tools}
    assert "governed_knowledge_search" in names
    assert "knowledge_search" in names
    assert "asset_search" in names
    assert "asset_overview" in names
    assert "asset_related" in names
    assert "memory_search" in names
    assert "clarify_user" in names
    assert "datetime" in names
    assert "web_search" not in names


def test_knowledge_search_records_sources_and_stats():
    ctx = ToolContext(rag_runner=FakeRagRunner(), citations=[], stats_holder={})
    tool = next(t for t in build_enabled_tools(ctx) if t.name == "knowledge_search")

    text = tool.invoke({"query": "phase 2"})
    payload = json.loads(text)

    assert payload["summary"] == "evidence for phase 2"
    assert payload["evidence"] == [{"chunk_id": "c1", "text": "hello"}]
    assert ctx.citations == [{"chunk_id": "c1", "item_id": "i1", "score": 0.9}]
    assert ctx.stats_holder["knowledge_search"]["hit_count"] == 1
    assert ctx.stats_holder["knowledge_search"]["iterations"] == 1


def test_asset_search_tool_returns_confirmed_assets(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from backend.app.database import Base
    from backend.app.models import PersonalAssetItem

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add(
        PersonalAssetItem(
            raw_text="Agent 需要一个工具注册表。",
            title="Agent 工具注册表参考",
            body="Agent 需要一个工具注册表。",
            summary="工具注册表资源。",
            asset_kind="resource",
            category="Agent 架构",
            tags=["Agent", "工具"],
            user_id="default-user",
            status="confirmed",
        )
    )
    session.commit()
    session.close()
    monkeypatch.setattr(asset_tools, "_Session", Session)

    ctx = ToolContext(rag_runner=FakeRagRunner(), citations=[], stats_holder={})
    tool = next(t for t in build_enabled_tools(ctx) if t.name == "asset_search")

    payload = json.loads(tool.invoke({"query": "Agent", "limit": 5}))

    assert payload["status"] == "success"
    assert payload["assets"][0]["title"] == "Agent 工具注册表参考"
    assert ctx.stats_holder["asset_search"]["hit_count"] == 1


def test_memory_search_tool_returns_confirmed_memories(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from backend.app.database import Base
    from backend.app.models import MemoryEntry

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add(
        MemoryEntry(
            title="偏好轻量方案",
            content="用户希望 Prism 第一版先轻量实现。",
            memory_type="preference",
            category="产品偏好",
            tags=["Prism"],
            user_id="default-user",
            importance=0.9,
        )
    )
    session.commit()
    session.close()
    monkeypatch.setattr(memory_tools, "_Session", Session)

    ctx = ToolContext(rag_runner=FakeRagRunner(), citations=[], stats_holder={})
    tool = next(t for t in build_enabled_tools(ctx) if t.name == "memory_search")

    payload = json.loads(tool.invoke({"query": "Prism", "limit": 5}))

    assert payload["status"] == "success"
    assert payload["memories"][0]["title"] == "偏好轻量方案"
    assert ctx.stats_holder["memory_search"]["hit_count"] == 1


def test_knowledge_search_dedupes_shared_citations_across_calls():
    ctx = ToolContext(rag_runner=FakeRagRunner(), citations=[], stats_holder={})
    tool = next(t for t in build_enabled_tools(ctx) if t.name == "knowledge_search")

    first_text = tool.invoke({"query": "phase 2"})
    second_text = tool.invoke({"query": "phase 2"})

    assert json.loads(first_text)["sources"] == [
        {"chunk_id": "c1", "item_id": "i1", "score": 0.9}
    ]
    assert json.loads(second_text)["sources"] == [
        {"chunk_id": "c1", "item_id": "i1", "score": 0.9}
    ]
    assert ctx.citations == [{"chunk_id": "c1", "item_id": "i1", "score": 0.9}]
