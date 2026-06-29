from unittest.mock import MagicMock

from backend.app.services.graph_query import (
    explore_subgraph,
    expand_neighbors,
    get_node_detail,
    search_nodes,
)


class FakeRecord:
    def __init__(self, data):
        self._data = data

    def get(self, key, default=None):
        return self._data.get(key, default)

    def __getitem__(self, key):
        return self._data[key]


class FakeResult:
    def __init__(self, records):
        self._records = records

    def __iter__(self):
        return iter(self._records)

    def single(self):
        return self._records[0] if self._records else None


class FakeSession:
    def __init__(self, records_by_query=None):
        self.calls = []
        self._records_by_query = records_by_query or []
        self._call_index = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def run(self, query, params=None):
        self.calls.append((query, params or {}))
        record = self._records_by_query[self._call_index] if self._call_index < len(self._records_by_query) else None
        self._call_index += 1
        if record is None:
            return FakeResult([])
        return FakeResult([record] if not isinstance(record, list) else record)


class FakeDriver:
    def __init__(self, records=None):
        self._records = records or []
        self.session_obj = FakeSession(records)
        self.closed = False

    def session(self, **kwargs):
        return self.session_obj

    def close(self):
        self.closed = True


def test_explore_subgraph_returns_nodes_and_links():
    records = [
        FakeRecord({
            "nodes": [
                {"id": "ckp:1", "title": "DPO", "_labels": ["CKP"]},
                {"id": "pku:1", "statement": "DPO optimizes pairs", "_labels": ["PKU"]},
            ],
            "node_count": 2,
        }),
        FakeRecord({
            "links": [
                {"source": "ckp:1", "target": "pku:1", "type": "SUPPORTED_BY"},
            ],
            "link_count": 1,
        }),
    ]
    driver = FakeDriver(records=records)

    result = explore_subgraph(driver, database="neo4j", node_types=["CKP", "PKU"], limit=10, user_id="default-user")

    assert result["node_count"] == 2
    assert result["link_count"] == 1
    assert len(result["nodes"]) == 2
    assert result["nodes"][0]["id"] == "ckp:1"
    assert result["nodes"][0]["type"] == "CKP"
    assert result["nodes"][0]["label"] == "DPO"
    assert result["links"][0]["source"] == "ckp:1"
    assert result["links"][0]["target"] == "pku:1"
    assert result["links"][0]["type"] == "SUPPORTED_BY"


def test_explore_subgraph_passes_node_types_and_limit_as_params():
    records = [
        FakeRecord({"nodes": [], "node_count": 0}),
        FakeRecord({"links": [], "link_count": 0}),
    ]
    driver = FakeDriver(records=records)
    explore_subgraph(driver, database="neo4j", node_types=["CKP", "Entity"], limit=5, user_id="default-user")

    query, params = driver.session_obj.calls[0]
    assert "$types" in query
    assert "$limit" in query
    assert "$user_id" in query
    assert params["types"] == ["CKP", "Entity"]
    assert params["limit"] == 5
    assert params["user_id"] == "default-user"


def test_explore_subgraph_empty_result():
    records = [
        FakeRecord({"nodes": [], "node_count": 0}),
        FakeRecord({"links": [], "link_count": 0}),
    ]
    driver = FakeDriver(records=records)
    result = explore_subgraph(driver, database="neo4j", node_types=["CKP"], limit=10, user_id="default-user")

    assert result["nodes"] == []
    assert result["links"] == []
    assert result["node_count"] == 0
    assert result["link_count"] == 0


def test_get_node_detail_returns_properties_and_neighbors():
    records = [
        FakeRecord({
            "node_data": {"id": "ckp:1", "title": "DPO", "_labels": ["CKP"], "status": "stable"},
            "neighbors": [
                {"id": "pku:1", "statement": "DPO optimizes", "_labels": ["PKU"]},
            ],
            "links": [
                {"source": "ckp:1", "target": "pku:1", "type": "SUPPORTED_BY", "confidence": 0.9},
            ],
        }),
    ]
    driver = FakeDriver(records=records)

    result = get_node_detail(driver, database="neo4j", node_id="ckp:1")

    assert result["node"]["id"] == "ckp:1"
    assert result["node"]["type"] == "CKP"
    assert result["node"]["properties"]["title"] == "DPO"
    assert result["node"]["properties"]["status"] == "stable"
    assert len(result["neighbors"]) == 1
    assert result["neighbors"][0]["id"] == "pku:1"
    assert result["neighbors"][0]["type"] == "PKU"
    assert result["links"][0]["type"] == "SUPPORTED_BY"


def test_expand_neighbors_returns_n_hop_subgraph():
    records = [
        FakeRecord({
            "nodes": [
                {"id": "entity:1", "canonical_name": "Yanchao Tan", "_labels": ["Entity"]},
                {"id": "entity:2", "canonical_name": "OpenViewer", "_labels": ["Entity"]},
            ],
            "links": [
                {"source": "entity:1", "target": "entity:2", "type": "AUTHORED"},
            ],
            "node_count": 2,
            "link_count": 1,
        }),
    ]
    driver = FakeDriver(records=records)

    result = expand_neighbors(driver, database="neo4j", node_id="entity:1", depth=2)

    query, params = driver.session_obj.calls[0]
    assert "$node_id" in query
    assert "$depth" in query
    assert params["node_id"] == "entity:1"
    assert params["depth"] == 2
    assert result["node_count"] == 2
    assert len(result["nodes"]) == 2


def test_search_nodes_finds_by_label():
    records = [
        FakeRecord({
            "nodes": [
                {"id": "ckp:1", "title": "DPO", "_labels": ["CKP"]},
            ],
            "links": [],
            "node_count": 1,
            "link_count": 0,
        }),
    ]
    driver = FakeDriver(records=records)

    result = search_nodes(driver, database="neo4j", query="DPO", node_types=["CKP"], limit=5)

    query, params = driver.session_obj.calls[0]
    assert "$query" in query
    assert "$types" in query
    assert params["query"] == "DPO"
    assert params["types"] == ["CKP"]
    assert result["node_count"] == 1
    assert result["nodes"][0]["label"] == "DPO"
