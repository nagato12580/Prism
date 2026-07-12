import os

if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "sqlite:///./_graph_rag_contract.db"


class _GraphForContractTest:
    def neighbors(self, entity_id, hops=1, limit=8):
        if entity_id == "e1":
            return [{"id": "personal_asset_unit:u1", "kind": "Source"}]
        return []


def test_unified_search_returns_graph_rag_hit_contract(monkeypatch):
    from engine.app.retrieval import unified as mod

    monkeypatch.setattr(
        mod,
        "hybrid_search",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(mod, "match_seed_entities", lambda *args, **kwargs: ["e1"])
    monkeypatch.setattr(mod, "rerank", lambda query, candidates, top_n: candidates)

    out = mod.unified_search("MiniMind-O", top_k=5, mode="fast", db=object(), graph_client=_GraphForContractTest())

    assert len(out) == 1
    first = out[0]
    assert "graph_rag" in first
    assert first["graph_rag"]["source"]["source_kind"] == "personal_asset_unit"
    assert first["graph_rag"]["source"]["source_id"] == "u1"
    assert first["source_marker"] == first["graph_rag"]["explain"]["source_marker"] == "graph_1hop"
    assert isinstance(first["graph_rag"]["path"], list)
    assert len(first["graph_rag"]["path"]) == 1
    route = first["graph_rag"]["path"][0]
    assert route["source_marker"] == "graph_1hop"
    assert route["matched_entity_ids"] == ["e1"]
    assert route["steps"][0]["node_id"] == "e1"
    assert route["steps"][1]["edge_type"] == "GRAPH_1HOP"
    assert route["steps"][2]["node_id"] == "personal_asset_unit:u1"
    assert first["graph_rag"]["explain"]["matched_entity_ids"] == ["e1"]
    assert first["graph_rag"]["explain"]["evidence_type"] == "INFERRED"
