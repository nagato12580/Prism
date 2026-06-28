import json
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

from engine.app.agent.tools.base import ToolContext
from engine.app.agent.tools.evidence import normalize_evidence_items
from engine.app.agent.tools.knowledge import build as build_knowledge_search


class FakeRagResult:
    status = "sufficient"
    summary = "found"
    missing = []
    clarify = None
    iterations = 1
    sources = [
        {
            "source_kind": "document_chunk",
            "source_id": "c1",
            "chunk_id": "c1",
            "item_id": "i1",
            "display_title": "Doc",
            "text": "source text",
            "score": 1.0,
            "chunk_type": "child",
            "chunk_index": 2,
        }
    ]
    evidence = []


class FakeRagRunner:
    def run(self, query):
        return FakeRagResult()


def test_knowledge_search_payload_includes_evidence_items():
    tool = build_knowledge_search(ToolContext(rag_runner=FakeRagRunner()))
    payload = json.loads(tool.invoke({"query": "q"}))

    assert payload["evidence_items"][0]["evidence_id"] == "document_chunk:c1"
    assert payload["evidence_items"][0]["chunk_id"] == "c1"
    assert payload["evidence_items"][0]["excerpt"] == "source text"


def test_payload_json_with_evidence_items_is_serializable():
    payload = {
        "status": "sufficient",
        "summary": "found",
        "sources": [
            {
                "source_kind": "document_chunk",
                "source_id": "chunk-1",
                "chunk_id": "chunk-1",
                "item_id": "item-1",
                "display_title": "Doc",
                "snippet": "text",
                "score": 1.0,
            }
        ],
    }

    payload["evidence_items"] = normalize_evidence_items("raw_document_search", payload)

    serialized = json.loads(json.dumps(payload, ensure_ascii=False))
    assert serialized["evidence_items"][0]["chunk_id"] == "chunk-1"
