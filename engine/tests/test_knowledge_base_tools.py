from types import SimpleNamespace

from backend.app.models import KnowledgeFile, KnowledgeTopic


class FakeRetrievalService:
    def __init__(self):
        self.calls = []

    def query(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "status": "ok",
            "evidence": [{
                "tenant_id": "tenant-a",
                "kb_uid": kwargs["kb_uid"],
                "file_uid": "file-a",
                "chunk_uid": "chunk-a",
                "excerpt": "grounded text",
            }],
            "warnings": [],
        }


def _context(db_session, allowed=("kb-a",)):
    from engine.app.agent.tools.base import ToolContext
    from engine.app.security.knowledge_scope import AuthorizedKnowledgeScope

    service = FakeRetrievalService()
    return ToolContext(
        db=db_session,
        trace_id="trace-1",
        run_id="run-1",
        knowledge_scope=AuthorizedKnowledgeScope(
            actor_id="alice",
            tenant_id="tenant-a",
            allowed_kb_uids=allowed,
            run_id="run-1",
            expires_at=9999999999,
        ),
        retrieval_service=service,
    )


def _seed(db_session):
    topic = KnowledgeTopic(
        id="topic-a",
        kb_uid="kb-a",
        tenant_id="tenant-a",
        owner_user_id="alice",
        name="Safe KB",
        description="Description",
        status="active",
        mindmap={"status": "ready", "version": 2, "nodes": [{"id": "n1", "title": "Root"}]},
    )
    forbidden = KnowledgeTopic(
        id="topic-b",
        kb_uid="kb-b",
        tenant_id="tenant-a",
        owner_user_id="alice",
        name="Forbidden KB",
        status="active",
    )
    file_a = KnowledgeFile(
        id="row-a",
        file_uid="file-a",
        kb_uid="kb-a",
        tenant_id="tenant-a",
        topic_id="topic-a",
        title="Architecture Guide",
        original_filename="architecture.md",
        media_type="document",
        mime_type="text/markdown",
        parse_status="succeeded",
        content_text="alpha line\nneedle appears here\nomega line",
        storage_uri="local://secret/object",
        file_path="C:/secret/internal.md",
    )
    file_b = KnowledgeFile(
        id="row-b",
        file_uid="file-b",
        kb_uid="kb-a",
        tenant_id="tenant-a",
        topic_id="topic-a",
        title="Second Guide",
        original_filename="second.md",
        media_type="document",
        parse_status="succeeded",
        content_text="second body",
    )
    db_session.add_all([topic, forbidden, file_a, file_b])
    db_session.commit()


def test_query_kb_rejects_kb_outside_run_scope(db_session):
    from engine.app.agent.tools.knowledge_base import build_tools

    _seed(db_session)
    ctx = _context(db_session)
    result = build_tools(ctx)["query_kb"].invoke({"kb_uid": "kb-b", "query_text": "secret"})

    assert result["status"] == "error"
    assert result["error"]["code"] == "KB_NOT_ALLOWED"
    assert ctx.retrieval_service.calls == []


def test_list_kbs_returns_safe_fields_only(db_session):
    from engine.app.agent.tools.knowledge_base import build_tools

    _seed(db_session)
    result = build_tools(_context(db_session))["list_kbs"].invoke({})

    assert result["status"] == "ok"
    assert set(result["data"]["items"][0]) == {"kb_uid", "name", "description", "status"}
    assert [row["kb_uid"] for row in result["data"]["items"]] == ["kb-a"]


def test_query_kb_passes_only_verified_scope_and_strips_tenant(db_session):
    from engine.app.agent.tools.knowledge_base import build_tools

    _seed(db_session)
    ctx = _context(db_session)
    result = build_tools(ctx)["query_kb"].invoke({
        "kb_uid": "kb-a",
        "query_text": "architecture",
        "mode": "deep",
        "file_filter": ["file-a"],
    })

    assert result["status"] == "ok"
    assert ctx.retrieval_service.calls[0]["tenant_id"] == "tenant-a"
    assert "tenant_id" not in str(result)


def test_query_kb_normalizes_empty_warning_messages(db_session):
    from engine.app.agent.tools.knowledge_base import build_tools

    _seed(db_session)
    ctx = _context(db_session)
    ctx.retrieval_service.query = lambda **_kwargs: {
        "status": "degraded",
        "evidence": [],
        "warnings": [{"code": "RERANK_UNAVAILABLE", "message": ""}],
    }

    result = build_tools(ctx)["query_kb"].invoke({
        "kb_uid": "kb-a",
        "query_text": "architecture",
    })

    assert result["status"] == "degraded"
    assert result["warnings"][0]["message"] == "RERANK_UNAVAILABLE"


def test_search_file_is_scoped_and_cursor_paginated(db_session):
    from engine.app.agent.tools.knowledge_base import build_tools

    _seed(db_session)
    tool = build_tools(_context(db_session))["search_file"]
    first = tool.invoke({"kb_uid": "kb-a", "query": "Guide", "limit": 1})
    second = tool.invoke({"kb_uid": "kb-a", "query": "Guide", "limit": 1, "cursor": first["data"]["next_cursor"]})

    assert len(first["data"]["items"]) == 1
    assert len(second["data"]["items"]) == 1
    assert first["data"]["items"][0]["file_uid"] != second["data"]["items"][0]["file_uid"]
    assert "storage_uri" not in str(first)
    assert "file_path" not in str(first)


def test_search_file_matches_original_filename_when_title_is_missing(db_session):
    from engine.app.agent.tools.knowledge_base import build_tools

    _seed(db_session)
    file_row = db_session.query(KnowledgeFile).filter_by(file_uid="file-a").one()
    file_row.title = None
    file_row.original_filename = "The_Name_of_the_Title_Is_Hope.pdf"
    db_session.commit()

    result = build_tools(_context(db_session))["search_file"].invoke({
        "kb_uid": "kb-a",
        "query": "The_Name_of_the_Title_Is_Hope",
    })

    assert result["status"] == "ok"
    assert [item["file_uid"] for item in result["data"]["items"]] == ["file-a"]


def test_find_and_open_document_are_bounded_and_path_safe(db_session):
    from engine.app.agent.tools.knowledge_base import build_tools

    _seed(db_session)
    tools = build_tools(_context(db_session))
    found = tools["find_kb_document"].invoke({
        "kb_uid": "kb-a", "file_uid": "file-a", "patterns": ["needle"], "window_size": 10,
    })
    opened = tools["open_kb_document"].invoke({
        "kb_uid": "kb-a", "file_uid": "file-a", "offset": 0, "window_size": 12,
    })

    assert found["status"] == "ok" and found["data"]["matches"]
    assert opened["data"]["has_more_after"] is True
    assert opened["data"]["content"] == "alpha line\nn"
    assert "secret" not in str(found).lower()
    assert "storage_uri" not in str(opened)


def test_get_mindmap_and_registered_names_are_exact(db_session):
    from engine.app.agent.tools.knowledge_base import build_tools

    _seed(db_session)
    tools = build_tools(_context(db_session))
    result = tools["get_mindmap"].invoke({"kb_uid": "kb-a"})

    assert set(tools) == {
        "list_kbs", "query_kb", "search_file", "find_kb_document", "open_kb_document", "get_mindmap",
    }
    assert result["data"]["mindmap"]["version"] == 2
    for tool in tools.values():
        fields = set(tool.args_schema.model_fields)
        assert "actor_id" not in fields
        assert "tenant_id" not in fields
