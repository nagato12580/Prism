import json
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./_entity_graph_search_import.db")

from engine.app.agent.tools.base import BUILTIN_REGISTRY, ToolContext
from engine.app.agent.tools.entity_graph_search import EntityGraphSearchService, build


class FakeGraphSearch:
    def search_entity_context(self, query, limit=8):
        return {
            "status": "success",
            "summary": "Found entity Yanchao Tan with 1 source.",
            "entities": [
                {
                    "id": "e1",
                    "canonical_name": "Yanchao Tan",
                    "entity_type": "person",
                }
            ],
            "sources": [
                {
                    "source_kind": "document_chunk",
                    "source_id": "chunk-1",
                    "snippet": "Yanchao Tan authored OpenViewer.",
                }
            ],
            "paths": [{"path": ["Yanchao Tan", "AUTHORED", "OpenViewer"]}],
        }


def test_entity_graph_search_invokes_injected_service_and_records_context():
    ctx = ToolContext(rag_runner=None, citations=[], stats_holder={})
    tool = build(ctx, graph_search=FakeGraphSearch())

    payload = json.loads(tool.invoke({"query": "yanchaotan", "limit": 5}))

    assert payload["status"] == "success"
    assert payload["entities"][0]["canonical_name"] == "Yanchao Tan"
    assert payload["sources"][0]["source_id"] == "chunk-1"
    assert ctx.citations == payload["sources"]
    assert ctx.stats_holder["entity_graph_search"]["entity_count"] == 1
    assert ctx.stats_holder["entity_graph_search"]["source_count"] == 1
    assert ctx.stats_holder["entity_graph_search"]["path_count"] == 1


def test_entity_graph_search_is_registered_on_tools_import():
    import engine.app.agent.tools  # noqa: F401

    assert "entity_graph_search" in BUILTIN_REGISTRY
    assert BUILTIN_REGISTRY["entity_graph_search"].default_enabled is True


def test_placeholder_entity_graph_service_returns_insufficient_shape():
    payload = EntityGraphSearchService().search_entity_context("unknown", limit=3)

    assert payload["status"] == "insufficient"
    assert isinstance(payload["summary"], str)
    assert payload["entities"] == []
    assert payload["sources"] == []
    assert payload["paths"] == []
