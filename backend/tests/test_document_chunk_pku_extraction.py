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


def test_extract_document_chunk_pkus_uses_main_llm_and_anchor_context(monkeypatch):
    from backend.app.models import KnowledgeChunk, KnowledgeItem
    from backend.app.services import knowledge_governance as kg

    captured = {}

    class FakeMessage:
        content = (
            '{"pkus":[{"local_id":"pku_1",'
            '"statement":"Metadata filters restrict retrieval by source.",'
            '"unit_type":"method",'
            '"evidence_span":"Metadata filters restrict retrieval by source.",'
            '"keywords":["metadata","retrieval"],'
            '"confidence":0.9}],'
            '"relations":[]}'
        )

    class FakeChoice:
        message = FakeMessage()

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return type("Response", (), {"choices": [FakeChoice()]})()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr(kg.settings, "LLM_API_BASE", "http://llm.local/v1")
    monkeypatch.setattr(kg.settings, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(kg.settings, "LLM_MODEL", "qwen-plus")
    monkeypatch.setattr(kg, "OpenAI", lambda base_url, api_key: FakeClient())

    item = KnowledgeItem(
        id="item-1",
        title="Hybrid retrieval",
        summary="Metadata filters help retrieval.",
        category="RAG",
        tags=["metadata"],
        source_type="manual",
        user_id="default-user",
    )
    previous = KnowledgeChunk(id="chunk-1", item_id="item-1", chunk_text="Hybrid retrieval combines signals.", chunk_type="parent")
    anchor = KnowledgeChunk(id="chunk-2", item_id="item-1", chunk_text="Metadata filters restrict retrieval by source.", chunk_type="parent")
    next_chunk = KnowledgeChunk(id="chunk-3", item_id="item-1", chunk_text="Reranking happens after filtering.", chunk_type="parent")

    result = kg._extract_document_chunk_pkus_with_llm(item, anchor, previous, next_chunk, anchor_index=1)

    request = json.loads(captured["messages"][1]["content"])
    assert captured["model"] == "qwen-plus"
    assert request["anchor_chunk"]["id"] == "chunk-2"
    assert request["context_chunks"]["previous"]["id"] == "chunk-1"
    assert request["context_chunks"]["next"]["id"] == "chunk-3"
    assert result.llm_model == "qwen-plus"
    assert result.pkus[0].statement == "Metadata filters restrict retrieval by source."
    assert result.pkus[0].unit_type == "method"
