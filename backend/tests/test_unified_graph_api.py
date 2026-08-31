from backend.app.models import (
    EntityMention,
    EntityRelation,
    KnowledgeChunk,
    KnowledgeEntity,
    KnowledgeFile,
    KnowledgeItem,
    KnowledgeTopic,
    PersonalAssetUnit,
)
from backend.app.api.unified_graph import _cap_per_entity


def test_cap_per_entity_keeps_top_by_confidence_per_entity():
    from types import SimpleNamespace

    rows = [
        SimpleNamespace(entity_id="a", confidence=0.5),
        SimpleNamespace(entity_id="a", confidence=0.95),
        SimpleNamespace(entity_id="a", confidence=0.7),
        SimpleNamespace(entity_id="a", confidence=None),
        SimpleNamespace(entity_id="b", confidence=0.4),
    ]
    capped = _cap_per_entity(rows, lambda row: row.entity_id, 2)

    a_kept = [row.confidence for row in capped if row.entity_id == "a"]
    b_kept = [row.confidence for row in capped if row.entity_id == "b"]
    assert a_kept == [0.95, 0.7]
    assert b_kept == [0.4]
    assert len(capped) == 3


def _seed_unified_entity_graph(db_session):
    topic = KnowledgeTopic(
        tenant_id="default-user",
        owner_user_id="default-user",
        name="GraphRAG knowledge",
        active_graph_generation="graph-live",
    )
    db_session.add(topic)
    db_session.flush()

    item = KnowledgeItem(
        tenant_id=topic.tenant_id,
        kb_uid=topic.kb_uid,
        title="GraphRAG design doc",
        content="GraphRAG connects entities to evidence sources.",
        category="RAG",
        tags=["graph"],
        user_id="default-user",
    )
    unit = PersonalAssetUnit(
        title="GraphRAG research notes",
        content="GraphRAG and Neo4j appear together in research notes.",
        summary="Research note",
        category="Notes",
        tags=["graph"],
        status="confirmed",
        user_id="default-user",
    )
    db_session.add_all([item, unit])
    db_session.flush()

    chunk = KnowledgeChunk(
        tenant_id=topic.tenant_id,
        kb_uid=topic.kb_uid,
        file_uid="legacy-file",
        item_id=item.id,
        chunk_uid="legacy-chunk",
        generation=topic.active_graph_generation,
        chunk_text="GraphRAG links the same entity across multiple source types.",
        chunk_index=0,
        chunk_type="parent",
    )
    graph_rag = KnowledgeEntity(
        tenant_id=topic.tenant_id,
        kb_uid=topic.kb_uid,
        graph_generation=topic.active_graph_generation,
        user_id="default-user",
        entity_type="concept",
        canonical_name="GraphRAG",
        normalized_key="graphrag",
        description="Entity-centric retrieval pattern.",
        confidence=0.9,
        status="active",
    )
    neo4j = KnowledgeEntity(
        tenant_id=topic.tenant_id,
        kb_uid=topic.kb_uid,
        graph_generation=topic.active_graph_generation,
        user_id="default-user",
        entity_type="tool",
        canonical_name="Neo4j",
        normalized_key="neo4j",
        description="Graph database.",
        confidence=0.85,
        status="active",
    )
    deprecated = KnowledgeEntity(
        tenant_id=topic.tenant_id,
        kb_uid=topic.kb_uid,
        graph_generation=topic.active_graph_generation,
        user_id="default-user",
        entity_type="concept",
        canonical_name="LegacyGraph",
        normalized_key="legacygraph",
        description="Deprecated entity should be hidden.",
        confidence=0.4,
        status="deprecated",
    )
    db_session.add_all([chunk, graph_rag, neo4j, deprecated])
    db_session.flush()

    db_session.add_all(
        [
            EntityMention(
                tenant_id=topic.tenant_id,
                kb_uid=topic.kb_uid,
                graph_generation=topic.active_graph_generation,
                file_uid=chunk.file_uid,
                chunk_uid=chunk.chunk_uid,
                entity_id=graph_rag.id,
                source_kind="document_chunk",
                source_id=chunk.id,
                item_id=item.id,
                chunk_id=chunk.id,
                surface_text="GraphRAG",
                normalized_key="graphrag",
                evidence_span="GraphRAG links the same entity across multiple source types.",
                confidence=0.95,
                extraction_method="test",
            ),
            EntityMention(
                tenant_id=topic.tenant_id,
                kb_uid=topic.kb_uid,
                graph_generation=topic.active_graph_generation,
                entity_id=graph_rag.id,
                source_kind="personal_asset_unit",
                source_id=unit.id,
                surface_text="GraphRAG",
                normalized_key="graphrag",
                evidence_span="GraphRAG appears in research notes.",
                confidence=0.91,
                extraction_method="test",
            ),
            EntityMention(
                tenant_id=topic.tenant_id,
                kb_uid=topic.kb_uid,
                graph_generation=topic.active_graph_generation,
                entity_id=neo4j.id,
                source_kind="personal_asset_unit",
                source_id=unit.id,
                surface_text="Neo4j",
                normalized_key="neo4j",
                evidence_span="Neo4j appears in research notes.",
                confidence=0.87,
                extraction_method="test",
            ),
            EntityMention(
                tenant_id=topic.tenant_id,
                kb_uid=topic.kb_uid,
                graph_generation=topic.active_graph_generation,
                entity_id=deprecated.id,
                source_kind="personal_asset_unit",
                source_id=unit.id,
                surface_text="LegacyGraph",
                normalized_key="legacygraph",
                evidence_span="Deprecated entity mention.",
                confidence=0.3,
                extraction_method="test",
            ),
            EntityRelation(
                tenant_id=topic.tenant_id,
                kb_uid=topic.kb_uid,
                graph_generation=topic.active_graph_generation,
                subject_entity_id=graph_rag.id,
                predicate="uses",
                object_entity_id=neo4j.id,
                source_kind="personal_asset_unit",
                source_id=unit.id,
                evidence_span="GraphRAG commonly uses Neo4j.",
                confidence=0.8,
                extraction_method="test",
            ),
        ]
    )
    db_session.commit()

    return {
        "item": item,
        "chunk": chunk,
        "unit": unit,
        "graph_rag": graph_rag,
        "neo4j": neo4j,
        "deprecated": deprecated,
    }


