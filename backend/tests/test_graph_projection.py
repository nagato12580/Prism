from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database import Base
from backend.app.models import (
    CanonicalKnowledgePoint,
    CanonicalRelation,
    EntityAlias,
    EntityMention,
    EntityRelation,
    KnowledgeEntity,
    KnowledgeChunk,
    KnowledgeItem,
    PKUCanonicalLink,
    PKURelation,
    PersonalAssetUnit,
    PersonalKnowledgeUnit,
)
from backend.app.services.graph_client import ALLOWED_RELATIONSHIP_TYPES
from backend.app.services.graph_projection import (
    project_asset_unit_entities,
    project_ckp_graph,
    project_entity_graph,
)
from backend.app.services.graph_projection import ENTITY_RELATION_TYPES


class FakeGraph:
    def __init__(self):
        self.ckps = []
        self.pkus = []
        self.entities = []
        self.aliases = []
        self.sources = []
        self.relations = []

    def upsert_ckp(self, data):
        self.ckps.append(data)

    def upsert_pku(self, data):
        self.pkus.append(data)

    def upsert_entity(self, data):
        self.entities.append(data)

    def upsert_alias(self, data):
        self.aliases.append(data)

    def upsert_source(self, data):
        self.sources.append(data)

    def relate(self, start_label, start_id, rel_type, end_label, end_id, props=None):
        self.relations.append(
            (start_label, start_id, rel_type, end_label, end_id, props or {})
        )

    def delete_item_sources(self, tenant_id, kb_uid, graph_generation, item_id):
        pass


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


def _entity(entity_id, canonical_name, *, entity_type="person", status="active"):
    return KnowledgeEntity(
        id=entity_id,
        user_id="default-user",
        entity_type=entity_type,
        canonical_name=canonical_name,
        normalized_key=canonical_name.replace(" ", ""),
        confidence=0.8,
        status=status,
    )


