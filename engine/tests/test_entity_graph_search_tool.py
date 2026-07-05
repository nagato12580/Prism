import json
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./_entity_graph_search_import.db")

from engine.app.agent.tools.base import BUILTIN_REGISTRY, ToolContext
from engine.app.agent.tools.entity_graph_search import (
    EntityGraphSearchService,
    Neo4jEntityQueryClient,
    _alias_keys,
    build,
)


class FakeGraphSearch:
    def search_entity_context(self, query, limit=8):
        return {
            "status": "success",
            "summary": None,
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
                    "title": "OpenViewer Notes",
                    "snippet": "Yanchao Tan authored OpenViewer.",
                    "confidence": 0.7,
                },
                {
                    "source_kind": "document_chunk",
                    "source_id": "chunk-2",
                    "title": "Lower priority source",
                    "snippet": "Yanchao Tan mentioned elsewhere.",
                    "confidence": 0.99,
                }
            ],
            "paths": [
                {"path": ["Yanchao Tan", "AUTHORED", "OpenViewer"]},
                {"path": ["Yanchao Tan", "RELATED_TO", "Other Entity"]},
            ],
            "governed_paths": [
                {
                    "entity_name": "Yanchao Tan",
                    "pku_id": "pku-1",
                    "pku_unit_type": "claim",
                    "ckp_id": "ckp-1",
                    "ckp_title": "OpenViewer authorship",
                    "source_kind": "document_chunk",
                    "source_id": "chunk-1",
                    "support_confidence": 0.9,
                    "ckp_confidence": 0.8,
                },
                {
                    "entity_name": "Yanchao Tan",
                    "pku_id": "pku-2",
                    "pku_unit_type": "rule",
                    "ckp_id": "ckp-2",
                    "ckp_title": "OpenViewer naming rules",
                    "source_kind": "document_chunk",
                    "source_id": "chunk-1",
                    "support_confidence": 0.6,
                    "ckp_confidence": 0.7,
                }
            ],
        }


def test_entity_graph_search_invokes_injected_service_and_records_context():
    ctx = ToolContext(rag_runner=None, citations=[], stats_holder={})
    tool = build(ctx, graph_search=FakeGraphSearch())

    payload = json.loads(tool.invoke({"query": "yanchaotan", "limit": 5}))

    assert payload["status"] == "success"
    assert payload["entities"][0]["canonical_name"] == "Yanchao Tan"
    assert payload["sources"][0]["source_id"] == "chunk-1"
    assert payload["governed_paths"][0]["ckp_title"] == "OpenViewer authorship"
    assert "Found entity context for Yanchao Tan" in payload["summary"]
    assert "Most relevant knowledge points: OpenViewer authorship, OpenViewer naming rules." in payload["summary"]
    assert "Source-backed evidence appears in: OpenViewer Notes, Lower priority source." in payload["summary"]
    assert payload["paths"][0]["path"][1] == "AUTHORED"
    assert ctx.citations == payload["sources"]
    assert ctx.stats_holder["entity_graph_search"]["entity_count"] == 1
    assert ctx.stats_holder["entity_graph_search"]["source_count"] == 2
    assert ctx.stats_holder["entity_graph_search"]["path_count"] == 2
    assert ctx.stats_holder["entity_graph_search"]["governed_path_count"] == 2


def test_entity_graph_search_is_registered_on_tools_import():
    import engine.app.agent.tools  # noqa: F401

    assert "entity_graph_search" in BUILTIN_REGISTRY
    assert BUILTIN_REGISTRY["entity_graph_search"].default_enabled is True


def test_placeholder_entity_graph_service_returns_insufficient_shape():
    class EmptyQueryClient:
        def query_entity_context(self, normalized_keys, limit):
            return {"entities": [], "sources": [], "paths": [], "governed_paths": []}

    payload = EntityGraphSearchService(client=EmptyQueryClient()).search_entity_context("unknown", limit=3)

    assert payload["status"] == "insufficient"
    assert isinstance(payload["summary"], str)
    assert payload["entities"] == []
    assert payload["sources"] == []
    assert payload["paths"] == []