def test_unified_graph_entity_view_returns_entity_and_source_nodes(client, db_session):
    seeded = _seed_unified_entity_graph(db_session)

    response = client.get("/api/v1/unified-graph")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) >= {"view", "nodes", "edges", "stats", "focus"}
    assert payload["view"] == "entity"
    assert payload["stats"]["node_count"] == len(payload["nodes"])
    assert payload["stats"]["edge_count"] == len(payload["edges"])

    nodes_by_id = {node["id"]: node for node in payload["nodes"]}
    graph_rag_node = next(
        node for node in payload["nodes"] if node["type"] == "entity" and node["label"] == "GraphRAG"
    )
    neo4j_node = next(
        node for node in payload["nodes"] if node["type"] == "entity" and node["label"] == "Neo4j"
    )
    chunk_node = next(node for node in payload["nodes"] if node["type"] == "document_chunk")
    asset_unit_node = next(node for node in payload["nodes"] if node["type"] == "personal_asset_unit")

    assert chunk_node["label"] == seeded["item"].title
    assert asset_unit_node["label"] == seeded["unit"].title
    assert "LegacyGraph" not in {node["label"] for node in payload["nodes"]}

    mentioned_in_edges = [edge for edge in payload["edges"] if edge["type"] == "mentioned_in"]
    related_edges = [edge for edge in payload["edges"] if edge["type"] == "related_to"]

    assert {
        edge["target"]
        for edge in mentioned_in_edges
        if edge["source"] == graph_rag_node["id"]
    } == {chunk_node["id"], asset_unit_node["id"]}
    assert related_edges == [
        {
            "id": related_edges[0]["id"],
            "source": graph_rag_node["id"],
            "target": neo4j_node["id"],
            "type": "related_to",
            "label": "uses",
            "confidence": 0.8,
            "evidence_span": "GraphRAG commonly uses Neo4j.",
            "predicate": "uses",
            "source_kind": "personal_asset_unit",
            "source_id": seeded["unit"].id,
        }
    ]
    assert nodes_by_id[chunk_node["id"]]["source_kind"] == "document_chunk"
    assert nodes_by_id[asset_unit_node["id"]]["source_kind"] == "personal_asset_unit"


