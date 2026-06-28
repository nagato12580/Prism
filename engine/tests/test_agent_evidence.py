import os

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
