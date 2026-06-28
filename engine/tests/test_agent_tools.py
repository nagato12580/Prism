import json

from engine.app.agent.rag.agentic import AgenticRagResult
from engine.app.agent.tools.base import BUILTIN_REGISTRY, ToolContext, build_enabled_tools
import engine.app.agent.tools.assets as asset_tools
import engine.app.agent.tools.governed_knowledge  # noqa: F401
import engine.app.agent.tools.knowledge  # noqa: F401
import engine.app.agent.tools.page_index  # noqa: F401
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
    assert {
        "knowledge_topic_search",
        "knowledge_evidence_search",
        "knowledge_material_search",
        "raw_document_search",
        "page_index_get_document",
        "page_index_get_document_structure",
        "page_index_get_page_content",
        "governed_knowledge_search",
        "knowledge_search",
        "asset_search",
        "asset_overview",
        "asset_related",
        "memory_search",
        "clarify_user",
        "datetime",
        "web_search",
    }.issubset(
        BUILTIN_REGISTRY
    )
    assert BUILTIN_REGISTRY["web_search"].default_enabled is False


def test_build_enabled_tools_skips_disabled_web_search():
    ctx = ToolContext(rag_runner=FakeRagRunner(), citations=[], stats_holder={})
    tools = build_enabled_tools(ctx)
    names = {tool.name for tool in tools}
    assert "knowledge_topic_search" in names
    assert "knowledge_evidence_search" in names
    assert "knowledge_material_search" in names
    assert "raw_document_search" in names
    assert "page_index_get_document" not in names
    assert "page_index_get_document_structure" not in names
    assert "page_index_get_page_content" not in names
    assert "memory_search" in names
    assert "clarify_user" in names
    assert "datetime" in names
    assert "governed_knowledge_search" not in names
    assert "knowledge_search" not in names
    assert "asset_search" not in names
    assert "asset_overview" not in names
    assert "asset_related" not in names
    assert "web_search" not in names


def test_model_facing_knowledge_tools_have_clear_task_schemas():
    ctx = ToolContext(rag_runner=FakeRagRunner(), citations=[], stats_holder={})
    tools = {tool.name: tool for tool in build_enabled_tools(ctx)}

    topic = tools["knowledge_topic_search"]
    assert "topic" in topic.description.lower()
    assert {"query", "limit"}.issubset(topic.args)

    evidence = tools["knowledge_evidence_search"]
    assert "pku" in evidence.description.lower()
    assert {"query", "evidence_types", "source_kinds", "limit"}.issubset(evidence.args)

    material = tools["knowledge_material_search"]
    assert "materials" in material.description.lower()
    assert {"query", "intent", "limit"}.issubset(material.args)

    raw = tools["raw_document_search"]
    assert "raw" in raw.description.lower()
    assert {"query"}.issubset(raw.args)


def test_knowledge_search_records_sources_and_stats():
    ctx = ToolContext(rag_runner=FakeRagRunner(), citations=[], stats_holder={})
    tool = BUILTIN_REGISTRY["knowledge_search"].builder(ctx)

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
    tool = BUILTIN_REGISTRY["asset_search"].builder(ctx)

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
    assert payload["evidence_items"][0]["evidence_id"].startswith("memory:")
    assert payload["evidence_items"][0]["source_kind"] == "memory"
    assert payload["evidence_items"][0]["source_id"] == payload["memories"][0]["ref_id"]
    assert payload["evidence_items"][0]["excerpt"] == payload["memories"][0]["content"]
    assert ctx.stats_holder["memory_search"]["hit_count"] == 1


