import json
import os
import pytest
from pydantic import ValidationError

os.environ.setdefault("DATABASE_URL", "sqlite:///./_deep_search_import.db")

from engine.app.agent.rag.agentic import AgenticRagResult
from engine.app.agent.tools.base import BUILTIN_REGISTRY, ToolContext, build_enabled_tools
from engine.app.api.chat import ChatRequest


class FakeDeepRagRunner:
    def __init__(self):
        self.calls = []

    def run(self, query: str, *, config=None):
        self.calls.append((query, config))
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
    rag_runner = FakeDeepRagRunner()
    ctx = ToolContext(rag_runner=rag_runner, citations=[], stats_holder={})
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
    query, config = rag_runner.calls[0]
    assert query == "how does MiniMind-O work"
    assert config.mode == "deep"
    assert config.top_k == 6
    assert config.graph_hops == 2
    assert config.max_iterations == 3


def test_deep_knowledge_search_depth_changes_real_run_controls():
    rag_runner = FakeDeepRagRunner()
    ctx = ToolContext(rag_runner=rag_runner, citations=[], stats_holder={})
    tool = next(
        tool
        for tool in build_enabled_tools(ctx, overrides={"deep_knowledge_search": True})
        if tool.name == "deep_knowledge_search"
    )

    tool.invoke({"query": "quick", "depth": "quick", "limit": 3})
    tool.invoke({"query": "deep", "depth": "deep", "limit": 30})

    quick = rag_runner.calls[0][1]
    deep = rag_runner.calls[1][1]
    assert (quick.mode, quick.top_k, quick.graph_hops, quick.max_iterations) == ("deep", 3, 1, 1)
    assert (deep.mode, deep.top_k, deep.graph_hops, deep.max_iterations) == ("deep", 30, 3, 5)


def test_deep_knowledge_search_handles_missing_runner():
    ctx = ToolContext(rag_runner=None, citations=[], stats_holder={})
    tools = build_enabled_tools(ctx, overrides={"deep_knowledge_search": True})
    tool = next(tool for tool in tools if tool.name == "deep_knowledge_search")

    payload = json.loads(tool.invoke({"query": "missing"}))

    assert payload["status"] == "insufficient"
    assert payload["sources"] == []
    assert payload["evidence"] == []
    assert payload["evidence_items"] == []


def test_chat_request_validates_deep_search_control_boundaries():
    default_request = ChatRequest(query="q")
    assert default_request.rag_max_iterations == 10

    request = ChatRequest(
        query="q",
        deep_search_depth="deep",
        deep_search_top_k=30,
        graph_hops=3,
        rag_max_iterations=10,
    )
    assert request.deep_search_depth == "deep"

    for field, value in (
        ("deep_search_depth", "unbounded"),
        ("deep_search_top_k", 31),
        ("graph_hops", 4),
        ("rag_max_iterations", 11),
    ):
        with pytest.raises(ValidationError):
            ChatRequest(query="q", **{field: value})
