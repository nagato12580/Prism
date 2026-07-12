import logging
import sys
import types

from engine.app.graph.analyzer import run_analysis
from engine.app.graph.diagnostics import diagnose_graph_payload


def test_diagnose_graph_payload_detects_generic_entities():
    payload = {
        "nodes": [
            {"id": "e1", "label": "system"},
            {"id": "e2", "label": "GraphRAG"},
            {"id": "e3", "label": "thing"},
            {"id": "e4", "label": "这个"},
        ],
        "edges": [],
    }

    diag = diagnose_graph_payload(payload)

    assert diag["generic_entities"] == ["e1", "e3", "e4"]


def test_diagnose_graph_payload_keeps_all_generic_entity_ids_for_duplicate_labels():
    payload = {
        "nodes": [
            {"id": "e1", "label": "system"},
            {"id": "e2", "label": "system"},
            {"id": "e3", "label": "GraphRAG"},
        ],
        "edges": [],
    }

    diag = diagnose_graph_payload(payload)

    assert diag["generic_entities"] == ["e1", "e2"]


def test_diagnose_graph_payload_counts_dangling_endpoint_edges():
    payload = {
        "nodes": [
            {"id": "e1", "label": "GraphRAG"},
            {"id": "e2", "label": "Retriever"},
        ],
        "edges": [
            {"source": "e1", "target": "e2"},
            {"source": "e1", "target": "missing"},
            {"source": "missing-source", "target": "e2"},
        ],
    }

    diag = diagnose_graph_payload(payload)

    assert diag["dangling_endpoint_edges"] == 2


class _DbStub:
    def query(self, *_args, **_kwargs):
        raise AssertionError("export_graph_for_graphify should be patched in this test")


class _GraphStub:
    def read_entity_communities(self):
        return {}

    def set_entity_analysis(self, *_args, **_kwargs):
        pass

    def relate(self, *_args, **_kwargs):
        pass


def test_run_analysis_logs_generic_entity_diagnostics_without_blocking(monkeypatch, caplog):
    monkeypatch.setattr(
        "engine.app.graph.analyzer.export_graph_for_graphify",
        lambda db, user_id="default-user": {
            "nodes": [{"id": "e1", "label": "system"}],
            "edges": [],
        },
    )
    monkeypatch.setattr("engine.app.graph.analyzer.generate_community_labels", lambda *_a, **_kw: {})
    monkeypatch.setattr("engine.app.graph.analyzer.compute_suggested_questions", lambda **_kw: [])
    monkeypatch.setattr("engine.app.graph.analyzer.govern_ckp_status_by_graph", lambda *_a, **_kw: None)

    graphify_pkg = types.ModuleType("graphify")
    build_mod = types.ModuleType("graphify.build")
    cluster_mod = types.ModuleType("graphify.cluster")
    analyze_mod = types.ModuleType("graphify.analyze")
    diagnostics_mod = types.ModuleType("graphify.diagnostics")

    build_mod.build_from_json = lambda payload, directed=False: types.SimpleNamespace(degree=[("e1", 0)])
    cluster_mod.cluster = lambda graph: {0: ["e1"]}
    cluster_mod.score_all = lambda graph, communities: {0: 0.0}
    analyze_mod.surprising_connections = lambda graph, communities, top_n=20: []
    diagnostics_mod.diagnose_extraction = lambda payload, directed=False: {"dangling_endpoint_edges": 0}

    monkeypatch.setitem(sys.modules, "graphify", graphify_pkg)
    monkeypatch.setitem(sys.modules, "graphify.build", build_mod)
    monkeypatch.setitem(sys.modules, "graphify.cluster", cluster_mod)
    monkeypatch.setitem(sys.modules, "graphify.analyze", analyze_mod)
    monkeypatch.setitem(sys.modules, "graphify.diagnostics", diagnostics_mod)

    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        result = run_analysis(_DbStub(), _GraphStub(), user_id="default-user")

    assert result["node_count"] == 1
    assert "[analyzer] diagnostics generic_entities=['e1']" in caplog.text