class FakeQueryClient:
    def __init__(self):
        self.calls = []

    def query_entity_context(self, normalized_keys, limit):
        self.calls.append((normalized_keys, limit))
        assert "yanchaotan" in normalized_keys
        return {
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
            "governed_paths": [
                {
                    "entity_name": "Yanchao Tan",
                    "pku_id": "pku-1",
                    "pku_unit_type": "claim",
                    "ckp_id": "ckp-1",
                    "ckp_title": "OpenViewer authorship",
                    "source_kind": "document_chunk",
                    "source_id": "chunk-1",
                }
            ],
        }


def test_entity_graph_search_service_normalizes_query_before_lookup():
    client = FakeQueryClient()
    service = EntityGraphSearchService(client=client)

    payload = service.search_entity_context("Yanchao Tan", limit=5)

    assert payload["status"] == "success"
    assert "yanchaotan" in payload["normalized_keys"]
    assert "tanyanchao" in payload["normalized_keys"]
    assert "yanchaotan" in payload["query_terms"]
    assert payload["governed_paths"][0]["ckp_title"] == "OpenViewer authorship"
    assert client.calls == [(payload["normalized_keys"], 5)]


def test_entity_graph_search_service_returns_insufficient_for_blank_query():
    service = EntityGraphSearchService(client=FakeQueryClient())

    payload = service.search_entity_context("   ", limit=5)

    assert payload["status"] == "insufficient"
    assert payload["entities"] == []
    assert payload["sources"] == []
    assert payload["paths"] == []
    assert payload["governed_paths"] == []
    assert payload["normalized_keys"] == []
    assert payload["query_terms"] == []


def test_entity_graph_search_tool_dedupes_citations_across_invocations():
    ctx = ToolContext(rag_runner=None, citations=[], stats_holder={})
    tool = build(ctx, graph_search=FakeGraphSearch())

    tool.invoke({"query": "yanchaotan", "limit": 5})
    tool.invoke({"query": "yanchaotan", "limit": 5})

    assert ctx.citations == [
        {
            "source_kind": "document_chunk",
            "source_id": "chunk-1",
            "title": "OpenViewer Notes",
            "snippet": "Yanchao Tan authored OpenViewer.",
            "confidence": 0.7,
        },
        {
            "source_kind": "document_chunk",
            "source_id": "chunk-2",
            "title": "Lower priority source",
            "snippet": "Yanchao Tan mentioned elsewhere.",
            "confidence": 0.99,
        },
    ]


def test_alias_keys_preserve_chinese_query():
    keys = _alias_keys(" 谭谚超 ")
    assert "谭谚超" in keys
    assert "tanyanchao" in keys


class FakeNeo4jSession:
    def __init__(self, records=None):
        self.calls = []
        self.records = records or []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def run(self, query, params):
        self.calls.append((query, params))
        return self.records


class FakeNeo4jDriver:
    def __init__(self, records=None):
        self.session_calls = []
        self.session_obj = FakeNeo4jSession(records=records)

    def session(self, **kwargs):
        self.session_calls.append(kwargs)
        return self.session_obj


def test_neo4j_entity_query_client_passes_keys_and_limit_as_params():
    driver = FakeNeo4jDriver()
    client = Neo4jEntityQueryClient(driver=driver, database="neo4j")

    payload = client.query_entity_context(["yanchaotan"], limit=5)

    assert driver.session_calls == [{"database": "neo4j"}]
    assert driver.session_obj.calls
    query, params = driver.session_obj.calls[0]
    assert "$keys" in query
    assert "$limit" in query
    assert params == {"keys": ["yanchaotan"], "limit": 5}
    assert payload == {"entities": [], "sources": [], "paths": [], "governed_paths": []}


