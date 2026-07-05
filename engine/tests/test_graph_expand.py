import os
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "sqlite:///./_graph_expand_test.db"

from unittest.mock import MagicMock
from backend.app.services.graph_client import GraphClient


class _FakeSession:
    def __init__(self, rows_by_query):
        self.rows_by_query = rows_by_query
        self.last = None
    def execute_read(self, fn):
        return fn(self)
    def run(self, query, **params):
        self.last = (query, params)
        # return rows matching by a keyword tag embedded in the query comment
        for tag, rows in self.rows_by_query.items():
            if tag in query:
                return MagicMock(data=lambda: rows)
        return MagicMock(data=lambda: [])
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _client(rows):
    driver = MagicMock(); driver.session.return_value = _FakeSession(rows)
    return GraphClient(driver=driver, database="neo4j")


def test_neighbors_returns_entity_and_source_ids():
    rows = {"neighbors": [{"id": "e2", "kind": "Entity"}, {"id": "document_chunk:c1", "kind": "Source"}]}
    c = _client(rows)
    out = c.neighbors("e1", hops=1, limit=8)
    ids = {(r["id"], r["kind"]) for r in out}
    assert ("e2", "Entity") in ids
    assert ("document_chunk:c1", "Source") in ids


def test_community_members_returns_entity_ids():
    rows = {"community_members": [{"id": "e3"}, {"id": "e4"}]}
    c = _client(rows)
    assert {r["id"] for r in c.community_members(7, limit=10)} == {"e3", "e4"}


def test_god_neighbors_and_surprising_endpoints():
    rows = {
        "god_neighbors": [{"id": "e5"}],
        "surprising": [{"id": "e6"}],
    }
    c = _client(rows)
    assert c.god_neighbors("e1", limit=10) == ["e5"]
    assert c.surprising_endpoints("e1") == ["e6"]
