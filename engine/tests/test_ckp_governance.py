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


from backend.app.database import Base, engine as _engine
from backend.app.models import (
    CanonicalKnowledgePoint, EntityAlias, GraphCommunity, KnowledgeEntity,
)
from sqlalchemy.orm import sessionmaker


def _db():
    Base.metadata.drop_all(_engine)
    Base.metadata.create_all(_engine)
    return sessionmaker(bind=_engine)()


def _seed_entities_and_communities(db):
    db.add(KnowledgeEntity(id="e1", user_id="default-user", entity_type="concept", canonical_name="混合检索", normalized_key="混合检索", status="active"))
    db.add(KnowledgeEntity(id="e2", user_id="default-user", entity_type="method",   canonical_name="RRF融合",   normalized_key="rrf融合",   status="active"))
    db.add(EntityAlias(id="a1", entity_id="e1", alias="混合检索", normalized_key="混合检索"))
    db.add(GraphCommunity(id="gc1", user_id="default-user", community_id=0, label="主题0", cohesion=0.45))
    db.commit()


class _FakeGraph:
    def __init__(self, communities, gods):
        self._communities = communities; self._gods = gods
    def entity_community(self, entity_id):
        return self._communities.get(entity_id)
    def are_gods(self, ids):
        return {i: self._gods.get(i, False) for i in ids}


def test_map_ckp_to_entities_matches_concepts_via_alias():
    db = _db(); _seed_entities_and_communities(db)
    try:
        from engine.app.graph.ckp_governance import map_ckp_to_entities
        ckp = CanonicalKnowledgePoint(id="ckp1", user_id="default-user", title="t",
                                      canonical_statement="s", concepts=["混合检索"], entities=[])
        ids = map_ckp_to_entities(db, ckp)
        assert ids == ["e1"]
    finally:
        db.close()


def test_aggregate_signals_cohesion_max_and_god_backed():
    db = _db(); _seed_entities_and_communities(db)
    g = _FakeGraph(communities={"e1": 0, "e2": 0}, gods={"e2": True})
    try:
        from engine.app.graph.ckp_governance import aggregate_ckp_signals
        sig = aggregate_ckp_signals(db, g, ["e1", "e2"], user_id="default-user")
        assert sig["cohesion_score"] == 0.45   # max of community 0 cohesion
        assert sig["god_backed"] is True
    finally:
        db.close()


def test_aggregate_signals_empty_when_no_mapping():
    db = _db(); g = _FakeGraph(communities={}, gods={})
    try:
        from engine.app.graph.ckp_governance import aggregate_ckp_signals
        sig = aggregate_ckp_signals(db, g, [], user_id="default-user")
        assert sig == {"cohesion_score": 0.0, "god_backed": False}
    finally:
        db.close()