def test_neo4j_entity_query_client_shapes_source_evidence_from_records():
    records = [
        {
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
                    "title": "OpenViewer Notes",
                    "evidence_span": "Yanchao Tan authored OpenViewer.",
                    "snippet": None,
                    "confidence": 0.91,
                    "extraction_method": "llm",
                }
            ],
            "paths": [
                {
                    "from": "Yanchao Tan",
                    "relation_type": "AUTHORED",
                    "to": "OpenViewer",
                }
            ],
        }
    ]
    driver = FakeNeo4jDriver(records=records)
    client = Neo4jEntityQueryClient(driver=driver, database="neo4j")

    payload = client.query_entity_context(["yanchaotan"], limit=5)

    assert payload["entities"] == [
        {
            "id": "e1",
            "canonical_name": "Yanchao Tan",
            "entity_type": "person",
        }
    ]
    assert payload["sources"] == [
        {
            "source_kind": "document_chunk",
            "source_id": "chunk-1",
            "title": "OpenViewer Notes",
            "evidence_span": "Yanchao Tan authored OpenViewer.",
            "snippet": "Yanchao Tan authored OpenViewer.",
            "confidence": 0.91,
            "extraction_method": "llm",
        }
    ]
    assert payload["paths"] == [
        {
            "path": ["Yanchao Tan", "AUTHORED", "OpenViewer"],
            "relation_type": "AUTHORED",
        }
    ]
    assert payload["governed_paths"] == []


def test_entity_graph_search_service_returns_success_when_only_governed_paths_exist():
    class GovernedOnlyClient:
        def query_entity_context(self, normalized_keys, limit):
            return {
                "entities": [],
                "sources": [],
                "paths": [],
                "governed_paths": [
                    {
                        "entity_name": "Yanchao Tan",
                        "pku_id": "pku-1",
                        "pku_unit_type": "claim",
                        "ckp_id": "ckp-1",
                        "ckp_title": "OpenViewer authorship",
                        "source_kind": "document_chunk",
                        "source_id": "chunk-1",
                    }
                ],
            }

    payload = EntityGraphSearchService(client=GovernedOnlyClient()).search_entity_context("Yanchao Tan", limit=3)

    assert payload["status"] == "success"
    assert payload["entities"] == []
    assert payload["sources"] == []
    assert payload["paths"] == []
    assert payload["governed_paths"][0]["ckp_title"] == "OpenViewer authorship"
    assert "Found entity context for Yanchao Tan" in payload["summary"]
    assert "Most relevant knowledge points: OpenViewer authorship." in payload["summary"]


def test_entity_graph_search_service_prioritizes_sources_backed_by_governed_paths():
    class RankedClient:
        def query_entity_context(self, normalized_keys, limit):
            return {
                "entities": [{"id": "e1", "canonical_name": "Yanchao Tan", "entity_type": "person"}],
                "sources": [
                    {
                        "source_kind": "document_chunk",
                        "source_id": "chunk-low",
                        "title": "Low",
                        "snippet": "low",
                        "confidence": 0.99,
                    },
                    {
                        "source_kind": "document_chunk",
                        "source_id": "chunk-high",
                        "title": "High",
                        "snippet": "high",
                        "confidence": 0.1,
                    },
                ],
                "paths": [],
                "governed_paths": [
                    {
                        "entity_name": "Yanchao Tan",
                        "pku_id": "p1",
                        "pku_unit_type": "claim",
                        "ckp_id": "c1",
                        "ckp_title": "High value CKP",
                        "source_kind": "document_chunk",
                        "source_id": "chunk-high",
                        "support_confidence": 0.95,
                        "ckp_confidence": 0.9,
                    }
                ],
            }

    payload = EntityGraphSearchService(client=RankedClient()).search_entity_context("Yanchao Tan", limit=5)

    assert payload["sources"][0]["source_id"] == "chunk-high"
    assert payload["governed_paths"][0]["ckp_title"] == "High value CKP"


