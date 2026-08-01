import base64
import json

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


class CoverageRetrievalService:
    def __init__(self, global_file_uids=(), unavailable_file_uids=()):
        self.calls = []
        self.global_file_uids = tuple(global_file_uids)
        self.unavailable_file_uids = set(unavailable_file_uids)

    @staticmethod
    def _evidence(kb_uid, file_uid, suffix):
        return {
            "kb_uid": kb_uid,
            "file_uid": file_uid,
            "chunk_uid": f"chunk-{file_uid}-{suffix}",
            "excerpt": f"evidence for {file_uid}",
        }

    def query(self, **kwargs):
        self.calls.append(kwargs)
        requested = tuple(kwargs["file_uids"])
        if len(requested) == 1:
            file_uid = requested[0]
            if file_uid in self.unavailable_file_uids:
                return {
                    "status": "unavailable",
                    "evidence": [],
                    "warnings": [{"code": "FILE_UNAVAILABLE", "message": file_uid}],
                    "retrieval_health": {file_uid: "unavailable"},
                }
            return {
                "status": "ok",
                "evidence": [self._evidence(kwargs["kb_uid"], file_uid, "directed")],
                "warnings": [],
                "retrieval_health": {file_uid: "ok"},
            }
        return {
            "status": "ok",
            "evidence": [
                self._evidence(kwargs["kb_uid"], file_uid, f"global-{index}")
                for index, file_uid in enumerate(self.global_file_uids)
            ],
            "warnings": [],
            "retrieval_health": {"global": "ok"},
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


def _seed_numbered_files(db_session, count):
    topic = KnowledgeTopic(
        id="topic-a",
        kb_uid="kb-a",
        tenant_id="tenant-a",
        owner_user_id="alice",
        name="Safe KB",
        status="active",
    )
    files = [
        KnowledgeFile(
            id=f"row-{index:03d}",
            file_uid=f"file-{index:03d}",
            kb_uid="kb-a",
            tenant_id="tenant-a",
            topic_id="topic-a",
            title=f"Paper {index:03d}",
            parse_status="succeeded" if index else "pending",
            content_text=f"body {index}",
        )
        for index in range(count)
    ]
    db_session.add_all([topic, *files])
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
    assert ctx.retrieval_service.calls[0]["depth"] == "standard"
    assert ctx.retrieval_service.calls[0]["max_iterations"] == 3
    assert "tenant_id" not in str(result)


def test_query_kb_uses_chat_deep_search_depth_controls(db_session):
    from engine.app.agent.tools.knowledge_base import build_tools

    _seed(db_session)
    ctx = _context(db_session)
    ctx.deep_search_enabled = True
    ctx.deep_search_depth = "deep"
    ctx.deep_search_top_k = 18
    ctx.graph_hops = 3
    ctx.rag_max_iterations = 5

    result = build_tools(ctx)["query_kb"].invoke({
        "kb_uid": "kb-a",
        "query_text": "architecture",
    })

    assert result["status"] == "ok"
    call = ctx.retrieval_service.calls[0]
    assert call["mode"] == "deep"
    assert call["depth"] == "deep"
    assert call["top_k"] == 18
    assert call["graph_hops"] == 3
    assert call["max_iterations"] == 5


def test_query_kb_resolves_file_filter_filenames_to_file_uids(db_session):
    from engine.app.agent.tools.knowledge_base import build_tools

    _seed(db_session)
    ctx = _context(db_session)
    result = build_tools(ctx)["query_kb"].invoke({
        "kb_uid": "kb-a",
        "query_text": "architecture",
        "file_filter": ["architecture.md"],
    })

    assert result["status"] == "ok"
    assert ctx.retrieval_service.calls[0]["file_uids"] == ("file-a",)


def test_query_kb_maps_default_to_single_authorized_kb(db_session):
    from engine.app.agent.tools.knowledge_base import build_tools

    _seed(db_session)
    ctx = _context(db_session, allowed=("kb-a",))
    result = build_tools(ctx)["query_kb"].invoke({
        "kb_uid": "default",
        "query_text": "architecture",
    })

    assert result["status"] == "ok"
    assert ctx.retrieval_service.calls[0]["kb_uid"] == "kb-a"


def test_query_kb_maps_missing_kb_uid_to_single_authorized_kb(db_session):
    from engine.app.agent.tools.knowledge_base import build_tools

    _seed(db_session)
    ctx = _context(db_session, allowed=("kb-a",))
    result = build_tools(ctx)["query_kb"].invoke({
        "query_text": "architecture",
    })

    assert result["status"] == "ok"
    assert ctx.retrieval_service.calls[0]["kb_uid"] == "kb-a"


def test_query_kb_defaults_to_all_authorized_kbs_when_multiple_scoped(db_session):
    from engine.app.agent.tools.knowledge_base import build_tools

    ctx = _context(db_session, allowed=("kb-main", "kb-inbox"))

    result = build_tools(ctx)["query_kb"].invoke({
        "query_text": "architecture",
    })

    assert result["status"] == "ok"
    assert [call["kb_uid"] for call in ctx.retrieval_service.calls] == [
        "kb-main",
        "kb-inbox",
    ]
    assert [item["kb_uid"] for item in result["data"]["evidence"]] == [
        "kb-main",
        "kb-inbox",
    ]


def test_query_kb_per_file_coverage_rejects_all_when_multiple_scoped(db_session):
    from engine.app.agent.tools.knowledge_base import build_tools

    ctx = _context(db_session, allowed=("kb-main", "kb-inbox"))

    result = build_tools(ctx)["query_kb"].invoke({
        "kb_uid": "all",
        "query_text": "architecture",
        "coverage": "per_file",
    })

    assert result["status"] == "error"
    assert result["error"]["code"] == "INVALID_REQUEST"
    assert result["error"]["message"] == (
        "coverage='per_file' requires exactly one knowledge base"
    )
    assert ctx.retrieval_service.calls == []


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


def test_query_kb_relevance_keeps_single_top_ten_call_without_coverage(db_session):
    from engine.app.agent.tools.knowledge_base import build_tools

    _seed(db_session)
    ctx = _context(db_session)

    result = build_tools(ctx)["query_kb"].invoke({
        "kb_uid": "kb-a",
        "query_text": "architecture",
    })

    assert result["status"] == "ok"
    assert result["data"]["coverage"] is None
    assert len(ctx.retrieval_service.calls) == 1
    assert ctx.retrieval_service.calls[0]["top_k"] == 10


def test_query_kb_per_file_coverage_fills_all_eleven_files(db_session):
    from engine.app.agent.tools.knowledge_base import build_tools

    _seed_numbered_files(db_session, 11)
    service = CoverageRetrievalService(global_file_uids=("file-000",) * 10)
    ctx = _context(db_session)
    ctx.retrieval_service = service

    result = build_tools(ctx)["query_kb"].invoke({
        "kb_uid": "kb-a",
        "query_text": "summarize every paper",
        "coverage": "per_file",
    })

    expected = [f"file-{index:03d}" for index in range(11)]
    coverage = result["data"]["coverage"]
    assert result["status"] == "ok"
    assert coverage == {
        "requested_file_uids": expected,
        "covered_file_uids": expected,
        "missing_file_uids": [],
        "complete": True,
        "next_cursor": None,
    }
    assert [item["file_uid"] for item in result["data"]["evidence"]] == expected
    assert len({item["file_uid"] for item in result["data"]["evidence"]}) == 11
    assert service.calls[0]["top_k"] == 22
    assert [call["file_uids"] for call in service.calls[1:]] == [
        (file_uid,) for file_uid in expected[1:]
    ]
    assert all(call["mode"] == "fast" and call["top_k"] == 1 for call in service.calls[1:])


def test_query_kb_per_file_coverage_only_directs_missing_files(db_session):
    from engine.app.agent.tools.knowledge_base import build_tools

    _seed_numbered_files(db_session, 4)
    service = CoverageRetrievalService(global_file_uids=("file-002", "file-000", "file-002"))
    ctx = _context(db_session)
    ctx.retrieval_service = service

    result = build_tools(ctx)["query_kb"].invoke({
        "kb_uid": "kb-a",
        "query_text": "compare all files",
        "coverage": "per_file",
    })

    assert [call["file_uids"] for call in service.calls[1:]] == [
        ("file-001",),
        ("file-003",),
    ]
    assert [item["file_uid"] for item in result["data"]["evidence"]] == [
        "file-002", "file-000", "file-001", "file-003",
    ]


def test_query_kb_per_file_coverage_reports_unavailable_file_as_missing(db_session):
    from engine.app.agent.tools.knowledge_base import build_tools

    _seed_numbered_files(db_session, 3)
    service = CoverageRetrievalService(
        global_file_uids=("file-001", "file-002"),
        unavailable_file_uids=("file-000",),
    )
    ctx = _context(db_session)
    ctx.retrieval_service = service

    result = build_tools(ctx)["query_kb"].invoke({
        "kb_uid": "kb-a",
        "query_text": "cover every file",
        "coverage": "per_file",
    })

    assert result["status"] == "degraded"
    assert result["data"]["coverage"]["requested_file_uids"] == [
        "file-000", "file-001", "file-002",
    ]
    assert result["data"]["coverage"]["covered_file_uids"] == ["file-001", "file-002"]
    assert result["data"]["coverage"]["missing_file_uids"] == ["file-000"]
    assert result["data"]["coverage"]["complete"] is False
    assert result["data"]["retrieval_health"] == {
        "global": "ok", "file-000": "unavailable",
    }
    assert result["warnings"][0]["code"] == "FILE_UNAVAILABLE"


def test_query_kb_per_file_coverage_redacts_retrieval_exception_details(
    db_session, caplog
):
    from engine.app.agent.tools.knowledge_base import build_tools

    sensitive_parts = (
        "secret-token-123",
        "https://provider.invalid/query?token=secret-token-123",
        "C:\\private\\provider\\request.json",
    )

    class RaisingRetrievalService:
        def __init__(self):
            self.calls = []

        def query(self, **kwargs):
            self.calls.append(kwargs)
            raise RuntimeError(" | ".join(sensitive_parts))

    _seed_numbered_files(db_session, 2)
    service = RaisingRetrievalService()
    ctx = _context(db_session)
    ctx.retrieval_service = service

    with caplog.at_level("ERROR", logger="uvicorn.error"):
        result = build_tools(ctx)["query_kb"].invoke({
            "kb_uid": "kb-a",
            "query_text": "all files",
            "coverage": "per_file",
        })

    public_json = json.dumps(result)
    assert all(part not in public_json for part in sensitive_parts)
    assert result["warnings"] == [{
        "code": "RETRIEVAL_UNAVAILABLE",
        "message": "retrieval is unavailable",
    }]
    assert len(service.calls) == 3
    error_records = [
        record
        for record in caplog.records
        if "[knowledge.query_kb] retrieval failed" in record.getMessage()
    ]
    assert len(error_records) == 3
    assert all(record.exc_info is not None for record in error_records)


def test_query_kb_per_file_coverage_deduplicates_provider_warnings_stably(db_session):
    from engine.app.agent.tools.knowledge_base import build_tools

    first_warning = {"code": "DENSE_UNAVAILABLE", "message": "dense unavailable"}
    second_warning = {"code": "RERANK_UNAVAILABLE", "message": "rerank unavailable"}

    class RepeatingWarningService(CoverageRetrievalService):
        def query(self, **kwargs):
            response = super().query(**kwargs)
            response["status"] = "degraded"
            response["warnings"] = (
                [first_warning]
                if len(self.calls) == 1
                else [second_warning, first_warning]
            )
            return response

    _seed_numbered_files(db_session, 30)
    service = RepeatingWarningService(global_file_uids=())
    ctx = _context(db_session)
    ctx.retrieval_service = service

    result = build_tools(ctx)["query_kb"].invoke({
        "kb_uid": "kb-a",
        "query_text": "all files",
        "coverage": "per_file",
    })

    assert len(service.calls) == 31
    assert result["warnings"] == [first_warning, second_warning]


def test_query_kb_per_file_coverage_pages_thirty_files_by_file_uid_cursor(db_session):
    from engine.app.agent.tools.knowledge_base import build_tools

    _seed_numbered_files(db_session, 31)
    service = CoverageRetrievalService(
        global_file_uids=tuple(f"file-{index:03d}" for index in range(31))
    )
    ctx = _context(db_session)
    ctx.retrieval_service = service
    tool = build_tools(ctx)["query_kb"]

    first = tool.invoke({
        "kb_uid": "kb-a", "query_text": "all documents", "coverage": "per_file",
    })
    second = tool.invoke({
        "kb_uid": "kb-a",
        "query_text": "all documents",
        "coverage": "per_file",
        "coverage_cursor": first["data"]["coverage"]["next_cursor"],
    })

    first_coverage = first["data"]["coverage"]
    assert len(first_coverage["requested_file_uids"]) == 30
    assert first_coverage["requested_file_uids"][-1] == "file-029"
    assert first_coverage["next_cursor"]
    assert first_coverage["complete"] is False
    assert second["data"]["coverage"] == {
        "requested_file_uids": ["file-030"],
        "covered_file_uids": ["file-030"],
        "missing_file_uids": [],
        "complete": True,
        "next_cursor": None,
    }


def test_query_kb_per_file_coverage_respects_file_filter_and_rejects_invalid_cursor(db_session):
    from engine.app.agent.tools.knowledge_base import _encode_cursor, build_tools

    _seed_numbered_files(db_session, 4)
    service = CoverageRetrievalService(global_file_uids=("file-001", "file-003"))
    ctx = _context(db_session)
    ctx.retrieval_service = service
    tool = build_tools(ctx)["query_kb"]

    filtered = tool.invoke({
        "kb_uid": "kb-a",
        "query_text": "selected files",
        "coverage": "per_file",
        "file_filter": ["Paper 001", "file-003"],
    })
    raw_offset = tool.invoke({
        "kb_uid": "kb-a",
        "query_text": "selected files",
        "coverage": "per_file",
        "coverage_cursor": "30",
    })
    internal_db_id = tool.invoke({
        "kb_uid": "kb-a",
        "query_text": "selected files",
        "coverage": "per_file",
        "coverage_cursor": _encode_cursor("row-001"),
    })

    assert filtered["data"]["coverage"]["requested_file_uids"] == ["file-001", "file-003"]
    assert service.calls[0]["file_uids"] == ("file-001", "file-003")
    assert raw_offset["status"] == "error"
    assert raw_offset["error"]["code"] == "INVALID_REQUEST"
    assert internal_db_id["status"] == "error"
    assert internal_db_id["error"]["code"] == "INVALID_REQUEST"


def test_query_kb_per_file_coverage_rejects_non_object_cursor(db_session):
    from engine.app.agent.tools.knowledge_base import build_tools

    _seed_numbered_files(db_session, 2)

    result = build_tools(_context(db_session))["query_kb"].invoke({
        "kb_uid": "kb-a",
        "query_text": "all files",
        "coverage": "per_file",
        "coverage_cursor": "W10",
    })

    assert result["status"] == "error"
    assert result["error"]["code"] == "INVALID_REQUEST"


def test_query_kb_per_file_coverage_rejects_wrong_cursor_version(db_session):
    from engine.app.agent.tools.knowledge_base import build_tools

    _seed_numbered_files(db_session, 2)
    cursor = base64.urlsafe_b64encode(
        b'{"v":2,"after":"file-000"}'
    ).decode("ascii").rstrip("=")

    result = build_tools(_context(db_session))["query_kb"].invoke({
        "kb_uid": "kb-a",
        "query_text": "all files",
        "coverage": "per_file",
        "coverage_cursor": cursor,
    })

    assert result["status"] == "error"
    assert result["error"]["code"] == "INVALID_REQUEST"


def test_query_kb_per_file_coverage_rejects_non_integer_cursor_version(db_session):
    from engine.app.agent.tools.knowledge_base import build_tools

    _seed_numbered_files(db_session, 2)
    cursor = base64.urlsafe_b64encode(
        b'{"v":true,"after":"file-000"}'
    ).decode("ascii").rstrip("=")

    result = build_tools(_context(db_session))["query_kb"].invoke({
        "kb_uid": "kb-a",
        "query_text": "all files",
        "coverage": "per_file",
        "coverage_cursor": cursor,
    })

    assert result["status"] == "error"
    assert result["error"]["code"] == "INVALID_REQUEST"


def test_query_kb_per_file_coverage_preserves_conflicting_retrieval_health(db_session):
    from engine.app.agent.tools.knowledge_base import build_tools

    class CollidingHealthService(CoverageRetrievalService):
        def query(self, **kwargs):
            response = super().query(**kwargs)
            response["retrieval_health"] = {
                "dense": "unavailable" if len(kwargs["file_uids"]) > 1 else "ok"
            }
            return response

    _seed_numbered_files(db_session, 2)
    service = CollidingHealthService(global_file_uids=("file-000",))
    ctx = _context(db_session)
    ctx.retrieval_service = service

    result = build_tools(ctx)["query_kb"].invoke({
        "kb_uid": "kb-a",
        "query_text": "all files",
        "coverage": "per_file",
    })

    assert result["data"]["retrieval_health"]["dense"] == ["unavailable", "ok"]


def test_query_kb_rejects_coverage_cursor_in_relevance_mode(db_session):
    from engine.app.agent.tools.knowledge_base import _encode_cursor, build_tools

    _seed_numbered_files(db_session, 2)
    result = build_tools(_context(db_session))["query_kb"].invoke({
        "kb_uid": "kb-a",
        "query_text": "all files",
        "coverage_cursor": _encode_cursor("file-000"),
    })

    assert result["status"] == "error"
    assert result["error"]["code"] == "INVALID_REQUEST"


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


def test_find_document_resolves_original_filename_to_file_uid(db_session):
    from engine.app.agent.tools.knowledge_base import build_tools

    _seed(db_session)
    result = build_tools(_context(db_session))["find_kb_document"].invoke({
        "kb_uid": "kb-a",
        "file_uid": "architecture.md",
        "patterns": ["needle"],
    })

    assert result["status"] == "ok"
    assert result["data"]["file_uid"] == "file-a"
    assert result["data"]["matches"]


def test_open_document_resolves_title_to_file_uid(db_session):
    from engine.app.agent.tools.knowledge_base import build_tools

    _seed(db_session)
    result = build_tools(_context(db_session))["open_kb_document"].invoke({
        "kb_uid": "kb-a",
        "file_uid": "Architecture Guide",
        "offset": 0,
        "window_size": 5,
    })

    assert result["status"] == "ok"
    assert result["data"]["file_uid"] == "file-a"
    assert result["data"]["content"] == "alpha"


def test_open_document_returns_next_offset_for_initial_window(db_session):
    from engine.app.agent.tools.knowledge_base import build_tools

    _seed(db_session)
    result = build_tools(_context(db_session))["open_kb_document"].invoke({
        "kb_uid": "kb-a",
        "file_uid": "file-a",
        "offset": 0,
        "window_size": 12,
    })

    assert result["data"]["next_offset"] == 12


def test_open_document_returns_document_end_for_tail_request(db_session):
    from engine.app.agent.tools.knowledge_base import build_tools

    _seed(db_session)
    result = build_tools(_context(db_session))["open_kb_document"].invoke({
        "kb_uid": "kb-a",
        "file_uid": "file-a",
        "offset": 35,
        "window_size": 100,
    })

    assert result["data"]["next_offset"] == len("alpha line\nneedle appears here\nomega line")
    assert result["data"]["has_more_after"] is False


def test_open_document_clamps_beyond_end_offset_for_nonempty_content(db_session):
    from engine.app.agent.tools.knowledge_base import build_tools

    _seed(db_session)
    content = "alpha line\nneedle appears here\nomega line"
    result = build_tools(_context(db_session))["open_kb_document"].invoke({
        "kb_uid": "kb-a",
        "file_uid": "file-a",
        "offset": 1000,
        "window_size": 12,
    })

    assert result["data"]["offset"] == len(content)
    assert result["data"]["next_offset"] == len(content)
    assert result["data"]["content"] == ""
    assert result["data"]["has_more_after"] is False
    assert result["data"]["has_more_before"] is True


def test_open_document_returns_next_offset_for_line_window(db_session):
    from engine.app.agent.tools.knowledge_base import build_tools

    _seed(db_session)
    result = build_tools(_context(db_session))["open_kb_document"].invoke({
        "kb_uid": "kb-a",
        "file_uid": "file-a",
        "line": 2,
        "window_size": 7,
    })

    line_start = len("alpha line\n")
    assert result["data"]["next_offset"] == line_start + len(result["data"]["content"])


def test_open_document_returns_document_end_for_empty_content(db_session):
    from engine.app.agent.tools.knowledge_base import build_tools

    _seed(db_session)
    file_row = db_session.query(KnowledgeFile).filter_by(file_uid="file-a").one()
    file_row.content_text = ""
    db_session.commit()

    result = build_tools(_context(db_session))["open_kb_document"].invoke({
        "kb_uid": "kb-a",
        "file_uid": "file-a",
        "offset": 0,
        "window_size": 12,
    })

    assert result["data"]["next_offset"] == 0
    assert result["data"]["has_more_after"] is False


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
