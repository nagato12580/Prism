import json
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./_deep_search_import.db")

from engine.app.agent.rag.agentic import AgenticRagResult
from engine.app.agent.tools.base import BUILTIN_REGISTRY, ToolContext, build_enabled_tools


class FakeDeepRagRunner:
    def run(self, query: str):
        return AgenticRagResult(
            status="sufficient",
            summary=f"Deep unified evidence for {query}",
            evidence=[
                {
                    "chunk_id": "c1",
                    "item_id": "i1",
                    "text": "MiniMind-O is an open-source Omni model.",
                    "title": "MiniMind-O note",
                }
            ],
            sources=[
                {
                    "chunk_id": "c1",
                    "item_id": "i1",
                    "score": 0.9,
                    "title": "MiniMind-O note",
                    "text": "MiniMind-O is an open-source Omni model.",
                }
            ],
            iterations=2,
        )


def test_deep_knowledge_search_is_registered_but_default_disabled():
    assert "deep_knowledge_search" in BUILTIN_REGISTRY

    ctx = ToolContext(rag_runner=None, citations=[], stats_holder={})
    names = {tool.name for tool in build_enabled_tools(ctx)}

    assert "deep_knowledge_search" not in names


def test_deep_knowledge_search_returns_unified_graphrag_payload():
    ctx = ToolContext(rag_runner=FakeDeepRagRunner(), citations=[], stats_holder={})
    tools = build_enabled_tools(ctx, overrides={"deep_knowledge_search": True})
    tool = next(tool for tool in tools if tool.name == "deep_knowledge_search")

    payload = json.loads(
        tool.invoke({"query": "how does MiniMind-O work", "depth": "standard", "limit": 6})
    )

    assert payload["status"] == "sufficient"
    assert payload["retrieval_path"] == "unified_graphrag_deep_search"
    assert payload["iterations"] == 2
    assert payload["judge"]["status"] == "complete"
    assert payload["judge"]["overall_score"] == 1.0
    assert len(payload["evidence"]) == 1
    assert len(payload["sources"]) == 1
    assert len(payload["evidence_items"]) == 1
    assert payload["trace_steps"]
    assert any(step["agent"] == "UnifiedRetrieval" for step in payload["trace_steps"])
    assert any(step["agent"] == "JudgeAgent" for step in payload["trace_steps"])
    assert ctx.citations == payload["sources"]
    assert ctx.stats_holder["deep_knowledge_search"]["evidence_count"] == len(payload["evidence"])


def test_deep_knowledge_search_handles_missing_runner():
    ctx = ToolContext(rag_runner=None, citations=[], stats_holder={})
    tools = build_enabled_tools(ctx, overrides={"deep_knowledge_search": True})
    tool = next(tool for tool in tools if tool.name == "deep_knowledge_search")

    payload = json.loads(tool.invoke({"query": "missing"}))

    assert payload["status"] == "insufficient"
    assert payload["sources"] == []
    assert payload["evidence"] == []
    assert payload["evidence_items"] == []
