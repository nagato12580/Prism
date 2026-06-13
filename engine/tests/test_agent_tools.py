from engine.app.agent.rag.agentic import AgenticRagResult
from engine.app.agent.tools.base import BUILTIN_REGISTRY, ToolContext, build_enabled_tools
import engine.app.agent.tools.knowledge  # noqa: F401
import engine.app.agent.tools.clarify  # noqa: F401
import engine.app.agent.tools.datetime  # noqa: F401
import engine.app.agent.tools.web_search  # noqa: F401


class FakeRagRunner:
    def run(self, query: str):
        return AgenticRagResult(
            status="sufficient",
            summary=f"evidence for {query}",
            sources=[{"chunk_id": "c1", "item_id": "i1", "score": 0.9}],
            iterations=1,
        )


def test_builtin_registry_contains_initial_tools():
    assert {"knowledge_search", "clarify_user", "datetime", "web_search"}.issubset(
        BUILTIN_REGISTRY
    )
    assert BUILTIN_REGISTRY["web_search"].default_enabled is False


def test_build_enabled_tools_skips_disabled_web_search():
    ctx = ToolContext(rag_runner=FakeRagRunner(), citations=[], stats_holder={})
    tools = build_enabled_tools(ctx)
    names = {tool.name for tool in tools}
    assert "knowledge_search" in names
    assert "clarify_user" in names
    assert "datetime" in names
    assert "web_search" not in names


def test_knowledge_search_records_sources_and_stats():
    ctx = ToolContext(rag_runner=FakeRagRunner(), citations=[], stats_holder={})
    tool = next(t for t in build_enabled_tools(ctx) if t.name == "knowledge_search")

    text = tool.invoke({"query": "phase 2"})

    assert "evidence for phase 2" in text
    assert ctx.citations == [{"chunk_id": "c1", "item_id": "i1", "score": 0.9}]
    assert ctx.stats_holder["knowledge_search"]["hit_count"] == 1
    assert ctx.stats_holder["knowledge_search"]["iterations"] == 1
