def test_graph_exports_subgraph_returns_nodes_and_edges(client):
    entity_id = "entity-123"
    response = client.get("/api/v1/graph-exports/subgraph", params={"entity_id": "entity-123"})

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) >= {"nodes", "edges"}
    assert payload["nodes"] == [{"id": entity_id, "label": entity_id, "type": "entity"}]
    assert payload["edges"] == []


def test_graph_exports_report_returns_summary(client):
    response = client.get("/api/v1/graph-exports/report")

    assert response.status_code == 200
    payload = response.json()
    assert "summary" in payload
    assert isinstance(payload["summary"], str)
    assert payload["details"] == {"node_count": 0, "edge_count": 0}
