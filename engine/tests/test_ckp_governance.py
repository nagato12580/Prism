import os
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "sqlite:///./_ckp_gov_test.db"

from unittest.mock import MagicMock
from backend.app.services.graph_client import GraphClient


class _FakeSession:
    def __init__(self, rows): self.rows = rows; self.last = None
    def execute_read(self, fn): return fn(self)
    def run(self, query, **params):
        self.last = (query, params)
        return MagicMock(data=lambda: self.rows)
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _client(rows):
    driver = MagicMock(); driver.session.return_value = _FakeSession(rows)
    return GraphClient(driver=driver, database="neo4j")


def test_are_gods_returns_id_to_bool_map():
    rows = [{"id": "e1", "is_god": True}, {"id": "e2", "is_god": False}]
    c = _client(rows)
    out = c.are_gods(["e1", "e2", "e3"])   # e3 absent -> False
    assert out == {"e1": True, "e2": False, "e3": False}
