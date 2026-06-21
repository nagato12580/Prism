from backend.app.models import KnowledgeChunk, KnowledgeItem, PKURelation, PersonalAssetUnit, PersonalKnowledgeUnit
from backend.app.services import knowledge_governance as kg
from backend.app.services.knowledge_governance import (
    settle_document_item_to_governance,
    settle_personal_asset_unit_to_governance,
)


def test_knowledge_graph_workbench_groups_ckp_pkus_sources_and_relations(client, db_session):
    from backend.app.models import CanonicalKnowledgePoint, PKUCanonicalLink

    item = KnowledgeItem(
        title="Hybrid retrieval notes",
        content="Metadata filters restrict retrieval before vector recall.",
        source_type="file",
        tags=["retrieval"],
        category="RAG",
        user_id="default-user",
    )
    db_session.add(item)
    db_session.flush()
    chunk = KnowledgeChunk(
        item_id=item.id,
        chunk_text="Metadata filters restrict retrieval before vector recall.",
        chunk_index=0,
        chunk_type="parent",
    )
    ckp = CanonicalKnowledgePoint(
        user_id="default-user",
        title="Hybrid retrieval",
        canonical_statement="Hybrid retrieval combines metadata filters with vector recall.",
        canonical_type="method",
        confidence=0.91,
        keywords=["hybrid", "retrieval"],
    )
    db_session.add_all([chunk, ckp])
    db_session.flush()

    first = PersonalKnowledgeUnit(
        user_id="default-user",
        source_kind="document_chunk",
        source_id=chunk.id,
        unit_type="method",
        statement="Metadata filters restrict retrieval before vector recall.",
        normalized_statement="Metadata filters restrict retrieval before vector recall.",
        normalized_statement_hash="workbench-pku-1",
        confidence=0.9,
        keywords=["metadata"],
    )
    second = PersonalKnowledgeUnit(
        user_id="default-user",
        source_kind="document_chunk",
        source_id=chunk.id,
        unit_type="method",
        statement="Vector recall retrieves semantically related chunks.",
        normalized_statement="Vector recall retrieves semantically related chunks.",
        normalized_statement_hash="workbench-pku-2",
        confidence=0.86,
        keywords=["vector"],
    )
    db_session.add_all([first, second])
    db_session.flush()
    db_session.add_all(
        [
            PKUCanonicalLink(
                user_id="default-user",
                pku_id=first.id,
                canonical_id=ckp.id,
                relation_type="same_as",
                role="external_reference",
                confidence=0.93,
                reason="First PKU supports the CKP.",
            ),
            PKUCanonicalLink(
                user_id="default-user",
                pku_id=second.id,
                canonical_id=ckp.id,
                relation_type="same_as",
                role="external_reference",
                confidence=0.88,
                reason="Second PKU supports the CKP.",
            ),
            PKURelation(
                user_id="default-user",
                source_pku_id=first.id,
                target_pku_id=second.id,
                relation_type="prerequisite",
                confidence=0.77,
                reason="Filtering happens before recall.",
                source_kind="document_chunk",
                source_id=chunk.id,
            ),
        ]
    )
    db_session.commit()

    response = client.get("/api/v1/knowledge-graph/workbench?q=hybrid")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ckps"][0]["id"] == f"ckp:{ckp.id}"
    assert payload["ckps"][0]["pku_count"] == 2
    assert payload["ckps"][0]["source_count"] == 1
    group = payload["groups"][f"ckp:{ckp.id}"]
    assert [entry["pku"]["id"] for entry in group["pkus"]] == [f"pku:{first.id}", f"pku:{second.id}"]
    assert group["pkus"][0]["link"]["reason"] == "First PKU supports the CKP."
    assert group["pkus"][0]["sources"][0]["node"]["id"] == f"chunk:{chunk.id}"
    assert group["relations"][0]["type"] == "pku_relation"
    assert group["relations"][0]["label"] == "prerequisite"


