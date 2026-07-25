import os
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "sqlite:///./_unified_test.db"

from unittest.mock import patch

import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base
from backend.app.models import KnowledgeChunk, KnowledgeItem, PersonalAssetUnit
from engine.app.retrieval.unified import unified_search, make_unified_search
from engine.app.retrieval.contracts import SearchScope

SCOPE = SearchScope(tenant_id="tenant-test", kb_uid="kb-test", index_generation="gen-test", graph_generation="graph-test")


@pytest.fixture(autouse=True)
def _stub_query_embedding(monkeypatch):
    monkeypatch.setattr("engine.app.retrieval.unified.embed_query", lambda query: [0.1])


def _recalled(*hits):
    rows = []
    for hit in hits:
        metadata = {key: value for key, value in hit.items() if key not in {"chunk_id", "item_id", "file_uid", "score"}}
        channel = "graph" if metadata.get("source_marker") else "dense"
        rows.append({
            "chunk_uid": hit["chunk_id"], "item_id": hit.get("item_id", ""),
            "file_uid": hit.get("file_uid", ""), "rrf_score": hit.get("score", 1.0),
            "channels": {channel: {"raw_rank": 1, "raw_score": hit.get("score", 1.0)}},
            "metadata": metadata,
        })
    return {"status": "ok" if rows else "no_hits", "results": rows, "channels": []}


def test_production_graph_client_wires_only_scoped_graph_search(monkeypatch):
    from engine.app.retrieval import unified as module
    from engine.app.retrieval.contracts import ChannelResult
    scope = SearchScope(tenant_id="t", kb_uid="k", index_generation="g", graph_generation="gg")
    seen = {}
    class ProductionGraph:
        def _execute_read(self, *args, **kwargs): return []
    monkeypatch.setattr(module, "embed_query", lambda query: [0.1])
    monkeypatch.setattr(module, "vector_search", lambda *a, **k: ChannelResult.ok("dense", []))
    monkeypatch.setattr(module, "es_fulltext_search", lambda *a, **k: ChannelResult.ok("bm25", []))
    monkeypatch.setattr(module, "graph_search", lambda query, actual_scope, client, top_k, hops: seen.update(scope=actual_scope, client=client) or ChannelResult.ok("graph", []))
    monkeypatch.setattr(module, "match_seed_entities", lambda *a, **k: (_ for _ in ()).throw(AssertionError("legacy graph path called")))
    graph = ProductionGraph()
    module.unified_search("q", 5, db=None, graph_client=graph, scope=scope)
    assert seen == {"scope": scope, "client": graph}


def _hybrid(query, scope, top_k, **kw):
    # pretend hybrid returns 2 chunks
    return [{"chunk_id": "c_vec", "item_id": "i1", "score": 0.6},
            {"chunk_id": "c_bm",  "item_id": "i1", "score": 0.4}]


def _recall_merge(*args, **kwargs):
    return _recalled(
        {"chunk_id": "c_vec", "item_id": "i1", "score": 0.6},
        {"chunk_id": "c_bm", "item_id": "i1", "score": 0.4},
        {"chunk_id": "c_graph", "item_id": "i2", "score": 0.5, "source_marker": "graph_1hop"},
    )


def _expand(db, graph, seeds, mode, hops, max_candidates, **kw):
    return [{"chunk_id": "c_graph", "item_id": "i2", "source_marker": "graph_1hop"}]


def _rerank(query, cands, top_n, **kw):
    # move graph candidate to top
    cands = sorted(cands, key=lambda c: c["chunk_id"] != "c_graph")
    for c in cands: c["source_marker"] = "rerank"
    return cands[:top_n]


