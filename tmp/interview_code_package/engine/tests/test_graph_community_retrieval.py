import os

import pytest

if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "sqlite:///./_graph_community_retrieval.db"


class _FakeDeepGraph:
    def __init__(self):
        self.neighbors_map = {
            "e1": [{"id": "document_chunk:c1", "kind": "Source"}],
            "e_comm": [{"id": "document_chunk:c_comm", "kind": "Source"}],
            "e_surp": [{"id": "document_chunk:c_surp", "kind": "Source"}],
        }

    def neighbors(self, entity_id, hops=1, limit=8):
        return self.neighbors_map.get(entity_id, [])

    def entity_community(self, entity_id):
        return 7 if entity_id == "e1" else None

    def community_members(self, cid, limit=10):
        if cid == 7:
            return [{"id": "e_comm"}]
        return []

    def god_neighbors(self, entity_id, limit=10):
        return []

    def surprising_endpoints(self, entity_id):
        if entity_id == "e1":
            return ["e_surp"]
        return []


def test_deep_unified_search_uses_community_and_surprising_candidates(monkeypatch):
    from engine.app.retrieval import unified as mod

    monkeypatch.setattr(mod, "hybrid_search", lambda *args, **kwargs: [])
    monkeypatch.setattr(mod, "match_seed_entities", lambda *args, **kwargs: ["e1"])
    monkeypatch.setattr(mod, "rerank", lambda query, candidates, top_n: candidates)
    monkeypatch.setattr(mod, "_filter_stale_hits", lambda db, hits: hits)

    out = mod.unified_search("query", top_k=5, mode="deep", db=object(), graph_client=_FakeDeepGraph())

    by_chunk = {item["chunk_id"]: item for item in out}
    markers = {item["source_marker"] for item in out}

    assert "c_comm" in by_chunk
    assert "c_surp" in by_chunk
    assert "community" in markers
    assert "surprising" in markers


def test_unified_search_scores_graph_hits_with_marker_specific_weights(monkeypatch):
    from engine.app.retrieval import unified as mod

    monkeypatch.setattr(mod, "hybrid_search", lambda *args, **kwargs: [])
    monkeypatch.setattr(mod, "match_seed_entities", lambda *args, **kwargs: ["e1"])
    monkeypatch.setattr(
        mod,
        "expand_candidates",
        lambda *args, **kwargs: [
            {"chunk_id": "c_graph", "item_id": "i1", "source_marker": "graph_2hop"},
            {"chunk_id": "c_comm", "item_id": "i2", "source_marker": "community"},
            {"chunk_id": "c_surp", "item_id": "i3", "source_marker": "surprising"},
            {"chunk_id": "c_god", "item_id": "i4", "source_marker": "god"},
        ],
    )
    monkeypatch.setattr(mod, "rerank", lambda query, candidates, top_n: candidates)

    out = mod.unified_search("query", top_k=10, mode="deep", db=object(), graph_client=object())
    by_chunk = {item["chunk_id"]: item for item in out}

    assert by_chunk["c_graph"]["score"] == pytest.approx(0.5 / (mod.RRF_K + 1))
    assert by_chunk["c_comm"]["score"] == pytest.approx(0.45 / (mod.RRF_K + 2))
    assert by_chunk["c_surp"]["score"] == pytest.approx(0.42 / (mod.RRF_K + 3))
    assert by_chunk["c_god"]["score"] == pytest.approx(0.48 / (mod.RRF_K + 4))