def test_knowledge_graph_returns_governance_nodes_and_edges(client, db_session, monkeypatch):
    unit = PersonalAssetUnit(
        title="Metadata filter practice",
        content="Metadata filter can restrict retrieval by source.",
        summary="Metadata filter restricts retrieval.",
        category="RAG",
        tags=["metadata", "filter"],
        source_asset_ids=["asset-1"],
        confidence={"overall": 0.9},
        status="confirmed",
        user_id="default-user",
    )
    item = KnowledgeItem(
        title="Metadata filter reference",
        content="Metadata filter can restrict retrieval by source.",
        summary="Metadata filter restricts retrieval.",
        category="RAG",
        tags=["metadata", "filter"],
        user_id="default-user",
    )
    db_session.add_all([unit, item])
    db_session.flush()
    db_session.add(
        KnowledgeChunk(
            item_id=item.id,
            chunk_text="Metadata filter can restrict retrieval by source.",
            chunk_type="parent",
        )
    )
    db_session.flush()

    monkeypatch.setattr(kg, "search_ckp_vectors", lambda **kwargs: [])
    monkeypatch.setattr(kg, "upsert_ckp_vector", lambda ckp: f"ckp:{ckp.id}")
    settle_personal_asset_unit_to_governance(db_session, unit)
    settle_document_item_to_governance(db_session, item.id)
    db_session.commit()

    response = client.get("/api/v1/knowledge-graph?q=metadata")

    assert response.status_code == 200
    payload = response.json()
    node_types = {node["type"] for node in payload["nodes"]}
    edge_types = {edge["type"] for edge in payload["edges"]}
    assert {"canonical", "pku", "personal_asset_unit", "document_chunk"}.issubset(node_types)
    assert {"canonical_pku", "pku_source"}.issubset(edge_types)
    assert payload["stats"]["node_count"] == len(payload["nodes"])


def test_knowledge_graph_returns_llm_extracted_pku_relations(client, db_session, monkeypatch):
    unit = PersonalAssetUnit(
        title="PKU extraction workflow",
        content="PKU extraction first extracts atomic points, then links prerequisite relations.",
        summary="PKU extraction creates atomic points and their relations.",
        category="Governance",
        tags=["pku"],
        source_asset_ids=["asset-1"],
        confidence={"overall": 0.9},
        status="confirmed",
        user_id="default-user",
    )
    db_session.add(unit)
    db_session.flush()

    first = PersonalKnowledgeUnit(
        user_id="default-user",
        source_kind="personal_asset_unit",
        source_id=unit.id,
        unit_type="method",
        statement="PKU extraction first extracts atomic knowledge points.",
        normalized_statement="PKU extraction first extracts atomic knowledge points.",
        normalized_statement_hash="graph-pku-a",
        modality="fact",
        keywords=["pku", "extraction"],
        status="active",
        confidence=0.9,
    )
    second = PersonalKnowledgeUnit(
        user_id="default-user",
        source_kind="personal_asset_unit",
        source_id=unit.id,
        unit_type="rule",
        statement="PKU relation creation links prerequisite relations between extracted points.",
        normalized_statement="PKU relation creation links prerequisite relations between extracted points.",
        normalized_statement_hash="graph-pku-b",
        modality="fact",
        keywords=["pku", "relation"],
        status="active",
        confidence=0.86,
    )
    db_session.add_all([first, second])
    db_session.flush()

    from backend.app.services.knowledge_governance import _create_or_get_ckp_from_pku, _create_or_get_generic_link

    monkeypatch.setattr(kg, "search_ckp_vectors", lambda **kwargs: [])
    monkeypatch.setattr(kg, "upsert_ckp_vector", lambda ckp: f"ckp:{ckp.id}")
    for pku in [first, second]:
        ckp = _create_or_get_ckp_from_pku(
            db_session,
            user_id="default-user",
            pku=pku,
            title=unit.title,
            summary=unit.summary or "",
            aliases=[unit.title],
            extra_meta={"created_from": "test"},
        )
        _create_or_get_generic_link(
            db_session,
            user_id="default-user",
            pku=pku,
            ckp=ckp,
            relation_type="same_as",
            role="synthesized_personal_knowledge",
            reason="test setup",
        )

    db_session.add(
        PKURelation(
            user_id="default-user",
            source_pku_id=first.id,
            target_pku_id=second.id,
            relation_type="prerequisite_of",
            confidence=0.82,
            reason="Atomic extraction happens before relation creation.",
            source_kind="personal_asset_unit",
            source_id=unit.id,
            llm_model="qwen-plus",
        )
    )
    db_session.commit()

    response = client.get("/api/v1/knowledge-graph?q=PKU")

    assert response.status_code == 200
    payload = response.json()
    relation_edges = [edge for edge in payload["edges"] if edge["type"] == "pku_relation"]
    assert len(relation_edges) == 1
    assert relation_edges[0]["label"] == "prerequisite_of"
    assert relation_edges[0]["source"] == f"pku:{first.id}"
    assert relation_edges[0]["target"] == f"pku:{second.id}"
    assert relation_edges[0]["confidence"] == 0.82
    assert relation_edges[0]["reason"] == "Atomic extraction happens before relation creation."
    assert relation_edges[0]["llm_model"] == "qwen-plus"
    assert payload["stats"]["edge_counts"]["pku_relation"] == 1


