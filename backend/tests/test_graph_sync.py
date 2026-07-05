from backend.app.services import graph_sync


class FakeGraph:
    closed = False

    def close(self):
        self.closed = True


class FakeResult:
    ckp_count = 1
    pku_count = 2
    entity_count = 3
    alias_count = 4
    relation_count = 5
    pku_entity_mention_count = 6


def test_project_governance_graph_if_enabled_returns_none_when_disabled(monkeypatch):
    monkeypatch.setattr(graph_sync.settings, "ENTITY_GRAPH_ENABLED", False)
    called = False

    def fail_if_called():
        nonlocal called
        called = True

    monkeypatch.setattr(graph_sync, "GraphClient", fail_if_called)

    assert graph_sync.project_governance_graph_if_enabled(object()) is None
    assert called is False


def test_project_governance_graph_if_enabled_projects_all_layers(monkeypatch):
    monkeypatch.setattr(graph_sync.settings, "ENTITY_GRAPH_ENABLED", True)
    graph = FakeGraph()
    calls = []

    monkeypatch.setattr(graph_sync, "GraphClient", lambda: graph)
    monkeypatch.setattr(graph_sync, "project_ckp_graph", lambda db, graph, user_id, **kw: calls.append(("ckp", user_id)) or FakeResult())
    monkeypatch.setattr(graph_sync, "project_entity_graph", lambda db, graph, user_id, **kw: calls.append(("entity", user_id)) or FakeResult())
    monkeypatch.setattr(graph_sync, "project_pku_entity_mentions", lambda db, graph, user_id, **kw: calls.append(("bridge", user_id)) or FakeResult())

    result = graph_sync.project_governance_graph_if_enabled(object(), user_id="u1")

    assert list(result) == ["ckp", "entity", "bridge"]
    assert calls == [("ckp", "u1"), ("entity", "u1"), ("bridge", "u1")]
    assert graph.closed is True


def test_project_governance_graph_if_enabled_is_best_effort(monkeypatch):
    monkeypatch.setattr(graph_sync.settings, "ENTITY_GRAPH_ENABLED", True)
    graph = FakeGraph()

    monkeypatch.setattr(graph_sync, "GraphClient", lambda: graph)

    def fail(*args, **kwargs):
        raise RuntimeError("neo4j down")

    monkeypatch.setattr(graph_sync, "project_ckp_graph", fail)

    assert graph_sync.project_governance_graph_if_enabled(object(), user_id="u1") is None
    assert graph.closed is True
