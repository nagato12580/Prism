import os
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "sqlite:///./_unified_test.db"

from unittest.mock import patch
from engine.app.retrieval.unified import unified_search, make_unified_search


def _hybrid(query, top_k, **kw):
    # pretend hybrid returns 2 chunks
    return [{"chunk_id": "c_vec", "item_id": "i1", "score": 0.6},
            {"chunk_id": "c_bm",  "item_id": "i1", "score": 0.4}]


def _expand(db, graph, seeds, mode, hops, max_candidates, **kw):
    return [{"chunk_id": "c_graph", "item_id": "i2", "source_marker": "graph_1hop"}]


def _rerank(query, cands, top_n, **kw):
    # move graph candidate to top
    cands = sorted(cands, key=lambda c: c["chunk_id"] != "c_graph")
    for c in cands: c["source_marker"] = "rerank"
    return cands[:top_n]


@patch("engine.app.retrieval.unified.expand_candidates", _expand)
@patch("engine.app.retrieval.unified.rerank", _rerank)
@patch("engine.app.retrieval.unified.hybrid_search", _hybrid)
@patch("engine.app.retrieval.unified.match_seed_entities", lambda db, q, **k: ["e1"])
def test_unified_search_merges_and_reranks():
    out = unified_search("q", top_k=5, mode="fast", db=object(), graph_client=object())
    ids = [o["chunk_id"] for o in out]
    assert set(ids) == {"c_vec", "c_bm", "c_graph"}   # hybrid + graph merged
    assert ids[0] == "c_graph"                          # rerank put graph hit first


@patch("engine.app.retrieval.unified.expand_candidates", _expand)
@patch("engine.app.retrieval.unified.rerank", _rerank)
@patch("engine.app.retrieval.unified.hybrid_search", _hybrid)
@patch("engine.app.retrieval.unified.match_seed_entities", lambda db, q, **k: ["e1"])
def test_make_unified_search_returns_scoped_search_fn():
    scoped = make_unified_search(mode="fast", topic_ids=["t1"], source_types=None, allowed_item_ids=None)
    out = scoped("q", 5)
    assert isinstance(out, list) and out and "chunk_id" in out[0]
