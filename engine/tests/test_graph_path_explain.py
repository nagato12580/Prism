from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.unified_graph import router


class _FakeReadResult:
    def __init__(self, rows):
        self._rows = rows

    def data(self):
        return self._rows


class _FakeReadTx:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def run(self, query, **params):
        self.calls.append((query, params))
        return _FakeReadResult(self.rows)


class _FakeReadSession:
    def __init__(self, rows):
        self.tx = _FakeReadTx(rows)
        self.database = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute_read(self, fn, *args, **kwargs):
        return fn(self.tx, *args, **kwargs)


class _FakeReadDriver:
    def __init__(self, rows):
        self.session_obj = _FakeReadSession(rows)

    def session(self, database=None):
        self.session_obj.database = database
        return self.session_obj


def test_unified_graph_query_path_and_explain_contract(monkeypatch):
    from backend.app.services.graph_client import GraphClient

    class FakeGraph(GraphClient):
        def __init__(self):
            pass

        def close(self):
            pass

        def entity_path(self, source_entity_id, target_entity_id, limit=6):
            assert source_entity_id == "e1"
            assert target_entity_id == "e2"
            assert limit == 6
            return [{"path": ["MiniMind-O", "RELATED_TO", "Omni"]}]

        def explain_source_link(self, entity_id, source_node_id):
            assert entity_id == "e1"
            assert source_node_id == "document_chunk:c1"
            return {
                "entity_id": entity_id,
                "source_id": "c1",
                "source_node_id": source_node_id,
                "why": "MENTIONED_IN edge exists",
                "evidence_type": "EXTRACTED",
            }

    monkeypatch.setattr("backend.app.api.unified_graph.GraphClient", FakeGraph)

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    client = TestClient(app)

    path_response = client.get(
        "/api/v1/unified-graph/path?source_entity_id=e1&target_entity_id=e2"
    )
    explain_response = client.get(
        "/api/v1/unified-graph/explain?entity_id=e1&source_kind=document_chunk&source_id=c1"
    )

    assert path_response.status_code == 200
    assert explain_response.status_code == 200

    path_payload = path_response.json()
    explain_payload = explain_response.json()

    assert path_payload["paths"][0]["path"] == ["MiniMind-O", "RELATED_TO", "Omni"]
    assert explain_payload["evidence_type"] == "EXTRACTED"


def test_graph_client_entity_path_returns_interleaved_path_and_uses_limit_as_max_hops():
    from backend.app.services.graph_client import GraphClient

    driver = _FakeReadDriver(
        [{"path": ["MiniMind-O", "RELATED_TO", "Omni", "MENTIONED_IN", "Design Doc"]}]
    )
    client = GraphClient(driver=driver, database="neo4j")

    rows = client.entity_path("e1", "e2", limit=4)

    assert rows == [{"path": ["MiniMind-O", "RELATED_TO", "Omni", "MENTIONED_IN", "Design Doc"]}]

    query, params = driver.session_obj.tx.calls[0]
    assert "relationships(p)" in query
    assert "type(rel)" in query
    assert "*..4" in query
    assert "LIMIT 1" in query
    assert "LIMIT $limit" not in query
    assert params == {"source_id": "e1", "target_id": "e2"}
