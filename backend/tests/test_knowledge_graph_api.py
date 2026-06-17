from backend.app.models import KnowledgeChunk, KnowledgeItem, PersonalAssetItem
from backend.app.services.knowledge_governance import (
    settle_document_item_to_governance,
    settle_personal_asset_item_to_governance,
)


def test_knowledge_graph_returns_governance_nodes_and_edges(client, db_session):
    asset = PersonalAssetItem(
        raw_text="我认为个人知识库需要 metadata filter 辅助检索。",
        title="个人知识库检索观点",
        body="我认为个人知识库需要 metadata filter 辅助检索。",
        summary="个人知识库需要 metadata filter。",
        asset_kind="opinion",
        category="RAG",
        tags=["metadata", "filter"],
        extracts=[{"type": "claim", "content": "个人知识库需要 metadata filter。", "confidence": 0.9}],
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
    db_session.add_all([asset, item])
    db_session.flush()
    db_session.add(
        KnowledgeChunk(
            item_id=item.id,
            chunk_text="Metadata filter can restrict retrieval by source.",
            chunk_type="parent",
        )
    )
    db_session.flush()

    settle_personal_asset_item_to_governance(db_session, asset)
    settle_document_item_to_governance(db_session, item.id)
    db_session.commit()

    response = client.get("/api/v1/knowledge-graph?q=metadata")

    assert response.status_code == 200
    payload = response.json()
    node_types = {node["type"] for node in payload["nodes"]}
    edge_types = {edge["type"] for edge in payload["edges"]}
    assert {"canonical", "pku", "asset", "document_chunk"}.issubset(node_types)
    assert {"canonical_pku", "pku_source"}.issubset(edge_types)
    assert payload["stats"]["node_count"] == len(payload["nodes"])
