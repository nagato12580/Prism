import json
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

from engine.app.agent.tools.base import ToolContext
from engine.app.agent.tools.evidence import normalize_evidence_items
from engine.app.agent.tools.knowledge import build as build_knowledge_search
from engine.app.agent.tools import knowledge_governance


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


class FailingRagRunner:
    def run(self, query):
        raise AssertionError("direct raw chunk lookup should not call rag runner")


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


def test_raw_chunk_direct_lookup_payload_includes_evidence_items(monkeypatch):
    chunk = type(
        "Chunk",
        (),
        {
            "id": "abcdef12-3456-7890-abcd-ef1234567890",
            "item_id": "item-1",
            "chunk_text": "direct chunk text",
            "chunk_index": 3,
            "chunk_type": "child",
            "parent_id": "parent-1",
        },
    )()
    item = type("Item", (), {"id": "item-1", "title": "Item Title"})()
    file = type("File", (), {"item_id": "item-1", "title": "File Title", "original_filename": "file.pdf"})()

    class FakeQuery:
        def __init__(self, model):
            self.model = model

        def filter(self, *args):
            return self

        def order_by(self, *args):
            return self

        def first(self):
            if self.model is knowledge_governance.KnowledgeChunk:
                return chunk
            if self.model is knowledge_governance.KnowledgeItem:
                return item
            if self.model is knowledge_governance.KnowledgeFile:
                return file
            return None

    class FakeSession:
        def query(self, model):
            return FakeQuery(model)

        def close(self):
            pass

    monkeypatch.setattr(knowledge_governance, "_new_db_session", lambda: FakeSession())

    payload = knowledge_governance._raw_chunk_payload_from_query("chunk_id: abcdef12-3456-7890-abcd-ef1234567890")

    assert payload is not None
    assert payload["evidence_items"][0]["evidence_id"] == "document_chunk:abcdef12-3456-7890-abcd-ef1234567890"
    assert payload["evidence_items"][0]["excerpt"] == "direct chunk text"
    assert payload["sources"][0]["parent_chunk_id"] == "parent-1"


def test_raw_chunk_direct_lookup_ignores_generic_source_labels(monkeypatch):
    def fail_session():
        raise AssertionError("generic source-like labels must not query the database")

    monkeypatch.setattr(knowledge_governance, "_new_db_session", fail_session)

    assert knowledge_governance._raw_chunk_payload_from_query("resource: abcdef12") is None
    assert knowledge_governance._raw_chunk_payload_from_query("source: 20240101") is None
    assert knowledge_governance._raw_chunk_payload_from_query("chunk: abcdef123456") is None
    assert knowledge_governance._extract_chunk_id_token("please read abcdef12-3456-7890-abcd-ef1234567890") is None
    assert (
        knowledge_governance._raw_chunk_payload_from_query(
            "please read abcdef12-3456-7890-abcd-ef1234567890"
        )
        is None
    )


def test_raw_chunk_direct_lookup_rejects_ambiguous_prefix(monkeypatch):
    chunks = [
        type(
            "Chunk",
            (),
            {
                "id": "abcdef123456-0000-0000-0000-000000000000",
                "item_id": "item-1",
                "chunk_text": "first text",
                "chunk_index": 1,
                "chunk_type": "child",
                "parent_id": None,
            },
        )(),
        type(
            "Chunk",
            (),
            {
                "id": "abcdef123456-1111-1111-1111-111111111111",
                "item_id": "item-2",
                "chunk_text": "second text",
                "chunk_index": 2,
                "chunk_type": "child",
                "parent_id": None,
            },
        )(),
    ]

    class FakeQuery:
        def __init__(self, model):
            self.model = model

        def filter(self, *args):
            return self

        def order_by(self, *args):
            return self

        def limit(self, value):
            return self

        def all(self):
            if self.model is knowledge_governance.KnowledgeChunk:
                return chunks
            return []

        def first(self):
            if self.model is knowledge_governance.KnowledgeChunk:
                return chunks[0]
            return None

    class FakeSession:
        def query(self, model):
            return FakeQuery(model)

        def close(self):
            pass

    monkeypatch.setattr(knowledge_governance, "_new_db_session", lambda: FakeSession())

    assert knowledge_governance._raw_chunk_payload_from_query("source_id: abcdef123456") is None


def test_raw_document_search_falls_back_when_direct_lookup_db_fails(monkeypatch):
    from engine.app.agent.tools.knowledge_governance import _build_raw_document_search

    def fail_session():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(knowledge_governance, "_new_db_session", fail_session)
    ctx = ToolContext(rag_runner=None)

    payload = json.loads(
        _build_raw_document_search(ctx).invoke(
            {"query": "chunk_id: abcdef12-3456-7890-abcd-ef1234567890"}
        )
    )

    assert payload["status"] == "insufficient"
    assert payload["summary"] == "Raw document search is not configured."
    assert payload["missing"] == ["No RAG runner is available."]
    assert payload["sources"] == []
    assert payload["evidence"] == []
    assert payload["evidence_items"] == []


def test_raw_document_search_uses_direct_chunk_lookup(monkeypatch):
    from engine.app.agent.tools.knowledge_governance import _build_raw_document_search

    direct_payload = {
        "status": "sufficient",
        "summary": "Found the requested raw document chunk by source_id.",
        "sources": [
            {
                "source_kind": "document_chunk",
                "source_id": "abcdef12",
                "chunk_id": "abcdef12",
                "text": "direct text",
            }
        ],
        "evidence": [],
        "missing": [],
        "evidence_items": [
            {
                "evidence_id": "document_chunk:abcdef12",
                "chunk_id": "abcdef12",
                "excerpt": "direct text",
            }
        ],
    }
    monkeypatch.setattr(knowledge_governance, "_raw_chunk_payload_from_query", lambda query: direct_payload)
    ctx = ToolContext(rag_runner=FailingRagRunner())

    payload = json.loads(_build_raw_document_search(ctx).invoke({"query": "chunk_id: abcdef12"}))

    assert payload["evidence_items"][0]["chunk_id"] == "abcdef12"
    assert ctx.stats_holder["raw_document_search"]["direct_lookup"] is True