@patch("engine.app.retrieval.unified.expand_candidates", _expand)
@patch("engine.app.retrieval.unified.rerank", _rerank)
@patch("engine.app.retrieval.unified.recall", _recall_merge)
@patch("engine.app.retrieval.unified.match_seed_entities", lambda db, q, **k: ["e1"])
def test_unified_search_merges_and_reranks():
    out = unified_search("q", top_k=5, mode="fast", db=object(), graph_client=object(), scope=SCOPE)
    ids = [o["chunk_id"] for o in out]
    assert set(ids) == {"c_vec", "c_bm", "c_graph"}   # hybrid + graph merged
    assert ids[0] == "c_graph"                          # rerank put graph hit first
    graph_hit = next(item for item in out if item["chunk_id"] == "c_graph")
    assert graph_hit["source_marker"] == "graph_1hop"
    assert graph_hit["graph_rag"]["explain"]["source_marker"] == "graph_1hop"


def test_make_unified_search_returns_scoped_search_fn(monkeypatch):
    captured = {}

    def _fake_unified_search(query, top_k, **kwargs):
        captured["query"] = query
        captured["top_k"] = top_k
        captured["mode"] = kwargs["mode"]
        captured["topic_ids"] = kwargs["topic_ids"]
        return [{"chunk_id": "c1", "item_id": "i1", "score": 1.0}]

    monkeypatch.setattr("engine.app.retrieval.unified.unified_search", _fake_unified_search)

    scoped = make_unified_search(mode="fast", topic_ids=["t1"], source_types=None, allowed_item_ids=None)
    out = scoped("q", 5)

    assert out == [{"chunk_id": "c1", "item_id": "i1", "score": 1.0}]
    assert captured == {"query": "q", "top_k": 5, "mode": "fast", "topic_ids": ["t1"]}


def test_make_unified_search_forwards_configured_graph_hops_once(monkeypatch):
    calls = []

    def _fake_unified_search(query, top_k, **kwargs):
        calls.append((query, top_k, kwargs["mode"], kwargs["graph_hops"]))
        return []

    monkeypatch.setattr("engine.app.retrieval.unified.unified_search", _fake_unified_search)
    scoped = make_unified_search(mode="fast", scope=SCOPE)

    scoped("q", 7, mode="deep", graph_hops=3)

    assert calls == [("q", 7, "deep", 3)]


def test_build_agent_runner_uses_unified_search_with_mode(monkeypatch):
    import engine.app.chat.answer as ans
    captured = {}
    def _fake_make(mode, **kw):
        captured["mode"] = mode
        def _scoped(query, top_k): return [{"chunk_id": "c1", "item_id": "i1", "score": 1.0}]
        return _scoped
    monkeypatch.setattr(ans, "make_unified_search", _fake_make)
    # avoid real model/tools
    monkeypatch.setattr(ans, "AgenticRagRunner", lambda **kw: type("R", (), {"run": lambda self, q: None})())
    monkeypatch.setattr(ans, "build_enabled_tools", lambda ctx, overrides=None: [])
    monkeypatch.setattr(ans, "create_chat_model", lambda s: object())

    ans.build_agent_runner(topic_id=None, source_types=None, deep_search_enabled=False, clarify_depth=0)
    assert captured["mode"] == "fast"
    ans.build_agent_runner(topic_id=None, source_types=None, deep_search_enabled=True, clarify_depth=0)
    assert captured["mode"] == "deep"


def _hybrid_overlap(query, scope, top_k, **kw):
    # same chunk appears in both hybrid and graph
    return [{"chunk_id": "c_shared", "item_id": "i1", "score": 0.8},
            {"chunk_id": "c_only",  "item_id": "i1", "score": 0.5}]


def _recall_overlap(*args, **kwargs):
    result = _recalled(
        {"chunk_id": "c_shared", "item_id": "i1", "score": 0.8, "source_marker": "graph_1hop"},
        {"chunk_id": "c_only", "item_id": "i1", "score": 0.5},
        {"chunk_id": "c_graph", "item_id": "i2", "score": 0.4, "source_marker": "graph_1hop"},
    )
    result["results"][0]["channels"]["dense"] = {"raw_rank": 1, "raw_score": 0.8}
    return result