def test_project_ckp_graph_projects_hierarchy_support_and_source():
    db = _db_session()
    try:
        item = KnowledgeItem(
            id="item-1",
            tenant_id="tenant-a",
            kb_uid="kb-a",
            user_id="default-user",
            title="OpenViewer",
            content="paper text",
        )
        chunk = KnowledgeChunk(
            id="chunk-1",
            tenant_id="tenant-a",
            kb_uid="kb-a",
            file_uid="file-a",
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
                "tenant_id": "tenant-a",
                "kb_uid": "kb-a",
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


def test_project_entity_graph_relationship_types_match_graph_client_allowlist():
    projected_relationship_types = {
        *ENTITY_RELATION_TYPES.values(),
        "RELATED_TO",
        "MENTIONED_IN",
        "ALIAS_OF",
    }

    assert projected_relationship_types <= ALLOWED_RELATIONSHIP_TYPES


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


def test_project_ckp_graph_projects_subtopic_of_as_parent_has_child():
    db = _db_session()
    try:
        parent = _ckp("ckp-parent", "Parent CKP")
        child = _ckp("ckp-child", "Child CKP")
        relation = CanonicalRelation(
            user_id="default-user",
            source_canonical_id=child.id,
            target_canonical_id=parent.id,
            relation_type="subtopic_of",
            confidence=0.95,
            reason="governance hierarchy",
        )
        db.add_all([parent, child, relation])
        db.commit()

        graph = FakeGraph()
        project_ckp_graph(db, graph)

        assert (
            "CKP",
            parent.id,
            "HAS_CHILD",
            "CKP",
            child.id,
            {
                "relation_type": "subtopic_of",
                "confidence": 0.95,
                "reason": "governance hierarchy",
            },
        ) in graph.relations
        assert not any(relation[2] == "RELATED_TO" for relation in graph.relations)
    finally:
        db.close()


def test_project_ckp_graph_counts_and_upserts_each_source_once():
    db = _db_session()
    try:
        item = KnowledgeItem(
            id="item-1",
            tenant_id="tenant-a",
            kb_uid="kb-a",
            user_id="default-user",
            title="OpenViewer",
            content="paper text",
        )
        chunk = KnowledgeChunk(
            id="chunk-1",
            tenant_id="tenant-a",
            kb_uid="kb-a",
            file_uid="file-a",
            item_id=item.id,
            chunk_text="OpenViewer chunk",
        )
        first_pku = _pku("pku-first", chunk.id)
        second_pku = _pku("pku-second", chunk.id)
        db.add_all([item, chunk, first_pku, second_pku])
        db.commit()

        graph = FakeGraph()
        result = project_ckp_graph(db, graph)

        assert result.pku_count == 2
        assert result.source_count == 1
        assert graph.sources == [
            {
                "id": "document_chunk:chunk-1",
                "tenant_id": "tenant-a",
                "kb_uid": "kb-a",
                "source_kind": "document_chunk",
                "source_id": "chunk-1",
                "item_id": "item-1",
                "title": "OpenViewer",
            }
        ]
        assert sum(1 for relation in graph.relations if relation[2] == "EVIDENCED_BY") == 2
    finally:
        db.close()


def test_project_ckp_graph_does_not_use_wrong_user_item_title_for_source():
    db = _db_session()
    try:
        wrong_user_item = KnowledgeItem(
            id="item-wrong-user",
            tenant_id="tenant-other",
            kb_uid="kb-other",
            user_id="other-user",
            title="Private Other User Title",
            content="paper text",
        )
        chunk = KnowledgeChunk(
            id="chunk-1",
            tenant_id="tenant-other",
            kb_uid="kb-other",
            file_uid="file-other",
            item_id=wrong_user_item.id,
            chunk_text="OpenViewer chunk",
        )
        pku = _pku("pku-1", chunk.id)
        db.add_all([wrong_user_item, chunk, pku])
        db.commit()

        graph = FakeGraph()
        result = project_ckp_graph(db, graph, user_id="default-user")

        assert result.source_count == 1
        assert graph.sources == [
            {
                "id": "document_chunk:chunk-1",
                "tenant_id": "tenant-other",
                "kb_uid": "kb-other",
                "source_kind": "document_chunk",
                "source_id": "chunk-1",
                "item_id": "item-wrong-user",
                "title": "chunk-1",
            }
        ]
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
        relation_endpoint_ids = {
            endpoint_id
            for relation in graph.relations
            for endpoint_id in (relation[1], relation[4])
        }
        assert "ckp-deprecated" not in relation_endpoint_ids
        assert "pku-deprecated" not in relation_endpoint_ids
        assert not any(
            relation[2] in {"SUPPORTED_BY", "RELATED_TO"}
            for relation in graph.relations
        )
    finally:
        db.close()


def test_project_entity_graph_projects_entities_aliases_mentions_and_relations():
    db = _db_session()
    try:
        person = _entity("person-1", "Yanchao Tan")
        paper = _entity("paper-1", "OpenViewer", entity_type="paper")
        alias = EntityAlias(
            id="alias-1",
            entity_id=person.id,
            alias="Tan",
            normalized_key="tan",
            confidence=0.75,
            extraction_method="test",
        )
        mention = EntityMention(
            id="mention-1",
            entity_id=person.id,
            source_kind="document_chunk",
            source_id="chunk-1",
            item_id="item-1",
            chunk_id="chunk-1",
            surface_text="Yanchao Tan",
            normalized_key="YanchaoTan",
            evidence_span="Yanchao Tan authored OpenViewer",
            confidence=0.9,
            extraction_method="test-extractor",
        )
        relation = EntityRelation(
            id="relation-1",
            subject_entity_id=person.id,
            predicate="authored",
            object_entity_id=paper.id,
            source_kind="document_chunk",
            source_id="chunk-1",
            evidence_span="Yanchao Tan authored OpenViewer",
            confidence=0.85,
            extraction_method="test-extractor",
        )
        db.add_all([person, paper, alias, mention, relation])
        db.commit()

        graph = FakeGraph()
        result = project_entity_graph(db, graph)

        assert result.entity_count == 2
        assert result.alias_count == 1
        assert result.source_count == 1
        assert result.relation_count == 3
        assert {
            (
                node["id"],
                node["user_id"],
                node["entity_type"],
                node["canonical_name"],
                node["normalized_key"],
                node["status"],
                node["confidence"],
            )
            for node in graph.entities
        } == {
            ("person-1", "default-user", "person", "Yanchao Tan", "YanchaoTan", "active", 0.8),
            ("paper-1", "default-user", "paper", "OpenViewer", "OpenViewer", "active", 0.8),
        }
        assert graph.aliases == [
            {
                "id": "alias-1",
                "key": "tan",
                "surface_text": "Tan",
                "entity_id": "person-1",
            }
        ]
        assert graph.sources == [
            {
                "id": "document_chunk:chunk-1",
                "tenant_id": "",
                "kb_uid": "",
                "source_kind": "document_chunk",
                "source_id": "chunk-1",
                "item_id": "item-1",
                "title": "item-1",
            }
        ]
        assert (
            "Entity",
            "person-1",
            "MENTIONED_IN",
            "Source",
            "document_chunk:chunk-1",
            {
                "confidence": 0.9,
                "evidence_span": "Yanchao Tan authored OpenViewer",
                "extraction_method": "test-extractor",
                "source_kind": "document_chunk",
                "source_id": "chunk-1",
            },
        ) in graph.relations
        assert (
            "Entity",
            "person-1",
            "AUTHORED",
            "Entity",
            "paper-1",
            {
                "predicate": "authored",
                "confidence": 0.85,
                "evidence_span": "Yanchao Tan authored OpenViewer",
                "extraction_method": "test-extractor",
                "source_kind": "document_chunk",
                "source_id": "chunk-1",
            },
        ) in graph.relations
    finally:
        db.close()


def test_project_entity_graph_skips_deprecated_entities_and_relations():
    db = _db_session()
    try:
        active = _entity("entity-active", "Active Person")
        deprecated = _entity("entity-deprecated", "Deprecated Paper", entity_type="paper", status="deprecated")
        alias = EntityAlias(
            id="alias-deprecated",
            entity_id=deprecated.id,
            alias="Deprecated",
            normalized_key="deprecated",
        )
        mention = EntityMention(
            id="mention-deprecated",
            entity_id=deprecated.id,
            source_kind="document_chunk",
            source_id="chunk-deprecated",
            item_id="item-deprecated",
            surface_text="Deprecated Paper",
            normalized_key="DeprecatedPaper",
        )
        relation = EntityRelation(
            id="relation-deprecated",
            subject_entity_id=active.id,
            predicate="authored",
            object_entity_id=deprecated.id,
            source_kind="document_chunk",
            source_id="chunk-deprecated",
        )
        db.add_all([active, deprecated, alias, mention, relation])
        db.commit()

        graph = FakeGraph()
        result = project_entity_graph(db, graph)

        assert result.entity_count == 1
        assert result.alias_count == 0
        assert result.source_count == 0
        assert result.relation_count == 0
        assert [node["id"] for node in graph.entities] == ["entity-active"]
        assert graph.aliases == []
        assert graph.sources == []
        relation_endpoint_ids = {
            endpoint_id
            for relation in graph.relations
            for endpoint_id in (relation[1], relation[4])
        }
        assert "entity-deprecated" not in relation_endpoint_ids
    finally:
        db.close()


def test_project_entity_graph_skips_literal_only_and_dangling_relations():
    db = _db_session()
    try:
        active = _entity("entity-active", "Active Person")
        literal_relation = EntityRelation(
            id="relation-literal",
            subject_entity_id=active.id,
            predicate="has_email",
            object_literal="active@example.com",
            source_kind="manual",
            source_id="source-1",
        )
        dangling_relation = EntityRelation(
            id="relation-dangling",
            subject_entity_id=active.id,
            predicate="authored",
            object_entity_id="missing-entity",
            source_kind="manual",
            source_id="source-2",
        )
        db.add_all([active, literal_relation, dangling_relation])
        db.commit()

        graph = FakeGraph()
        result = project_entity_graph(db, graph)

        assert result.entity_count == 1
        assert result.relation_count == 0
        assert graph.relations == []
    finally:
        db.close()


def test_project_entity_graph_maps_unknown_predicate_to_related_to():
    db = _db_session()
    try:
        source = _entity("entity-source", "Source Entity")
        target = _entity("entity-target", "Target Entity", entity_type="organization")
        relation = EntityRelation(
            id="relation-unknown",
            subject_entity_id=source.id,
            predicate="collaborates_near",
            object_entity_id=target.id,
            source_kind="manual",
            source_id="source-1",
            evidence_span="Source collaborates near target",
            confidence=0.65,
            extraction_method="human",
        )
        db.add_all([source, target, relation])
        db.commit()

        graph = FakeGraph()
        result = project_entity_graph(db, graph)

        assert result.entity_count == 2
        assert result.relation_count == 1
        assert (
            "Entity",
            "entity-source",
            "RELATED_TO",
            "Entity",
            "entity-target",
            {
                "predicate": "collaborates_near",
                "confidence": 0.65,
                "evidence_span": "Source collaborates near target",
                "extraction_method": "human",
                "source_kind": "manual",
                "source_id": "source-1",
            },
        ) in graph.relations
    finally:
        db.close()


def test_project_entity_graph_counts_duplicate_mention_sources_once():
    db = _db_session()
    try:
        person = _entity("person-1", "Yanchao Tan")
        first = EntityMention(
            id="mention-1",
            entity_id=person.id,
            source_kind="document_chunk",
            source_id="chunk-1",
            item_id="item-1",
            surface_text="Yanchao Tan",
            normalized_key="YanchaoTan",
        )
        second = EntityMention(
            id="mention-2",
            entity_id=person.id,
            source_kind="document_chunk",
            source_id="chunk-1",
            item_id="item-1",
            surface_text="Tan",
            normalized_key="Tan",
        )
        db.add_all([person, first, second])
        db.commit()

        graph = FakeGraph()
        result = project_entity_graph(db, graph)

        assert result.entity_count == 1
        assert result.source_count == 1
        assert len(graph.sources) == 1
        assert sum(1 for relation in graph.relations if relation[2] == "MENTIONED_IN") == 2
    finally:
        db.close()


def test_project_entity_graph_does_not_use_wrong_user_item_title_for_mention_source():
    db = _db_session()
    try:
        wrong_user_item = KnowledgeItem(
            id="item-wrong-user",
            tenant_id="tenant-other",
            kb_uid="kb-other",
            user_id="other-user",
            title="Private Other User Title",
            content="paper text",
        )
        chunk = KnowledgeChunk(
            id="chunk-1",
            tenant_id="tenant-other",
            kb_uid="kb-other",
            file_uid="file-other",
            item_id=wrong_user_item.id,
            chunk_text="OpenViewer chunk",
        )
        person = _entity("person-1", "Yanchao Tan")
        mention = EntityMention(
            id="mention-1",
            entity_id=person.id,
            source_kind="document_chunk",
            source_id=chunk.id,
            surface_text="Yanchao Tan",
            normalized_key="YanchaoTan",
        )
        db.add_all([wrong_user_item, chunk, person, mention])
        db.commit()

        graph = FakeGraph()
        result = project_entity_graph(db, graph, user_id="default-user")

        assert result.source_count == 1
        assert graph.sources == [
            {
                "id": "document_chunk:chunk-1",
                "tenant_id": "tenant-other",
                "kb_uid": "kb-other",
                "source_kind": "document_chunk",
                "source_id": "chunk-1",
                "item_id": "item-wrong-user",
                "title": "chunk-1",
            }
        ]
    finally:
        db.close()


def test_project_asset_unit_entities_projects_source_mentions_and_relations():
    db = _db_session()
    try:
        unit = PersonalAssetUnit(
            id="unit-1",
            user_id="default-user",
            title="GraphRAG retrospective",
            summary="Summary",
            content="Entity-driven notes",
            status="confirmed",
        )
        entity_a = _entity("entity-a", "GraphRAG", entity_type="concept")
        entity_b = _entity("entity-b", "Neo4j", entity_type="tool")
        mention_a = EntityMention(
            id="mention-a",
            entity_id=entity_a.id,
            source_kind="personal_asset_unit",
            source_id=unit.id,
            item_id=None,
            chunk_id=None,
            surface_text="GraphRAG",
            normalized_key="graphrag",
            evidence_span="GraphRAG",
            confidence=0.8,
            extraction_method="test-extractor",
        )
        mention_b = EntityMention(
            id="mention-b",
            entity_id=entity_b.id,
            source_kind="personal_asset_unit",
            source_id=unit.id,
            item_id=None,
            chunk_id=None,
            surface_text="Neo4j",
            normalized_key="neo4j",
            evidence_span="Neo4j",
            confidence=0.8,
            extraction_method="test-extractor",
        )
        relation = EntityRelation(
            id="relation-asset-unit",
            subject_entity_id=entity_a.id,
            predicate="related_to",
            object_entity_id=entity_b.id,
            source_kind="personal_asset_unit",
            source_id=unit.id,
            evidence_span="GraphRAG uses Neo4j",
            confidence=0.7,
            extraction_method="test-extractor",
        )
        db.add_all([unit, entity_a, entity_b, mention_a, mention_b, relation])
        db.commit()

        graph = FakeGraph()
        result = project_asset_unit_entities(db, graph, asset_unit_id=unit.id, user_id="default-user")

        assert result == 3
        assert graph.sources == [
                {
                    "id": "personal_asset_unit:unit-1",
                    "tenant_id": "",
                    "kb_uid": "",
                "source_kind": "personal_asset_unit",
                "source_id": "unit-1",
                "item_id": "unit-1",
                "title": "GraphRAG retrospective",
            }
        ]
        assert {
            (
                node["id"],
                node["canonical_name"],
                node["entity_type"],
                node["normalized_key"],
            )
            for node in graph.entities
        } == {
            ("entity-a", "GraphRAG", "concept", "GraphRAG"),
            ("entity-b", "Neo4j", "tool", "Neo4j"),
        }
        assert (
            "Entity",
            "entity-a",
            "MENTIONED_IN",
            "Source",
            "personal_asset_unit:unit-1",
            {
                "confidence": 0.8,
                "evidence_span": "GraphRAG",
                "extraction_method": "test-extractor",
                "source_kind": "personal_asset_unit",
                "source_id": "unit-1",
            },
        ) in graph.relations
        assert (
            "Entity",
            "entity-b",
            "MENTIONED_IN",
            "Source",
            "personal_asset_unit:unit-1",
            {
                "confidence": 0.8,
                "evidence_span": "Neo4j",
                "extraction_method": "test-extractor",
                "source_kind": "personal_asset_unit",
                "source_id": "unit-1",
            },
        ) in graph.relations
        assert (
            "Entity",
            "entity-a",
            "RELATED_TO",
            "Entity",
            "entity-b",
            {
                "predicate": "related_to",
                "confidence": 0.7,
                "evidence_span": "GraphRAG uses Neo4j",
                "extraction_method": "test-extractor",
                "source_kind": "personal_asset_unit",
                "source_id": "unit-1",
            },
        ) in graph.relations
    finally:
        db.close()
