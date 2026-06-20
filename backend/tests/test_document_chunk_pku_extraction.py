import json

from backend.app.prompts.asset_parse import (
    ASSET_UNIT_PKU_RELATION_TYPES,
    ASSET_UNIT_PKU_UNIT_TYPES,
    build_document_chunk_pku_extraction_messages,
)


def test_build_document_chunk_pku_extraction_messages_include_anchor_context_schema():
    system_prompt, user_message = build_document_chunk_pku_extraction_messages(
        item_id="item-1",
        title="Hybrid retrieval guide",
        summary="Metadata filters and vector recall work together.",
        category="RAG",
        tags=["metadata", "retrieval"],
        source_type="manual",
        anchor_chunk={
            "id": "chunk-2",
            "text": "Metadata filters restrict retrieval results by source or project.",
            "index": 1,
        },
        previous_chunk={
            "id": "chunk-1",
            "text": "Hybrid retrieval combines keyword and vector recall.",
            "index": 0,
        },
        next_chunk={
            "id": "chunk-3",
            "text": "The filtered candidates are reranked before answering.",
            "index": 2,
        },
    )

    request = json.loads(user_message)

    assert "JSON" in system_prompt
    assert request["source_item"]["id"] == "item-1"
    assert request["source_item"]["title"] == "Hybrid retrieval guide"
    assert request["anchor_chunk"]["id"] == "chunk-2"
    assert request["anchor_chunk"]["text"] == "Metadata filters restrict retrieval results by source or project."
    assert request["context_chunks"]["previous"]["id"] == "chunk-1"
    assert request["context_chunks"]["next"]["id"] == "chunk-3"
    assert request["allowed_unit_types"] == ASSET_UNIT_PKU_UNIT_TYPES
    assert request["allowed_relation_types"] == ASSET_UNIT_PKU_RELATION_TYPES
    assert request["json_shape"]["pkus"][0]["local_id"] == "pku_1"
    assert request["json_shape"]["relations"][0]["source_local_id"] == "pku_1"
    assert any("anchor" in rule.lower() for rule in request["rules"])