def _expand_overlap(db, graph, seeds, mode, hops, max_candidates, **kw):
    return [{"chunk_id": "c_shared", "item_id": "i1", "source_marker": "graph_1hop"},
            {"chunk_id": "c_graph", "item_id": "i2", "source_marker": "graph_1hop"}]


@patch("engine.app.retrieval.unified.expand_candidates", _expand_overlap)
@patch("engine.app.retrieval.unified.rerank", lambda q, c, **kw: c)  # no-op rerank
@patch("engine.app.retrieval.unified.recall", _recall_overlap)
@patch("engine.app.retrieval.unified.match_seed_entities", lambda db, q, **k: ["e1"])
def test_unified_search_merges_markers_when_chunk_overlaps():
    """When a chunk appears in both hybrid and graph results, source_marker is merged."""
    out = unified_search("q", top_k=10, mode="fast", db=object(), graph_client=object(), scope=SCOPE)
    by_id = {o["chunk_id"]: o for o in out}
    # c_shared: appears in both → marker should show graph contribution
    assert "c_shared" in by_id
    shared = by_id["c_shared"]
    assert shared["source_marker"] and "graph_1hop" in shared["source_marker"]
    assert shared["graph_rag"]["explain"]["source_marker"] == shared["source_marker"]
    # c_graph: only in graph → marker unchanged
    assert by_id["c_graph"]["source_marker"] == "graph_1hop"
    # c_only: only in hybrid → no marker
    assert by_id["c_only"].get("source_marker") is None


def _expand_overlap_with_graph_rag(db, graph, seeds, mode, hops, max_candidates, **kw):
    return [
        {
            "chunk_id": "c_shared",
            "item_id": "i1",
            "source_marker": "graph_1hop+community",
            "path": [
                {
                    "source_marker": "graph_1hop",
                    "matched_entity_ids": ["e1"],
                    "steps": [
                        {"node_id": "e1", "node_type": "entity"},
                        {"edge_type": "GRAPH_1HOP", "evidence_type": "INFERRED"},
                        {"node_id": "document_chunk:c_shared", "node_type": "source"},
                    ],
                },
                {
                    "source_marker": "community",
                    "matched_entity_ids": ["e2"],
                    "steps": [
                        {"node_id": "e2", "node_type": "entity"},
                        {"edge_type": "COMMUNITY", "evidence_type": "INFERRED"},
                        {"node_id": "document_chunk:c_shared", "node_type": "source"},
                    ],
                },
            ],
            "explain": {
                "matched_entity_ids": ["e1", "e2"],
                "why": "2 graph expansion routes reached source",
                "evidence_type": "INFERRED",
                "source_markers": ["graph_1hop", "community"],
                "route_count": 2,
            },
        }
    ]


@patch("engine.app.retrieval.unified.expand_candidates", _expand_overlap_with_graph_rag)
@patch("engine.app.retrieval.unified.rerank", lambda q, c, **kw: c)
@patch("engine.app.retrieval.unified.recall", lambda *a, **kw: _recalled({
    "chunk_id": "c_shared", "item_id": "i1", "score": 0.8, "text": "Hybrid evidence",
    "source_marker": "graph_1hop+community", "path": _expand_overlap_with_graph_rag(None, None, None, None, None, None)[0]["path"],
    "explain": _expand_overlap_with_graph_rag(None, None, None, None, None, None)[0]["explain"],
}))
@patch("engine.app.retrieval.unified.match_seed_entities", lambda db, q, **k: ["e1"])
def test_unified_search_preserves_graph_rag_metadata_when_hybrid_and_graph_overlap():
    out = unified_search("q", top_k=10, mode="fast", db=object(), graph_client=object(), scope=SCOPE)

    assert len(out) == 1
    assert out[0]["chunk_id"] == "c_shared"
    assert out[0]["source_marker"] == "graph_1hop+community"
    assert len(out[0]["graph_rag"]["path"]) == 2
    assert out[0]["graph_rag"]["path"] == [
        {
            "source_marker": "graph_1hop",
            "matched_entity_ids": ["e1"],
            "steps": [
                {"node_id": "e1", "node_type": "entity"},
                {"edge_type": "GRAPH_1HOP", "evidence_type": "INFERRED"},
                {"node_id": "document_chunk:c_shared", "node_type": "source"},
            ],
        },
        {
            "source_marker": "community",
            "matched_entity_ids": ["e2"],
            "steps": [
                {"node_id": "e2", "node_type": "entity"},
                {"edge_type": "COMMUNITY", "evidence_type": "INFERRED"},
                {"node_id": "document_chunk:c_shared", "node_type": "source"},
            ],
        },
    ]
    assert out[0]["graph_rag"]["explain"] == {
        "matched_entity_ids": ["e1", "e2"],
        "why": "2 graph expansion routes reached source",
        "evidence_type": "INFERRED",
        "source_marker": "graph_1hop+community",
        "source_markers": ["graph_1hop", "community"],
        "route_count": 2,
    }


