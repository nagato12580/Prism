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


# ---- graph_expand module tests ----

from backend.app.database import Base, engine as _engine
from backend.app.models import KnowledgeEntity, EntityAlias
from sqlalchemy.orm import sessionmaker
from engine.app.retrieval.graph_expand import expand_candidates, match_seed_entities


class _FakeGraphClient:
    def __init__(self, neighbors_map, community_map, gods, surprising_map, entity_community_map=None):
        self.neighbors_map = neighbors_map; self.community_map = community_map
        self.gods = gods; self.surprising_map = surprising_map
        self._entity_community_map = entity_community_map or {}
    def neighbors(self, entity_id, hops=1, limit=8):
        return self.neighbors_map.get(entity_id, [])
    def community_members(self, cid, limit=10):
        return self.community_map.get(cid, [])
    def god_neighbors(self, entity_id, limit=10):
        return self.gods.get(entity_id, [])
    def surprising_endpoints(self, entity_id):
        return self.surprising_map.get(entity_id, [])
    def entity_community(self, entity_id):
        return self._entity_community_map.get(entity_id)


def _db():
    Base.metadata.create_all(_engine)
    return sessionmaker(bind=_engine)()


def test_match_seed_entities_finds_by_alias():
    db = _db()
    try:
        db.query(EntityAlias).delete()
        db.query(KnowledgeEntity).delete()
        db.commit()
        db.add(KnowledgeEntity(id="e1", user_id="default-user", entity_type="concept", canonical_name="混合检索", normalized_key="混合检索", status="active"))
        db.add(EntityAlias(id="a1", entity_id="e1", alias="混合检索", normalized_key="混合检索"))
        db.commit()
        seeds = match_seed_entities(db, "我想了解 混合检索 的用法")
        assert "e1" in seeds
    finally:
        db.close()


def test_match_seed_entities_substring_match_is_case_insensitive():
    db = _db()
    try:
        db.query(EntityAlias).delete()
        db.query(KnowledgeEntity).delete()
        db.commit()
        db.add(
            KnowledgeEntity(
                id="e-openai",
                user_id="default-user",
                entity_type="organization",
                canonical_name="OpenAI",
                normalized_key="openai",
                status="active",
            )
        )
        db.commit()

        seeds = match_seed_entities(db, "tell me about openai model behavior")

        assert "e-openai" in seeds
    finally:
        db.close()


def test_expand_candidates_fast_mode_collects_source_chunks():
    g = _FakeGraphClient(
        neighbors_map={"e1": [{"id": "document_chunk:c1", "kind": "Source"},
                              {"id": "document_chunk:c2", "kind": "Source"}]},
        community_map={}, gods={}, surprising_map={})
    cands = expand_candidates(db=None, graph=g, seed_entity_ids=["e1"], mode="fast", hops=1, max_candidates=60)
    chunk_ids = {c["chunk_id"] for c in cands}
    assert chunk_ids == {"c1", "c2"}
    assert all(c["source_marker"] in ("graph_1hop", "graph_2hop") for c in cands)


def test_expand_candidates_deep_adds_community_god_surprising():
    g = _FakeGraphClient(
        neighbors_map={"e1": [{"id": "e2", "kind": "Entity"}, {"id": "document_chunk:c1", "kind": "Source"}]},
        community_map={0: [{"id": "e3"}]},
        gods={"e1": ["eGOD"]},
        surprising_map={"e1": ["eSURP"]},
        entity_community_map={"e1": 0})
    # neighbors of the community/god/surprising entities also yield chunks
    g.neighbors_map["e3"] = [{"id": "document_chunk:c3", "kind": "Source"}]
    g.neighbors_map["eGOD"] = [{"id": "document_chunk:cGOD", "kind": "Source"}]
    g.neighbors_map["eSURP"] = [{"id": "document_chunk:cSURP", "kind": "Source"}]
    cands = expand_candidates(db=None, graph=g, seed_entity_ids=["e1"], mode="deep", hops=2, max_candidates=60)
    chunk_ids = {c["chunk_id"] for c in cands}
    assert {"c1", "c3", "cGOD", "cSURP"} <= chunk_ids
    markers = {c["source_marker"] for c in cands}
    assert "community" in markers and "god" in markers and "surprising" in markers


def test_expand_candidates_returns_personal_asset_unit_sources():
    g = _FakeGraphClient(
        neighbors_map={"e1": [{"id": "personal_asset_unit:unit-1", "kind": "Source"}]},
        community_map={},
        gods={},
        surprising_map={},
    )
    cands = expand_candidates(db=None, graph=g, seed_entity_ids=["e1"], mode="fast", hops=1, max_candidates=10)
    assert len(cands) == 1
    assert cands[0]["source_kind"] == "personal_asset_unit"
    assert cands[0]["source_id"] == "unit-1"
    assert cands[0]["source_marker"] == "graph_1hop"
    assert cands[0]["path"] == [
        {
            "source_marker": "graph_1hop",
            "matched_entity_ids": ["e1"],
            "steps": [
                {"node_id": "e1", "node_type": "entity"},
                {"edge_type": "GRAPH_1HOP", "evidence_type": "INFERRED"},
                {"node_id": "personal_asset_unit:unit-1", "node_type": "source"},
            ],
        }
    ]
    assert cands[0]["explain"]["matched_entity_ids"] == ["e1"]
    assert cands[0]["explain"]["why"] == "graph_1hop expansion reached source"
    assert cands[0]["explain"]["evidence_type"] == "INFERRED"


def test_expand_candidates_merges_graph_routes_for_same_source():
    g = _FakeGraphClient(
        neighbors_map={
            "e1": [{"id": "document_chunk:c1", "kind": "Source"}],
            "e2": [{"id": "document_chunk:c1", "kind": "Source"}],
        },
        community_map={0: [{"id": "e2"}]},
        gods={},
        surprising_map={},
        entity_community_map={"e1": 0},
    )

    cands = expand_candidates(db=None, graph=g, seed_entity_ids=["e1"], mode="deep", hops=2, max_candidates=10)

    assert len(cands) == 1
    assert cands[0]["chunk_id"] == "c1"
    assert cands[0]["source_marker"] == "graph_2hop+community"
    assert cands[0]["path"] == [
        {
            "source_marker": "graph_2hop",
            "matched_entity_ids": ["e1"],
            "steps": [
                {"node_id": "e1", "node_type": "entity"},
                {"edge_type": "GRAPH_2HOP", "evidence_type": "INFERRED"},
                {"node_id": "document_chunk:c1", "node_type": "source"},
            ],
        },
        {
            "source_marker": "community",
            "matched_entity_ids": ["e2"],
            "steps": [
                {"node_id": "e2", "node_type": "entity"},
                {"edge_type": "COMMUNITY", "evidence_type": "INFERRED"},
                {"node_id": "document_chunk:c1", "node_type": "source"},
            ],
        },
    ]
    assert cands[0]["explain"] == {
        "matched_entity_ids": ["e1", "e2"],
        "why": "2 graph expansion routes reached source",
        "evidence_type": "INFERRED",
        "source_markers": ["graph_2hop", "community"],
        "route_count": 2,
    }