def test_unified_graph_source_view_returns_source_nodes_and_mentions_edges(client, db_session):
    seeded = _seed_unified_entity_graph(db_session)

    response = client.get("/api/v1/unified-graph?view=source")

    assert response.status_code == 200
    payload = response.json()
    assert payload["view"] == "source"
    assert set(payload) >= {"view", "nodes", "edges", "stats", "focus"}

    nodes_by_id = {node["id"]: node for node in payload["nodes"]}
    source_nodes = [
        node
        for node in payload["nodes"]
        if node["type"] in {"document_chunk", "personal_asset_unit"}
    ]
    entity_nodes = [node for node in payload["nodes"] if node["type"] == "entity"]
    graph_rag_node = next(node for node in entity_nodes if node["label"] == "GraphRAG")
    chunk_source = next(node for node in source_nodes if node["source_kind"] == "document_chunk")
    asset_unit_source = next(node for node in source_nodes if node["source_kind"] == "personal_asset_unit")

    assert chunk_source["label"] == seeded["item"].title
    assert asset_unit_source["label"] == seeded["unit"].title
    assert "LegacyGraph" not in {node["label"] for node in entity_nodes}

    mention_edges = [edge for edge in payload["edges"] if edge["type"] == "mentions_entity"]
    assert mention_edges
    assert {nodes_by_id[edge["source"]]["type"] for edge in mention_edges} == {
        "document_chunk",
        "personal_asset_unit",
    }
    assert {nodes_by_id[edge["target"]]["type"] for edge in mention_edges} == {"entity"}
    assert {
        edge["source"]
        for edge in mention_edges
        if edge["target"] == graph_rag_node["id"]
    } == {chunk_source["id"], asset_unit_source["id"]}
    assert all(edge["type"] == "mentions_entity" for edge in payload["edges"])


def test_unified_graph_includes_active_scoped_knowledge_base_entities(client, db_session):
    topic = KnowledgeTopic(
        tenant_id="tenant-a",
        owner_user_id="alice",
        name="多视图知识库",
        active_graph_generation="graph-live",
    )
    db_session.add(topic)
    db_session.flush()
    item = KnowledgeItem(
        tenant_id=topic.tenant_id,
        kb_uid=topic.kb_uid,
        title="Multi-view paper",
        content="Multi-view clustering uses graph learning.",
    )
    db_session.add(item)
    db_session.flush()
    file_row = KnowledgeFile(
        tenant_id=topic.tenant_id,
        kb_uid=topic.kb_uid,
        topic_id=topic.id,
        item_id=item.id,
        file_uid="file-mv",
        original_filename="multi-view.pdf",
        parse_status="succeeded",
        graph_status="succeeded",
        parsed_content_version=1,
    )
    chunk = KnowledgeChunk(
        tenant_id=topic.tenant_id,
        kb_uid=topic.kb_uid,
        file_uid=file_row.file_uid,
        item_id=item.id,
        generation="1",
        chunk_uid="chunk-mv",
        chunk_text="Multi-view clustering uses graph learning.",
        chunk_type="child",
    )
    entity = KnowledgeEntity(
        tenant_id=topic.tenant_id,
        kb_uid=topic.kb_uid,
        graph_generation=topic.active_graph_generation,
        user_id="scoped-user",
        entity_type="concept",
        canonical_name="Multi-view clustering",
        normalized_key="multi-view clustering",
        status="active",
    )
    related = KnowledgeEntity(
        tenant_id=topic.tenant_id,
        kb_uid=topic.kb_uid,
        graph_generation=topic.active_graph_generation,
        user_id="scoped-user",
        entity_type="concept",
        canonical_name="Graph learning",
        normalized_key="graph learning",
        status="active",
    )
    stale = KnowledgeEntity(
        tenant_id=topic.tenant_id,
        kb_uid=topic.kb_uid,
        graph_generation="old-graph",
        user_id="scoped-user",
        entity_type="concept",
        canonical_name="Old graph entity",
        normalized_key="old graph entity",
        status="active",
    )
    db_session.add_all([file_row, chunk, entity, related, stale])
    db_session.flush()
    db_session.add_all([
        EntityMention(
            tenant_id=topic.tenant_id,
            kb_uid=topic.kb_uid,
            graph_generation=topic.active_graph_generation,
            file_uid=file_row.file_uid,
            chunk_uid=chunk.chunk_uid,
            entity_id=entity.id,
            source_kind="document_chunk",
            source_id=chunk.chunk_uid,
            item_id=item.id,
            chunk_id=chunk.chunk_uid,
            surface_text="Multi-view clustering",
            normalized_key="multi-view clustering",
            evidence_span="Multi-view clustering uses graph learning.",
        ),
        EntityMention(
            tenant_id=topic.tenant_id,
            kb_uid=topic.kb_uid,
            graph_generation=topic.active_graph_generation,
            file_uid=file_row.file_uid,
            chunk_uid=chunk.chunk_uid,
            entity_id=related.id,
            source_kind="document_chunk",
            source_id=chunk.chunk_uid,
            item_id=item.id,
            chunk_id=chunk.chunk_uid,
            surface_text="Graph learning",
            normalized_key="graph learning",
            evidence_span="Multi-view clustering uses graph learning.",
        ),
        EntityRelation(
            tenant_id=topic.tenant_id,
            kb_uid=topic.kb_uid,
            graph_generation=topic.active_graph_generation,
            file_uid=file_row.file_uid,
            subject_entity_id=entity.id,
            predicate="uses",
            object_entity_id=related.id,
            source_kind="document_chunk",
            source_id=chunk.chunk_uid,
            evidence_span="Multi-view clustering uses graph learning.",
        ),
    ])
    db_session.commit()

    response = client.get(
        "/api/v1/unified-graph?q=Multi-view&limit=20",
        headers={"X-Prism-Actor": "alice", "X-Prism-Tenant": "tenant-a"},
    )

    assert response.status_code == 200
    payload = response.json()
    labels = {node["label"] for node in payload["nodes"]}
    assert "Multi-view clustering" in labels
    assert "Graph learning" in labels
    assert "Old graph entity" not in labels
    source = next(node for node in payload["nodes"] if node["type"] == "document_chunk")
    assert source["label"] == "multi-view.pdf"
    assert source["knowledge_base"] == "多视图知识库"
    assert any(edge["type"] == "related_to" and edge["label"] == "uses" for edge in payload["edges"])


