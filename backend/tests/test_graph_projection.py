from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database import Base
from backend.app.models import (
    CanonicalKnowledgePoint,
    CanonicalRelation,
    KnowledgeChunk,
    KnowledgeItem,
    PKUCanonicalLink,
    PKURelation,
    PersonalKnowledgeUnit,
)
from backend.app.services.graph_projection import project_ckp_graph


class FakeGraph:
    def __init__(self):
        self.ckps = []
        self.pkus = []
        self.sources = []
        self.relations = []

    def upsert_ckp(self, data):
        self.ckps.append(data)

    def upsert_pku(self, data):
        self.pkus.append(data)

    def upsert_source(self, data):
        self.sources.append(data)

    def relate(self, start_label, start_id, rel_type, end_label, end_id, props=None):
        self.relations.append(
            (start_label, start_id, rel_type, end_label, end_id, props or {})
        )


def _db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(engine)
    return TestingSessionLocal()


def _ckp(ckp_id, title, *, status="stable", canonical_type="concept"):
    return CanonicalKnowledgePoint(
        id=ckp_id,
        user_id="default-user",
        canonical_type=canonical_type,
        title=title,
        canonical_statement=f"{title} statement",
        status=status,
        confidence=0.8,
    )


def _pku(pku_id, source_id, *, status="active"):
    return PersonalKnowledgeUnit(
        id=pku_id,
        user_id="default-user",
        source_kind="document_chunk",
        source_id=source_id,
        unit_type="claim",
        statement=f"{pku_id} statement",
        normalized_statement=f"{pku_id} normalized",
        normalized_statement_hash=f"{pku_id}-hash",
        confidence=0.7,
        status=status,
    )


def test_project_ckp_graph_projects_hierarchy_support_and_source():
    db = _db_session()
    try:
        item = KnowledgeItem(
            id="item-1",
            user_id="default-user",
            title="OpenViewer",
            content="paper text",
        )
        chunk = KnowledgeChunk(
            id="chunk-1",
            item_id=item.id,
            chunk_text="OpenViewer chunk",
            chunk_index=0,
        )
        parent = _ckp("ckp-parent", "Parent CKP", canonical_type="topic")
        child = _ckp("ckp-child", "Child CKP", canonical_type="claim")
        pku = _pku("pku-1", chunk.id)
        hierarchy = CanonicalRelation(
            user_id="default-user",
            source_canonical_id=parent.id,
            target_canonical_id=child.id,
            relation_type="has_child",
            confidence=0.9,
            reason="explicit hierarchy",
        )
        support = PKUCanonicalLink(
            user_id="default-user",
            pku_id=pku.id,
            canonical_id=child.id,
            relation_type="supports",
            role="evidence",
            confidence=0.85,
            reason="chunk says so",
        )
        db.add_all([item, chunk, parent, child, pku, hierarchy, support])
        db.commit()

        graph = FakeGraph()
        result = project_ckp_graph(db, graph)

        assert result.ckp_count == 2
        assert {node["title"] for node in graph.ckps} == {"Parent CKP", "Child CKP"}
        assert {node["ckp_type"] for node in graph.ckps} == {"topic", "claim"}
        assert graph.pkus == [
            {
                "id": pku.id,
                "user_id": "default-user",
                "unit_type": "claim",
                "statement_hash": "pku-1-hash",
                "confidence": 0.7,
                "status": "active",
            }
        ]
        assert graph.sources == [
            {
                "id": "document_chunk:chunk-1",
                "source_kind": "document_chunk",
                "source_id": "chunk-1",
                "item_id": "item-1",
                "title": "OpenViewer",
            }
        ]
        assert (
            "CKP",
            parent.id,
            "HAS_CHILD",
            "CKP",
            child.id,
            {"relation_type": "has_child", "confidence": 0.9, "reason": "explicit hierarchy"},
        ) in graph.relations
        assert (
            "CKP",
            child.id,
            "SUPPORTED_BY",
            "PKU",
            pku.id,
            {
                "relation_type": "supports",
                "role": "evidence",
                "confidence": 0.85,
                "reason": "chunk says so",
            },
        ) in graph.relations
        assert (
            "PKU",
            pku.id,
            "EVIDENCED_BY",
            "Source",
            "document_chunk:chunk-1",
            {"source_kind": "document_chunk", "source_id": "chunk-1"},
        ) in graph.relations
    finally:
        db.close()