def test_memory_search_tool_recalls_confirmed_statements_and_skips_drafts(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from backend.app.database import Base
    from backend.app.models import MemoryStatement
    from backend.app.models.memory import MemoryStatus

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add_all(
        [
            MemoryStatement(
                user_id="default-user",
                content="用户每天早上用 Prism 复习前一天的知识。",
                statement_type="habit",
                temporal_type="stable",
                importance=0.8,
                status=MemoryStatus.CONFIRMED,
            ),
            MemoryStatement(
                user_id="default-user",
                content="用户喜欢深夜用 Prism 整理碎片。",
                statement_type="habit",
                temporal_type="stable",
                importance=0.5,
                status=MemoryStatus.DRAFT,
            ),
            MemoryStatement(
                user_id="default-user",
                content="用户已弃用 Prism 旧版偏好。",
                statement_type="fact",
                temporal_type="stable",
                importance=0.4,
                status=MemoryStatus.SUPERSEDED,
            ),
        ]
    )
    session.commit()
    session.close()
    monkeypatch.setattr(memory_tools, "_Session", Session)

    ctx = ToolContext(rag_runner=FakeRagRunner(), citations=[], stats_holder={})
    tool = next(t for t in build_enabled_tools(ctx) if t.name == "memory_search")

    payload = json.loads(tool.invoke({"query": "复习", "limit": 10}))

    assert payload["status"] == "success"
    titles = [m["title"] for m in payload["memories"]]
    assert any("复习" in t for t in titles)
    assert all("弃用" not in t for t in titles)
    assert all("深夜" not in t for t in titles)
    assert ctx.stats_holder["memory_search"]["hit_count"] == 1


def test_memory_search_recalls_insights_via_vector(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from backend.app.database import Base
    from backend.app.models import MemoryInsight

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    insight = MemoryInsight(
        id="ins-1",
        user_id="default-user",
        theme="技术偏好",
        content="用户偏好轻量、低依赖的技术方案。",
        insight_type="reflection",
        importance=0.85,
    )
    session.add(insight)
    session.commit()
    insight_id = insight.id
    session.close()
    monkeypatch.setattr(memory_tools, "_Session", Session)

    def fake_vector_search(**kw):
        return [{"memory_id": insight_id, "kind": "insight", "memory_type": "技术偏好", "score": 0.88}]

    monkeypatch.setattr(memory_tools, "search_memory_vectors", fake_vector_search)

    ctx = ToolContext(rag_runner=FakeRagRunner(), citations=[], stats_holder={})
    tool = next(t for t in build_enabled_tools(ctx) if t.name == "memory_search")

    payload = json.loads(tool.invoke({"query": "我偏好什么技术", "limit": 5}))

    assert payload["status"] == "success"
    assert len(payload["memories"]) == 1
    hit = payload["memories"][0]
    assert hit["source"] == "insight"
    assert hit["memory_type"] == "insight"
    assert "轻量" in hit["content"]
    assert abs(hit["score"] - 0.88) < 1e-6


def test_memory_search_prefers_vector_recall_and_propagates_score(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from backend.app.database import Base
    from backend.app.models import MemoryEntry, MemoryStatement
    from backend.app.models.memory import MemoryStatus

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    entry = MemoryEntry(
        title="偏好深色主题",
        content="用户偏好深色主题进行夜间阅读。",
        memory_type="preference",
        user_id="default-user",
        importance=0.5,
    )
    statement = MemoryStatement(
        user_id="default-user",
        content="用户每天早上复习前一天的知识。",
        statement_type="habit",
        temporal_type="stable",
        importance=0.9,
        status=MemoryStatus.CONFIRMED,
    )
    session.add_all([entry, statement])
    session.commit()
    statement_id = statement.id
    entry_id = entry.id
    session.close()
    monkeypatch.setattr(memory_tools, "_Session", Session)

    def fake_vector_search(*, text, user_id, top_k):
        return [{"memory_id": statement_id, "kind": "statement", "memory_type": "habit", "score": 0.82}]

    monkeypatch.setattr(memory_tools, "search_memory_vectors", fake_vector_search)

    ctx = ToolContext(rag_runner=FakeRagRunner(), citations=[], stats_holder={})
    tool = next(t for t in build_enabled_tools(ctx) if t.name == "memory_search")

    payload = json.loads(tool.invoke({"query": "复习习惯", "limit": 5}))

    assert payload["status"] == "success"
    assert len(payload["memories"]) == 1
    hit = payload["memories"][0]
    assert "复习" in hit["content"]
    assert hit["source"] == "conversation"
    assert abs(hit["score"] - 0.82) < 1e-6
    ctx = ToolContext(rag_runner=FakeRagRunner(), citations=[], stats_holder={})
    tool = BUILTIN_REGISTRY["knowledge_search"].builder(ctx)

    first_text = tool.invoke({"query": "phase 2"})
    second_text = tool.invoke({"query": "phase 2"})

    assert json.loads(first_text)["sources"] == [
        {"chunk_id": "c1", "item_id": "i1", "score": 0.9}
    ]
    assert json.loads(second_text)["sources"] == [
        {"chunk_id": "c1", "item_id": "i1", "score": 0.9}
    ]
    assert ctx.citations == [{"chunk_id": "c1", "item_id": "i1", "score": 0.9}]