@patch("engine.app.retrieval.unified.expand_candidates", lambda *args, **kwargs: [
    {
        "chunk_id": "c_graph",
        "item_id": "i2",
        "source_marker": "graph_1hop",
        "path": [
            {
                "source_marker": "graph_1hop",
                "matched_entity_ids": ["e1"],
                "steps": [
                    {"node_id": "e1", "node_type": "entity"},
                    {"edge_type": "GRAPH_1HOP", "evidence_type": "INFERRED"},
                    {"node_id": "document_chunk:c_graph", "node_type": "source"},
                ],
            }
        ],
        "explain": {
            "matched_entity_ids": ["e1"],
            "why": "graph_1hop expansion reached source",
            "evidence_type": "INFERRED",
        },
    }
])
@patch("engine.app.retrieval.unified.rerank", _rerank)
@patch("engine.app.retrieval.unified.recall", lambda *a, **kw: _recalled({
    "chunk_id": "c_graph", "item_id": "i2", "score": 1.0, "source_marker": "graph_1hop",
    "path": [{"source_marker": "graph_1hop", "matched_entity_ids": ["e1"], "steps": [
        {"node_id": "e1", "node_type": "entity"}, {"edge_type": "GRAPH_1HOP", "evidence_type": "INFERRED"},
        {"node_id": "document_chunk:c_graph", "node_type": "source"}]}],
    "explain": {"matched_entity_ids": ["e1"], "why": "graph_1hop expansion reached source", "evidence_type": "INFERRED"},
}))
@patch("engine.app.retrieval.unified.match_seed_entities", lambda db, q, **k: ["e1"])
def test_unified_search_restores_graph_marker_after_rerank_override():
    out = unified_search("q", top_k=5, mode="fast", db=object(), graph_client=object(), scope=SCOPE)

    assert len(out) == 1
    assert out[0]["source_marker"] == "graph_1hop"
    assert out[0]["graph_rag"]["explain"]["source_marker"] == "graph_1hop"
    assert out[0]["graph_rag"]["path"] == [
        {
            "source_marker": "graph_1hop",
            "matched_entity_ids": ["e1"],
            "steps": [
                {"node_id": "e1", "node_type": "entity"},
                {"edge_type": "GRAPH_1HOP", "evidence_type": "INFERRED"},
                {"node_id": "document_chunk:c_graph", "node_type": "source"},
            ],
        }
    ]


def _test_session():
    engine = create_engine("sqlite:///:memory:")
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(engine)
    return TestingSessionLocal()


def _expand_asset_unit(db, graph, seeds, mode, hops, max_candidates, **kw):
    return [
        {
            "source_kind": "personal_asset_unit",
            "source_id": "unit-1",
            "source_marker": "graph_1hop",
        }
    ]


