"""Engine regression tests for the AuthorizedKnowledgeScope boundary (Task 6).

The Engine must never judge team roles itself. It consumes a Backend-signed
:class:`AuthorizedKnowledgeScope` and must enforce exactly three properties:

1. A ``kb_uid`` outside ``allowed_kb_uids`` is rejected before any DB retrieval
   or retrieval-service call.
2. A missing knowledge scope is treated as an authorization failure.
3. The multi-KB default target list is exactly ``allowed_kb_uids``.

These tests exercise the public ``build_tools`` surface (the same entrypoint
the existing ``test_knowledge_base_tools.py`` uses) so they stay coupled to the
real tool behavior rather than private internals.
"""

from backend.app.models import KnowledgeTopic


class _SpyRetrieval:
    """Records every retrieval call; fails loudly if any query would have leaked."""

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

    service = _SpyRetrieval()
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
    db_session.add_all([
        KnowledgeTopic(
            id="topic-a",
            kb_uid="kb-a",
            tenant_id="tenant-a",
            owner_user_id="alice",
            name="Safe KB",
            status="active",
        ),
        KnowledgeTopic(
            id="topic-b",
            kb_uid="kb-b",
            tenant_id="tenant-a",
            owner_user_id="alice",
            name="Forbidden KB",
            status="active",
        ),
    ])
    db_session.commit()


def test_query_kb_rejects_out_of_scope_kb_before_any_retrieval(db_session):
    from engine.app.agent.tools.knowledge_base import build_tools

    _seed(db_session)
    ctx = _context(db_session, allowed=("kb-a",))

    result = build_tools(ctx)["query_kb"].invoke({
        "kb_uid": "kb-b",
        "query_text": "secret",
    })

    assert result["status"] == "error"
    assert result["error"]["code"] == "KB_NOT_ALLOWED"
    assert ctx.retrieval_service.calls == []


def test_missing_scope_is_an_authorization_failure(db_session):
    from engine.app.agent.tools.base import ToolContext
    from engine.app.agent.tools.knowledge_base import build_tools

    ctx = ToolContext(
        db=db_session,
        trace_id="trace-1",
        run_id="run-1",
        knowledge_scope=None,
        retrieval_service=_SpyRetrieval(),
    )

    result = build_tools(ctx)["query_kb"].invoke({
        "kb_uid": "kb-a",
        "query_text": "secret",
    })

    assert result["status"] == "error"
    assert result["error"]["code"] == "KNOWLEDGE_TOOL_ERROR"
    assert ctx.retrieval_service.calls == []


def test_multi_kb_default_targets_exactly_allowed_kb_uids(db_session):
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
