import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database import Base
from backend.app.models.knowledge_item import KnowledgeChunk, KnowledgeItem
from engine.app.agent.tools.base import BUILTIN_REGISTRY, ToolContext
import engine.app.agent.tools.page_index as page_index_tool
from engine.app.retrieval.page_index import PageIndexService


def _session_with_document():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    item_scope = {"tenant_id": "tenant-test", "kb_uid": "kb-test"}
    chunk_scope = {**item_scope, "file_uid": "file-test", "generation": "gen-test"}
    item = KnowledgeItem(
        id="item-1",
        **item_scope,
        title="Attention Residuals",
        content="full document text",
        source_type="file",
        user_id="default-user",
    )
    parent_1 = KnowledgeChunk(
        id="parent-1",
        chunk_uid="parent-public-1",
        **chunk_scope,
        item_id="item-1",
        chunk_text="# Introduction\nAttention residuals are shortcuts.",
        chunk_index=0,
        chunk_type="parent",
        extra_meta={"page_start": 1, "page_end": 2, "heading": "Introduction"},
    )
    child_1 = KnowledgeChunk(
        id="child-1",
        chunk_uid="child-public-1",
        **chunk_scope,
        item_id="item-1",
        chunk_text="Attention residuals are shortcuts on page one.",
        chunk_index=0,
        chunk_type="child",
        parent_id="parent-1",
        extra_meta={"page_start": 1, "page_end": 1},
    )
    child_2 = KnowledgeChunk(
        id="child-2",
        chunk_uid="child-public-2",
        **chunk_scope,
        item_id="item-1",
        chunk_text="Residual analysis continues on page two.",
        chunk_index=1,
        chunk_type="child",
        parent_id="parent-1",
        extra_meta={"page_start": 2, "page_end": 2},
    )
    parent_2 = KnowledgeChunk(
        id="parent-2",
        chunk_uid="parent-public-2",
        **chunk_scope,
        item_id="item-1",
        chunk_text="# Experiments\nResults compare residual layers.",
        chunk_index=1,
        chunk_type="parent",
        extra_meta={"page_start": 3, "page_end": 3, "heading": "Experiments"},
    )
    child_3 = KnowledgeChunk(
        id="child-3",
        chunk_uid="child-public-3",
        **chunk_scope,
        item_id="item-1",
        chunk_text="Experiments compare residual layers on page three.",
        chunk_index=0,
        chunk_type="child",
        parent_id="parent-2",
        extra_meta={"page_start": 3, "page_end": 3},
    )
    session.add_all([item, parent_1, child_1, child_2, parent_2, child_3])
    session.commit()
    return Session


def test_page_index_service_returns_document_metadata_and_structure():
    Session = _session_with_document()
    service = PageIndexService(Session)

    metadata = service.get_document("item-1")
    structure = service.get_document_structure("item-1")

    assert metadata["status"] == "ready"
    assert metadata["doc_id"] == "item-1"
    assert metadata["name"] == "Attention Residuals"
    assert metadata["page_count"] == 3
    assert metadata["chunk_count"] == 5
    assert structure["doc_id"] == "item-1"
    assert [section["title"] for section in structure["sections"]] == [
        "Introduction",
        "Experiments",
    ]
    assert structure["sections"][0]["pages"] == "1-2"
    assert structure["sections"][0]["children"][0]["chunk_id"] == "child-1"


def test_page_index_service_returns_tight_page_content_ranges():
    Session = _session_with_document()
    service = PageIndexService(Session)

    payload = service.get_page_content("item-1", "2-3")

    assert payload["doc_id"] == "item-1"
    assert payload["pages"] == "2-3"
    assert [page["page"] for page in payload["pages_content"]] == [2, 3]
    assert "page two" in payload["pages_content"][0]["text"]
    assert "page three" in payload["pages_content"][1]["text"]
    assert "page one" not in payload["pages_content"][0]["text"]


def test_page_index_tool_records_citations_and_stats(monkeypatch):
    Session = _session_with_document()
    monkeypatch.setattr(page_index_tool, "_Session", Session)

    ctx = ToolContext(rag_runner=None, citations=[], stats_holder={})
    tool = BUILTIN_REGISTRY["page_index_get_page_content"].builder(ctx)

    text = tool.invoke({"doc_id": "item-1", "pages": "1"})
    payload = json.loads(text)

    assert payload["status"] == "success"
    assert payload["pages"] == "1"
    assert ctx.stats_holder["page_index_get_page_content"]["page_count"] == 1
    assert ctx.citations == [
        {
            "source": "page_index",
            "doc_id": "item-1",
            "page": 1,
            "chunk_ids": ["child-1"],
        }
    ]