@patch("engine.app.retrieval.unified.expand_candidates", _expand_asset_unit)
@patch("engine.app.retrieval.unified.rerank", lambda q, c, **kw: c)
@patch("engine.app.retrieval.unified.recall", lambda *a, **kw: _recalled({
    "chunk_id": "", "item_id": "", "score": 1.0, "source_kind": "personal_asset_unit",
    "source_id": "unit-1", "source_marker": "graph_1hop",
}))
@patch("engine.app.retrieval.unified.match_seed_entities", lambda db, q, **k: ["e1"])
def test_unified_search_preserves_personal_asset_unit_graph_hits():
    db = _test_session()
    try:
        db.add(
            PersonalAssetUnit(
                id="unit-1",
                user_id="default-user",
                title="LoRA learning note",
                content="LoRA reduces trainable parameters for adaptation.",
                summary="A short note about LoRA.",
                status="confirmed",
            )
        )
        db.commit()

        out = unified_search("LoRA", top_k=5, mode="fast", db=db, graph_client=object(), scope=SCOPE)
    finally:
        db.close()

    assert len(out) == 1
    assert out[0]["source_kind"] == "personal_asset_unit"
    assert out[0]["source_id"] == "unit-1"
    assert out[0]["title"] == "LoRA learning note"
    assert out[0]["text"] == "LoRA reduces trainable parameters for adaptation."
    assert out[0]["source_marker"] == "graph_1hop"


@patch("engine.app.retrieval.unified.expand_candidates", lambda *args, **kwargs: [])
@patch("engine.app.retrieval.unified.rerank", lambda q, c, **kw: c)
@patch("engine.app.retrieval.unified.recall", lambda *a, **kw: _recalled(*[
    {"chunk_id": "chunk-live", "item_id": "item-live", "score": 0.8},
    {"chunk_id": "chunk-stale", "item_id": "item-stale", "score": 0.7},
]))
def test_unified_search_filters_stale_document_chunks_from_retrieval():
    db = _test_session()
    try:
        db.add(KnowledgeItem(id="item-live", tenant_id="tenant-test", kb_uid="kb-test", title="Live item", user_id="default-user"))
        db.add(
            KnowledgeChunk(
                    id="internal-chunk-row", chunk_uid="chunk-live", tenant_id="tenant-test", kb_uid="kb-test", file_uid="file-test", generation="gen-test",
                item_id="item-live",
                chunk_text="Live chunk text",
                chunk_type="child",
            )
        )
        db.commit()

        out = unified_search("stale?", top_k=5, mode="fast", db=db, graph_client=None, scope=SCOPE)
    finally:
        db.close()

    assert [row["chunk_id"] for row in out] == ["chunk-live"]


@patch("engine.app.retrieval.unified.expand_candidates", lambda *args, **kwargs: [])
@patch("engine.app.retrieval.unified.rerank", lambda q, c, **kw: c)
@patch("engine.app.retrieval.unified.recall", lambda *a, **kw: _recalled({
    "chunk_id": "chunk-side-index",
    "item_id": "item-side-index",
    "file_uid": "file-side-index",
    "score": 0.8,
}))
def test_unified_search_loads_chunk_text_when_index_generation_differs_from_parse_generation():
    db = _test_session()
    try:
        db.add(
            KnowledgeItem(
                id="item-side-index",
                tenant_id="tenant-test",
                kb_uid="kb-test",
                title="Side indexed item",
                user_id="default-user",
            )
        )
        db.add(
            KnowledgeChunk(
                id="internal-side-index-row",
                chunk_uid="chunk-side-index",
                tenant_id="tenant-test",
                kb_uid="kb-test",
                file_uid="file-side-index",
                generation="parse-version-1",
                item_id="item-side-index",
                chunk_text="Text must be loaded even though active index generation is different.",
                chunk_type="child",
            )
        )
        db.commit()

        out = unified_search("side index?", top_k=5, mode="fast", db=db, graph_client=None, scope=SCOPE)
    finally:
        db.close()

    assert out[0]["chunk_id"] == "chunk-side-index"
    assert out[0]["text"] == "Text must be loaded even though active index generation is different."
