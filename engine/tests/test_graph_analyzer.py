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


from engine.app.graph.analyzer import run_analysis, _remap_communities


def test_remap_keeps_stable_ids_for_unchanged_community():
    # old: {e1,e2,e3}->cid 5
    old = {"e1": 5, "e2": 5, "e3": 5}
    new = {0: ["e1", "e2", "e3", "e4"]}   # same community, one new node
    final = _remap_communities(new, old)
    assert final["e1"] == 5 and final["e2"] == 5 and final["e3"] == 5   # stable
    assert final["e4"] == 5                                               # joined same community


def test_remap_assigns_new_id_to_brand_new_community():
    old = {"e1": 5}
    new = {0: ["e1"], 1: ["e2", "e3"]}   # e2,e3 brand new, no overlap with old
    final = _remap_communities(new, old)
    assert final["e1"] == 5
    assert final["e2"] == final["e3"]                                    # same new community
    assert final["e2"] != 5                                              # a new id


class _AnalysisFakeGraph:
    """Records analysis writes; supports the methods run_analysis calls."""
    def __init__(self): self.old = {}; self.set_calls = []; self.relations = []
    def read_entity_communities(self): return dict(self.old)
    def set_entity_analysis(self, eid, community_id, is_god, cohesion):
        self.set_calls.append((eid, community_id, is_god, cohesion))
    def relate(self, sl, si, rt, el, ei, props=None):
        if sl == "Entity" and el == "Entity":
            self.relations.append((si, ei, props))


def test_run_analysis_writes_community_and_does_not_crash_on_small_graph():
    db = _db()
    try:
        db.query(EntityRelation).delete()
        db.query(EntityMention).delete()
        db.query(KnowledgeEntity).delete()
        db.commit()
        for i, name in enumerate(["混合检索", "RRF融合", "重排", "metadata filter", "向量召回"], start=1):
            db.add(KnowledgeEntity(id=f"e{i}", user_id="default-user", entity_type="concept",
                                   canonical_name=name, normalized_key=name, status="active"))
        db.flush()
        db.add(EntityRelation(id="r1", subject_entity_id="e1", predicate="uses", object_entity_id="e2", relation_key="k1", source_kind="document_chunk", source_id="c1", confidence=0.85))
        db.add(EntityRelation(id="r2", subject_entity_id="e1", predicate="uses", object_entity_id="e3", relation_key="k2", source_kind="document_chunk", source_id="c1", confidence=0.85))
        db.commit()
        fake = _AnalysisFakeGraph()
        result = run_analysis(db, fake, user_id="default-user")
        # every entity got a community_id written
        written_ids = {c[0] for c in fake.set_calls}
        assert written_ids == {f"e{i}" for i in range(1, 6)}
        assert result["node_count"] == 5
    finally:
        db.close()


def test_run_analysis_persists_community_labels_and_questions(monkeypatch):
    from backend.app.database import Base, engine as _engine
    from backend.app.models import KnowledgeEntity, EntityRelation, GraphCommunity, GraphInsightSummary
    from sqlalchemy.orm import sessionmaker
    from engine.app.graph.analyzer import run_analysis
    from engine.app.graph import insights as ins

    Base.metadata.create_all(_engine)
    db = sessionmaker(bind=_engine)()
    try:
        for i, name in enumerate(["混合检索", "RRF融合", "重排", "metadata filter", "向量召回"], start=21):
            db.add(KnowledgeEntity(id=f"e{i}", user_id="default-user", entity_type="concept",
                                   canonical_name=name, normalized_key=name + "_p5bis", status="active"))
        db.flush()
        db.add(EntityRelation(id="r1_p5b", subject_entity_id="e21", predicate="uses", object_entity_id="e22", relation_key="k1p5b", source_kind="document_chunk", source_id="c1", confidence=0.85))
        db.add(EntityRelation(id="r2_p5b", subject_entity_id="e21", predicate="uses", object_entity_id="e23", relation_key="k2p5b", source_kind="document_chunk", source_id="c1", confidence=0.85))
        db.commit()

        # stub the LLM label call + graph (read/write analysis) so run_analysis stays deterministic
        # patch on analyzer module since it imported the functions locally
        monkeypatch.setattr("engine.app.graph.analyzer.generate_community_labels", lambda c, **kw: {cid: f"主题{cid}" for cid in c})
        monkeypatch.setattr("engine.app.graph.analyzer.compute_suggested_questions", lambda **kw: [{"type": "god", "question": "Q?", "why": "w"}])

        class _G:
            def read_entity_communities(self): return {}
            def set_entity_analysis(self, *a, **kw): pass
            def relate(self, *a, **kw): pass
        run_analysis(db, _G(), user_id="default-user")

        gcs = db.query(GraphCommunity).filter_by(user_id="default-user").all()
        assert len(gcs) >= 1 and all(gc.label.startswith("主题") for gc in gcs)
        summ = db.query(GraphInsightSummary).filter_by(user_id="default-user").one()
        assert summ.suggested_questions[0]["question"] == "Q?"
    finally:
        db.close()


def test_run_analysis_invokes_ckp_governance(monkeypatch):
    from backend.app.database import Base, engine as _engine
    from backend.app.models import KnowledgeEntity, EntityRelation
    from sqlalchemy.orm import sessionmaker
    from engine.app.graph.analyzer import run_analysis

    Base.metadata.drop_all(_engine)
    Base.metadata.create_all(_engine)
    db = sessionmaker(bind=_engine)()
    try:
        for i, name in enumerate(["混合检索", "RRF融合", "重排", "metadata filter", "向量召回"], start=1):
            db.add(KnowledgeEntity(id=f"e{i}", user_id="default-user", entity_type="concept",
                                   canonical_name=name, normalized_key=name + "_p4task5", status="active"))
        db.flush()
        db.add(EntityRelation(id="r1", subject_entity_id="e1", predicate="uses", object_entity_id="e2", relation_key="k1", source_kind="document_chunk", source_id="c1", confidence=0.85))
        db.commit()

        # patch insights functions that analyzer imports locally
        monkeypatch.setattr("engine.app.graph.analyzer.generate_community_labels", lambda c, **kw: {cid: f"主题{cid}" for cid in c})
        monkeypatch.setattr("engine.app.graph.analyzer.compute_suggested_questions", lambda **kw: [])

        called = {"n": 0}
        def _fake_gov(db, graph, user_id, **kw):
            called["n"] += 1; return {"promoted": 0, "signaled": 0}
        monkeypatch.setattr("engine.app.graph.analyzer.govern_ckp_status_by_graph", _fake_gov)

        class _G:
            def read_entity_communities(self): return {}
            def set_entity_analysis(self, *a, **kw): pass
            def relate(self, *a, **kw): pass
        run_analysis(db, _G(), user_id="default-user")
        assert called["n"] == 1   # govern called once at end of run_analysis
    finally:
        db.close()