def test_project_ckp_graph_projects_ckp_and_pku_related_to_relations():
    db = _db_session()
    try:
        source = _ckp("ckp-source", "Source CKP")
        target = _ckp("ckp-target", "Target CKP")
        first_pku = _pku("pku-first", "chunk-a")
        second_pku = _pku("pku-second", "chunk-b")
        ckp_relation = CanonicalRelation(
            user_id="default-user",
            source_canonical_id=source.id,
            target_canonical_id=target.id,
            relation_type="related_to",
            confidence=0.6,
            reason="semantic neighbor",
        )
        pku_relation = PKURelation(
            user_id="default-user",
            source_pku_id=first_pku.id,
            target_pku_id=second_pku.id,
            relation_type="prerequisite",
            confidence=0.75,
            reason="learn this first",
            source_kind="manual",
            source_id="rel-source",
        )
        db.add_all([source, target, first_pku, second_pku, ckp_relation, pku_relation])
        db.commit()

        graph = FakeGraph()
        project_ckp_graph(db, graph)

        assert (
            "CKP",
            source.id,
            "RELATED_TO",
            "CKP",
            target.id,
            {"relation_type": "related_to", "confidence": 0.6, "reason": "semantic neighbor"},
        ) in graph.relations
        assert (
            "PKU",
            first_pku.id,
            "RELATED_TO",
            "PKU",
            second_pku.id,
            {
                "relation_type": "prerequisite",
                "confidence": 0.75,
                "reason": "learn this first",
                "source_kind": "manual",
                "source_id": "rel-source",
            },
        ) in graph.relations
    finally:
        db.close()


def test_project_ckp_graph_skips_deprecated_nodes():
    db = _db_session()
    try:
        active_ckp = _ckp("ckp-active", "Active CKP")
        deprecated_ckp = _ckp("ckp-deprecated", "Deprecated CKP", status="deprecated")
        active_pku = _pku("pku-active", "chunk-active")
        deprecated_pku = _pku("pku-deprecated", "chunk-deprecated", status="deprecated")
        skipped_ckp_relation = CanonicalRelation(
            user_id="default-user",
            source_canonical_id=active_ckp.id,
            target_canonical_id=deprecated_ckp.id,
            relation_type="related_to",
        )
        skipped_support = PKUCanonicalLink(
            user_id="default-user",
            pku_id=deprecated_pku.id,
            canonical_id=active_ckp.id,
            relation_type="supports",
        )
        skipped_pku_relation = PKURelation(
            user_id="default-user",
            source_pku_id=active_pku.id,
            target_pku_id=deprecated_pku.id,
            relation_type="related_to",
        )
        db.add_all(
            [
                active_ckp,
                deprecated_ckp,
                active_pku,
                deprecated_pku,
                skipped_ckp_relation,
                skipped_support,
                skipped_pku_relation,
            ]
        )
        db.commit()

        graph = FakeGraph()
        result = project_ckp_graph(db, graph)

        assert result.ckp_count == 1
        assert result.pku_count == 1
        assert [node["id"] for node in graph.ckps] == ["ckp-active"]
        assert [node["id"] for node in graph.pkus] == ["pku-active"]
        assert all("deprecated" not in relation for relation in graph.relations)
        assert not any(relation[2] in {"SUPPORTED_BY", "RELATED_TO"} for relation in graph.relations)
    finally:
        db.close()