def test_knowledge_graph_updates_canonical_node(client, db_session, monkeypatch):
    unit = PersonalAssetUnit(
        title="RAG search explainability",
        content="RAG search should explain why each result matched.",
        summary="Search results need explanations.",
        category="RAG",
        tags=["search"],
        source_asset_ids=["asset-1"],
        confidence={"overall": 0.9},
        status="confirmed",
        user_id="default-user",
    )
    db_session.add(unit)
    db_session.flush()
    monkeypatch.setattr(kg, "search_ckp_vectors", lambda **kwargs: [])
    monkeypatch.setattr(kg, "upsert_ckp_vector", lambda ckp: f"ckp:{ckp.id}")
    settle_personal_asset_unit_to_governance(db_session, unit)
    db_session.commit()

    graph = client.get("/api/v1/knowledge-graph?q=search").json()
    canonical = next(node for node in graph["nodes"] if node["type"] == "canonical")

    response = client.patch(
        f"/api/v1/knowledge-graph/nodes/{canonical['id']}",
        json={
            "label": "Search result explainability",
            "summary": "Each recalled asset should say why it matched.",
            "keywords": ["search", "explainability"],
        },
    )

    assert response.status_code == 200
    updated = response.json()
    assert updated["label"] == "Search result explainability"
    assert updated["summary"] == "Each recalled asset should say why it matched."
    assert updated["keywords"] == ["search", "explainability"]


def test_knowledge_graph_updates_personal_asset_unit_node(client, db_session, monkeypatch):
    unit = PersonalAssetUnit(
        title="Interview prep draft",
        content="Collect AI interview questions into a stable study note.",
        summary="AI interview preparation note.",
        category="Interview",
        tags=["interview"],
        source_asset_ids=["asset-1"],
        confidence={"overall": 0.8},
        status="confirmed",
        user_id="default-user",
    )
    db_session.add(unit)
    db_session.flush()
    monkeypatch.setattr(kg, "search_ckp_vectors", lambda **kwargs: [])
    monkeypatch.setattr(kg, "upsert_ckp_vector", lambda ckp: f"ckp:{ckp.id}")
    settle_personal_asset_unit_to_governance(db_session, unit)
    db_session.commit()

    graph = client.get("/api/v1/knowledge-graph?q=interview").json()
    asset_unit = next(node for node in graph["nodes"] if node["type"] == "personal_asset_unit")

    response = client.patch(
        f"/api/v1/knowledge-graph/nodes/{asset_unit['id']}",
        json={
            "label": "AI interview study note",
            "text": "Updated study note content.",
            "summary": "Updated summary.",
            "category": "Career",
            "tags": ["interview", "ai"],
        },
    )

    assert response.status_code == 200
    updated = response.json()
    assert updated["type"] == "personal_asset_unit"
    assert updated["label"] == "AI interview study note"
    assert updated["text"] == "Updated study note content."
    assert updated["summary"] == "Updated summary."
    assert updated["category"] == "Career"
    assert updated["tags"] == ["interview", "ai"]
