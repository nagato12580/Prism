import os
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "sqlite:///./_graph_analyzer_test.db"

from backend.app.database import Base, engine as _engine
from backend.app.models import KnowledgeEntity, EntityMention, EntityRelation
from sqlalchemy.orm import sessionmaker

from engine.app.graph.analyzer import export_graph_for_graphify


def _db():
    Base.metadata.create_all(_engine)
    return sessionmaker(bind=_engine)()


def test_export_builds_nodes_and_cooccurrence_and_relation_edges():
    db = _db()
    try:
        db.query(EntityRelation).delete()
        db.query(EntityMention).delete()
        db.query(KnowledgeEntity).delete()
        db.commit()
        e1 = KnowledgeEntity(id="e1", user_id="default-user", entity_type="concept", canonical_name="混合检索", normalized_key="a", status="active")
        e2 = KnowledgeEntity(id="e2", user_id="default-user", entity_type="method", canonical_name="RRF融合", normalized_key="b", status="active")
        e3 = KnowledgeEntity(id="e3", user_id="default-user", entity_type="concept", canonical_name="重排", normalized_key="c", status="active")
        db.add_all([e1, e2, e3]); db.flush()
        # e1,e2 both mentioned by chunk c1 -> co-occurrence edge e1-e2
        db.add(EntityMention(id="m1", entity_id="e1", source_kind="document_chunk", source_id="c1", item_id="i1", chunk_id="c1", surface_text="混合检索", normalized_key="a", confidence=1.0))
        db.add(EntityMention(id="m2", entity_id="e2", source_kind="document_chunk", source_id="c1", item_id="i1", chunk_id="c1", surface_text="RRF融合", normalized_key="b", confidence=1.0))
        # explicit relation e2-e3
        db.add(EntityRelation(id="r1", subject_entity_id="e2", predicate="uses", object_entity_id="e3", relation_key="k1", source_kind="document_chunk", source_id="c1", confidence=0.85))
        db.commit()

        exported = export_graph_for_graphify(db, user_id="default-user")
        ids = {n["id"] for n in exported["nodes"]}
        assert ids == {"e1", "e2", "e3"}
        # co-occurrence edge e1-e2 + relation edge e2-e3 = at least 2 edges
        pairs = {(e["source"], e["target"]) for e in exported["edges"]}
        assert (("e1", "e2") in pairs or ("e2", "e1") in pairs)
        assert (("e2", "e3") in pairs or ("e3", "e2") in pairs)
    finally:
        db.close()


from unittest.mock import MagicMock
from backend.app.services.graph_client import GraphClient


class _FakeSession:
    def __init__(self):
        self.entities = {}   # id -> props
        self.written = []
    def execute_read(self, fn):
        return fn(self)
    def execute_write(self, fn):
        return fn(self)
    def run(self, query, **params):
        self.written.append((query, params))
        if query.strip().startswith("MATCH (e:Entity) WHERE e.community_id"):
            return MagicMock(data=lambda: [{"id": i, "cid": p["community_id"]} for i, p in self.entities.items() if p.get("community_id") is not None])
        return MagicMock()
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_graph_client_read_write_analysis():
    sess = _FakeSession()
    driver = MagicMock(); driver.session.return_value = sess
    client = GraphClient(driver=driver, database="neo4j")

    # seed one entity with an old community
    sess.entities["e1"] = {"community_id": 7}
    old = client.read_entity_communities()
    assert old == {"e1": 7}

    client.set_entity_analysis("e2", community_id=7, is_god=True, cohesion=0.42)
    # a write happened
    assert any("SET" in q for q, _ in sess.written)