def test_entity_graph_search_service_query_aware_reranks_governed_paths_by_ckp_title_match():
    class QueryAwareClient:
        def query_entity_context(self, normalized_keys, limit):
            return {
                "entities": [{"id": "e1", "canonical_name": "Yanchao Tan", "entity_type": "person"}],
                "sources": [
                    {
                        "source_kind": "document_chunk",
                        "source_id": "chunk-1",
                        "title": "generic source",
                        "snippet": "generic",
                    }
                ],
                "paths": [],
                "governed_paths": [
                    {
                        "entity_name": "Yanchao Tan",
                        "pku_id": "p1",
                        "pku_unit_type": "claim",
                        "ckp_id": "c1",
                        "ckp_title": "Generic coding practices",
                        "source_kind": "document_chunk",
                        "source_id": "chunk-1",
                        "support_confidence": 0.95,
                        "ckp_confidence": 0.9,
                    },
                    {
                        "entity_name": "Yanchao Tan",
                        "pku_id": "p2",
                        "pku_unit_type": "claim",
                        "ckp_id": "c2",
                        "ckp_title": "OpenViewer naming rules",
                        "source_kind": "document_chunk",
                        "source_id": "chunk-1",
                        "support_confidence": 0.50,
                        "ckp_confidence": 0.6,
                    },
                ],
            }

    payload = EntityGraphSearchService(client=QueryAwareClient()).search_entity_context("OpenViewer", limit=5)

    assert payload["query_terms"][0] == "openviewer"
    assert payload["governed_paths"][0]["ckp_title"] == "OpenViewer naming rules"


def test_entity_graph_search_summary_without_governed_paths_falls_back_to_source_summary():
    class SourceOnlyClient:
        def query_entity_context(self, normalized_keys, limit):
            return {
                "entities": [{"id": "e1", "canonical_name": "Yanchao Tan", "entity_type": "person"}],
                "sources": [
                    {
                        "source_kind": "document_chunk",
                        "source_id": "chunk-1",
                        "title": "OpenViewer Notes",
                        "snippet": "Yanchao Tan authored OpenViewer.",
                    }
                ],
                "paths": [],
                "governed_paths": [],
            }

    payload = EntityGraphSearchService(client=SourceOnlyClient()).search_entity_context("Yanchao Tan", limit=3)

    assert payload["status"] == "success"
    assert payload["summary"] == (
        "Found entity context for Yanchao Tan. "
        "Source-backed evidence appears in: OpenViewer Notes. "
        "Returned 1 source(s) and 0 entity path(s)."
    )


# --- Task 14: yanchaotan / 谭谚超 badcase regression (query layer) ---


def test_yanchaotan_query_resolves_to_yanchao_tan_entity_with_source():
    """Locks the original 'yanchaotan 查无此人' failure at the query layer:
    a compact alias key must normalize to yanchaotan/tanyanchao and resolve to
    the Yanchao Tan entity with a source-backed snippet."""

    class BadcaseClient:
        def __init__(self):
            self.calls = []

        def query_entity_context(self, normalized_keys, limit):
            self.calls.append((normalized_keys, limit))
            assert "yanchaotan" in normalized_keys
            return {
                "entities": [
                    {"id": "e1", "canonical_name": "Yanchao Tan", "entity_type": "person"}
                ],
                "sources": [
                    {
                        "source_kind": "document_chunk",
                        "source_id": "chunk-1",
                        "snippet": "Yanchao Tan authored OpenViewer.",
                        "evidence_span": "Yanchao Tan authored OpenViewer.",
                    }
                ],
                "paths": [
                    {"path": ["Yanchao Tan", "AUTHORED", "OpenViewer"], "relation_type": "AUTHORED"}
                ],
            }

    client = BadcaseClient()
    service = EntityGraphSearchService(client=client)

    payload = service.search_entity_context("yanchaotan", limit=5)

    assert payload["status"] == "success"
    assert payload["normalized_keys"] == ["yanchaotan"]
    assert payload["entities"][0]["canonical_name"] == "Yanchao Tan"
    assert payload["sources"][0]["source_id"] == "chunk-1"
    assert payload["sources"][0]["snippet"] == "Yanchao Tan authored OpenViewer."
    # NOTE: the yanchaotan<->tanyanchao two-word swap is exercised by
    # test_entity_graph_search_service_normalizes_query_before_lookup, which
    # queries the surface "Yanchao Tan" rather than the compact key.
    assert client.calls == [(payload["normalized_keys"], 5)]


def test_chinese_alias_yanchaotan_query_passes_through_normalizer():
    """Chinese surface 谭谚超 must pass through normalization unchanged and reach
    the query client. Pinyin fallback keys are also generated for cross-script
    alias resolution."""
    keys = _alias_keys("谭谚超")
    assert "谭谚超" in keys
    assert "tanyanchao" in keys
