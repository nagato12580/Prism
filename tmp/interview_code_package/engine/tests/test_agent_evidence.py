import os
import json

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

from engine.app.agent.tools.evidence import normalize_evidence_items


def test_normalize_document_source_to_evidence_item():
    payload = {
        "sources": [
            {
                "source_kind": "document_chunk",
                "source_id": "chunk-1",
                "chunk_id": "chunk-1",
                "parent_id": "parent-1",
                "item_id": "item-1",
                "display_title": "Doc",
                "snippet": "text",
                "score": 0.8,
                "chunk_type": "child",
                "chunk_index": 2,
            }
        ]
    }

    items = normalize_evidence_items("raw_document_search", payload)

    assert items == [
        {
            "evidence_id": "document_chunk:chunk-1",
            "source_kind": "document_chunk",
            "source_id": "chunk-1",
            "chunk_id": "chunk-1",
            "parent_chunk_id": "parent-1",
            "item_id": "item-1",
            "display_title": "Doc",
            "excerpt": "text",
            "hit_reason": "matched raw_document_search result",
            "score": 0.8,
            "retrieval_path": ["raw_document_search"],
            "metadata": {"chunk_type": "child", "chunk_index": 2},
        }
    ]


def test_normalize_material_raw_evidence():
    payload = {
        "materials": [
            {
                "raw_evidence": [
                    {
                        "source_kind": "document_chunk",
                        "source_id": "chunk-2",
                        "chunk_id": "chunk-2",
                        "item_id": "item-2",
                        "display_title": "Doc 2",
                        "text": "material text",
                    }
                ]
            }
        ]
    }

    items = normalize_evidence_items("knowledge_material_search", payload)

    assert items[0]["evidence_id"] == "document_chunk:chunk-2"
    assert items[0]["excerpt"] == "material text"


def test_normalize_preserves_explicit_zero_score():
    payload = {
        "sources": [
            {
                "source_kind": "document_chunk",
                "source_id": "chunk-zero",
                "chunk_id": "chunk-zero",
                "text": "zero score text",
                "score": 0,
                "raw_score": 0.72,
            }
        ]
    }

    items = normalize_evidence_items("raw_document_search", payload)

    assert items[0]["score"] == 0.0


def test_normalize_skips_source_without_excerpt():
    payload = {
        "sources": [
            {
                "source_kind": "document_chunk",
                "source_id": "chunk-id-only",
                "chunk_id": "chunk-id-only",
            }
        ]
    }

    assert normalize_evidence_items("raw_document_search", payload) == []


def test_normalize_metadata_is_json_serializable():
    class Unserializable:
        pass

    payload = {
        "sources": [
            {
                "source_kind": "document_chunk",
                "source_id": "chunk-meta",
                "chunk_id": "chunk-meta",
                "text": "metadata text",
                "chunk_index": Unserializable(),
                "display_id": Unserializable(),
            }
        ]
    }

    items = normalize_evidence_items("raw_document_search", payload)

    json.dumps(items)
    assert isinstance(items[0]["metadata"]["chunk_index"], str)
    assert isinstance(items[0]["metadata"]["display_id"], str)


def test_normalize_graph_rag_source_to_evidence_item():
    payload = {
        "sources": [
            {
                "source_kind": "personal_asset_unit",
                "source_id": "u1",
                "title": "Asset 1",
                "summary": "Asset summary",
                "graph_rag": {
                    "path": [{"node_id": "e1", "node_type": "entity"}],
                    "explain": {"why": "expanded from seed", "evidence_type": "INFERRED"},
                },
            }
        ]
    }

    items = normalize_evidence_items("knowledge_search", payload)

    assert items[0]["metadata"]["graph_path"][0]["node_id"] == "e1"
    assert items[0]["metadata"]["graph_explain"]["evidence_type"] == "INFERRED"
    assert items[0]["metadata"]["evidence_type"] == "INFERRED"
