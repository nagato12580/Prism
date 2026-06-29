from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.app.main import app


def _mock_client():
    client = MagicMock()
    client.explore.return_value = {
        "nodes": [
            {"id": "ckp:1", "label": "DPO", "type": "CKP", "properties": {"status": "stable"}},
            {"id": "pku:1", "label": "DPO optimizes pairs", "type": "PKU", "properties": {}},
        ],
        "links": [
            {"source": "ckp:1", "target": "pku:1", "type": "SUPPORTED_BY", "properties": {}},
        ],
        "node_count": 2,
        "link_count": 1,
    }
    client.node_detail.return_value = {
        "node": {"id": "ckp:1", "label": "DPO", "type": "CKP", "properties": {"status": "stable"}},
        "neighbors": [
            {"id": "pku:1", "label": "DPO optimizes", "type": "PKU", "properties": {}},
        ],
        "links": [
            {"source": "ckp:1", "target": "pku:1", "type": "SUPPORTED_BY", "properties": {}},
        ],
    }
    client.expand.return_value = {
        "nodes": [{"id": "entity:1", "label": "Tan", "type": "Entity", "properties": {}}],
        "links": [],
        "node_count": 1,
        "link_count": 0,
    }
    return client


def test_graph_explore_returns_subgraph():
    mock_client = _mock_client()
    with patch("backend.app.api.graph_explore.get_graph_query_client", return_value=mock_client):
        client = TestClient(app)
        resp = client.get("/api/v1/graph/explore", params={"types": "CKP,PKU", "limit": 10})

    assert resp.status_code == 200
    data = resp.json()
    assert data["node_count"] == 2
    assert len(data["nodes"]) == 2
    assert data["nodes"][0]["type"] == "CKP"
    assert data["links"][0]["type"] == "SUPPORTED_BY"
    mock_client.explore.assert_called_once()


def test_graph_explore_default_types():
    mock_client = _mock_client()
    with patch("backend.app.api.graph_explore.get_graph_query_client", return_value=mock_client):
        client = TestClient(app)
        resp = client.get("/api/v1/graph/explore")

    assert resp.status_code == 200
    call_args = mock_client.explore.call_args
    assert "CKP" in call_args.kwargs["node_types"]
    assert "Entity" in call_args.kwargs["node_types"]


def test_graph_explore_node_detail():
    mock_client = _mock_client()
    with patch("backend.app.api.graph_explore.get_graph_query_client", return_value=mock_client):
        client = TestClient(app)
        resp = client.get("/api/v1/graph/explore/nodes/ckp:1")

    assert resp.status_code == 200
    data = resp.json()
    assert data["node"]["id"] == "ckp:1"
    assert data["node"]["type"] == "CKP"
    assert len(data["neighbors"]) == 1


def test_graph_explore_expand():
    mock_client = _mock_client()
    with patch("backend.app.api.graph_explore.get_graph_query_client", return_value=mock_client):
        client = TestClient(app)
        resp = client.get("/api/v1/graph/explore/nodes/entity:1/expand", params={"depth": 2})

    assert resp.status_code == 200
    data = resp.json()
    assert data["node_count"] == 1
    mock_client.expand.assert_called_once_with("entity:1", depth=2)