def test_unified_graph_excludes_hidden_active_graph_scopes(client, db_session):
    hidden_topic = KnowledgeTopic(
        tenant_id="legacy-personal",
        owner_user_id="default-user",
        name="Hidden Graph Smoke",
        governance_status="",
        active_graph_generation="graph-hidden",
    )
    db_session.add(hidden_topic)
    db_session.flush()

    item = KnowledgeItem(
        tenant_id=hidden_topic.tenant_id,
        kb_uid=hidden_topic.kb_uid,
        title="Hidden paper",
        content="Hidden graph data should not leak into unified graph.",
    )
    db_session.add(item)
    db_session.flush()

    file_row = KnowledgeFile(
        tenant_id=hidden_topic.tenant_id,
        kb_uid=hidden_topic.kb_uid,
        topic_id=hidden_topic.id,
        item_id=item.id,
        file_uid="file-hidden",
        original_filename="hidden.pdf",
        parse_status="succeeded",
        graph_status="succeeded",
        parsed_content_version=1,
    )
    chunk = KnowledgeChunk(
        tenant_id=hidden_topic.tenant_id,
        kb_uid=hidden_topic.kb_uid,
        file_uid=file_row.file_uid,
        item_id=item.id,
        generation="1",
        chunk_uid="chunk-hidden",
        chunk_text="Hidden graph data should not leak into unified graph.",
        chunk_type="child",
    )
    entity = KnowledgeEntity(
        tenant_id=hidden_topic.tenant_id,
        kb_uid=hidden_topic.kb_uid,
        graph_generation=hidden_topic.active_graph_generation,
        user_id="default-user",
        entity_type="concept",
        canonical_name="Hidden Entity",
        normalized_key="hidden entity",
        status="active",
    )
    db_session.add_all([file_row, chunk, entity])
    db_session.flush()
    db_session.add(
        EntityMention(
            tenant_id=hidden_topic.tenant_id,
            kb_uid=hidden_topic.kb_uid,
            graph_generation=hidden_topic.active_graph_generation,
            file_uid=file_row.file_uid,
            chunk_uid=chunk.chunk_uid,
            entity_id=entity.id,
            source_kind="document_chunk",
            source_id=chunk.chunk_uid,
            item_id=item.id,
            chunk_id=chunk.chunk_uid,
            surface_text="Hidden Entity",
            normalized_key="hidden entity",
            evidence_span="Hidden graph data should not leak into unified graph.",
        )
    )
    db_session.commit()

    response = client.get(
        "/api/v1/unified-graph",
        headers={"X-Prism-Actor": "default-user", "X-Prism-Tenant": "legacy-personal"},
    )

    assert response.status_code == 200
    assert response.json()["nodes"] == []
    assert response.json()["edges"] == []
