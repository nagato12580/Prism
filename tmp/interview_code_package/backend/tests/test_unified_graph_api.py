from backend.app.models import (
    EntityMention,
    EntityRelation,
    KnowledgeChunk,
    KnowledgeEntity,
    KnowledgeItem,
    PersonalAssetUnit,
)


def _seed_unified_entity_graph(db_session):
    item = KnowledgeItem(
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
        item_id=item.id,
        chunk_text="GraphRAG links the same entity across multiple source types.",
        chunk_index=0,
        chunk_type="parent",
    )
    graph_rag = KnowledgeEntity(
        user_id="default-user",
        entity_type="concept",
        canonical_name="GraphRAG",
        normalized_key="graphrag",
        description="Entity-centric retrieval pattern.",
        confidence=0.9,
        status="active",
    )
    neo4j = KnowledgeEntity(
        user_id="default-user",
        entity_type="tool",
        canonical_name="Neo4j",
        normalized_key="neo4j",
        description="Graph database.",
        confidence=0.85,
        status="active",
    )
    deprecated = KnowledgeEntity(
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
