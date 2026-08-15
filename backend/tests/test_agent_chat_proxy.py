"""Task 6: Backend-authorized streaming chat proxy.

The browser must never own private Engine authorization. The Backend resolves
requested/default KBs with KnowledgeAccessPolicy, signs an
AuthorizedKnowledgeScope, and only then forwards to Engine. A forbidden KB is
rejected with 403 before Engine is contacted.
"""

import base64
import json

import backend.app.api.agent_chat_proxy as proxy_module
from backend.app.api.agent_chat_proxy import ChatAnswerRequest
from backend.app.models import ChatMessage, ChatSession, KnowledgeTopic


def _seed_owned_kb(db, kb_uid, owner="default-user", tenant="default-user"):
    from backend.app.models import KnowledgeTopic

    db.add(
        KnowledgeTopic(
            kb_uid=kb_uid,
            tenant_id=tenant,
            owner_user_id=owner,
            name=kb_uid,
            status="active",
        )
    )
    db.commit()


def _seed_chat_turn(db, session_id="session-a", user_message_id="message-a", user_id="default-user"):
    db.add(ChatSession(id=session_id, user_id=user_id, title="Resume session"))
    db.add(
        ChatMessage(
            id=user_message_id,
            session_id=session_id,
            role="user",
            content="continue",
        )
    )
    db.commit()


def _enable_scope_secret(monkeypatch):
    monkeypatch.setattr(proxy_module.settings, "KNOWLEDGE_SCOPE_SECRET", "test-secret")


def _decoded_scope_payload(signed_token):
    payload, _signature = signed_token.split(".", 1)
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def test_chat_answer_request_schema_has_no_secrets():
    fields = set(ChatAnswerRequest.model_fields)
    assert "query" in fields
    assert "kb_uids" in fields
    # The browser must not pass tenant/actor/scope/secrets.
    assert "tenant_id" not in fields
    assert "actor_id" not in fields
    assert "storage_uri" not in fields
    assert "secret" not in fields


def test_chat_answer_request_defaults_exclude_personal_inbox():
    req = ChatAnswerRequest(query="summarize", kb_uids=["kb-a"])

    assert req.include_personal_inbox is False


def test_chat_answer_request_defaults_allow_multi_step_knowledge_synthesis():
    req = ChatAnswerRequest(query="summarize", kb_uids=["kb-a"])

    assert req.rag_max_iterations == 10
    assert req.deep_search_enabled is False
    assert req.deep_search_depth == "standard"


def test_backend_proxy_forwards_deep_search_depth_controls(client, db_session, monkeypatch):
    _enable_scope_secret(monkeypatch)
    _seed_owned_kb(db_session, "kb-a")
    captured = {}

    async def fake_stream(signed_token, payload):
        captured["payload"] = payload
        yield b'{"type":"done"}\n'

    monkeypatch.setattr(proxy_module, "stream_engine_answer", fake_stream)

    response = client.post(
        "/api/v1/chat/answer",
        json={
            "query": "hi",
            "kb_uids": ["kb-a"],
            "mode": "deep",
            "deep_search_enabled": True,
            "deep_search_depth": "deep",
        },
    )

    assert response.status_code == 200
    assert captured["payload"]["deep_search_enabled"] is True
    assert captured["payload"]["deep_search_depth"] == "deep"


def test_chat_proxy_forwards_resume_trace_id_with_owner_ids(client, db_session, monkeypatch):
    _seed_chat_turn(db_session)
    captured = {}

    async def fake_stream(signed_token, payload):
        captured["token"] = signed_token
        captured["payload"] = payload
        yield b'{"type":"done","data":{}}\n'

    monkeypatch.setattr(proxy_module, "stream_engine_answer", fake_stream)

    response = client.post(
        "/api/v1/chat/answer",
        json={
            "query": "continue",
            "history": [],
            "resume_trace_id": "trace-resume",
            "session_id": "session-a",
            "user_message_id": "message-a",
            "kb_uids": [],
        },
    )

    assert response.status_code == 200
    assert captured["token"] == ""
    assert captured["payload"]["resume_trace_id"] == "trace-resume"
    assert captured["payload"]["session_id"] == "session-a"
    assert captured["payload"]["user_message_id"] == "message-a"


def test_chat_proxy_rejects_resume_for_other_users_session(client, db_session, monkeypatch):
    _seed_chat_turn(db_session, user_id="alice")
    captured = {}

    async def fake_stream(signed_token, payload):
        captured["payload"] = payload
        yield b'{"type":"done","data":{}}\n'

    monkeypatch.setattr(proxy_module, "stream_engine_answer", fake_stream)

    response = client.post(
        "/api/v1/chat/answer",
        headers={"X-Prism-Actor": "bob", "X-Prism-Tenant": "bob"},
        json={
            "query": "continue",
            "resume_trace_id": "trace-resume",
            "session_id": "session-a",
            "user_message_id": "message-a",
            "kb_uids": [],
        },
    )

    assert response.status_code == 403
    assert captured == {}


def test_chat_proxy_rejects_resume_with_wrong_user_message(client, db_session, monkeypatch):
    _seed_chat_turn(db_session)
    db_session.add(
        ChatMessage(
            id="assistant-a",
            session_id="session-a",
            role="assistant",
            content="partial",
        )
    )
    db_session.commit()
    captured = {}

    async def fake_stream(signed_token, payload):
        captured["payload"] = payload
        yield b'{"type":"done","data":{}}\n'

    monkeypatch.setattr(proxy_module, "stream_engine_answer", fake_stream)

    response = client.post(
        "/api/v1/chat/answer",
        json={
            "query": "continue",
            "resume_trace_id": "trace-resume",
            "session_id": "session-a",
            "user_message_id": "assistant-a",
            "kb_uids": [],
        },
    )

    assert response.status_code == 403
    assert captured == {}


def test_backend_proxy_signs_only_authorized_kbs(client, db_session, monkeypatch):
    _enable_scope_secret(monkeypatch)
    _seed_owned_kb(db_session, "kb-a")
    _seed_owned_kb(db_session, "kb-forbidden", owner="someone-else")

    calls = []

    async def fake_stream(signed_token, payload):
        calls.append({"token": signed_token, "payload": payload})
        yield b'{"type":"done"}\n'

    monkeypatch.setattr(proxy_module, "stream_engine_answer", fake_stream)

    response = client.post(
        "/api/v1/chat/answer",
        json={"query": "x", "kb_uids": ["kb-a", "kb-forbidden"]},
    )

    assert response.status_code == 403
    assert calls == []


def test_backend_proxy_forwards_authorized_kbs_with_signed_scope(client, db_session, monkeypatch):
    _enable_scope_secret(monkeypatch)
    _seed_owned_kb(db_session, "kb-a")

    captured = {}

    async def fake_stream(signed_token, payload):
        captured["token"] = signed_token
        captured["payload"] = payload
        yield b'{"type":"done"}\n'

    monkeypatch.setattr(proxy_module, "stream_engine_answer", fake_stream)

    response = client.post("/api/v1/chat/answer", json={"query": "hi", "kb_uids": ["kb-a"]})

    assert response.status_code == 200
    assert captured["token"], "scope must be signed before forwarding"
    # Payload forwarded to Engine must not carry tenant/actor or the secret token.
    forwarded = str(captured["payload"]).lower()
    assert "tenant_id" not in forwarded
    assert "actor_id" not in forwarded


def test_backend_proxy_forwards_public_continuation_history_without_scope_leaks(
    client, db_session, monkeypatch
):
    _enable_scope_secret(monkeypatch)
    _seed_owned_kb(db_session, "kb-a")
    captured = {}
    history = [
        {"role": "user", "content": "continue"},
        {
            "role": "assistant",
            "content": "partial answer",
            "continuation": {
                "version": 1,
                "objective": "finish the synthesis",
                "kb_uid": "kb-a",
                "file_uid": "file-a",
                "next_offset": 24,
                "has_more_after": True,
            },
        },
    ]

    async def fake_stream(signed_token, payload):
        captured["token"] = signed_token
        captured["payload"] = payload
        yield b'{"type":"done"}\n'

    monkeypatch.setattr(proxy_module, "stream_engine_answer", fake_stream)

    response = client.post(
        "/api/v1/chat/answer",
        json={"query": "next", "kb_uids": ["kb-a"], "history": history},
    )

    assert response.status_code == 200
    assert captured["payload"]["history"] == history
    forwarded = str(captured["payload"]).lower()
    assert "tenant_id" not in forwarded
    assert "actor_id" not in forwarded
    assert "scope" not in forwarded
    assert captured["token"]


def test_chat_proxy_appends_personal_inbox_scope_when_requested(client, db_session, monkeypatch):
    _enable_scope_secret(monkeypatch)
    _seed_owned_kb(db_session, "kb-a")
    captured = {}

    async def fake_stream(signed_token, payload):
        captured["token"] = signed_token
        captured["payload"] = payload
        yield b'{"type":"done"}\n'

    monkeypatch.setattr(proxy_module, "stream_engine_answer", fake_stream)

    response = client.post(
        "/api/v1/chat/answer",
        json={"query": "hi", "kb_uids": ["kb-a"], "include_personal_inbox": True},
    )

    assert response.status_code == 200
    scope = _decoded_scope_payload(captured["token"])
    assert "kb-a" in scope["allowed_kb_uids"]
    assert len(scope["allowed_kb_uids"]) == 2
    inbox_kb_uid = next(kb_uid for kb_uid in scope["allowed_kb_uids"] if kb_uid != "kb-a")
    assert db_session.query(KnowledgeTopic).filter_by(
        kb_uid=inbox_kb_uid,
        tenant_id="default-user",
        owner_user_id="default-user",
        system_type="personal_inbox",
    ).one()
    assert captured["payload"]["include_personal_inbox"] is True


def test_chat_proxy_does_not_append_personal_inbox_scope_by_default(
    client, db_session, monkeypatch
):
    _enable_scope_secret(monkeypatch)
    _seed_owned_kb(db_session, "kb-a")
    captured = {}

    async def fake_stream(signed_token, payload):
        captured["token"] = signed_token
        captured["payload"] = payload
        yield b'{"type":"done"}\n'

    monkeypatch.setattr(proxy_module, "stream_engine_answer", fake_stream)

    response = client.post("/api/v1/chat/answer", json={"query": "hi", "kb_uids": ["kb-a"]})

    assert response.status_code == 200
    scope = _decoded_scope_payload(captured["token"])
    assert scope["allowed_kb_uids"] == ["kb-a"]
    assert captured["payload"]["include_personal_inbox"] is False


def test_chat_proxy_ignores_frontend_supplied_personal_inbox_when_switch_is_false(
    client, db_session, monkeypatch
):
    from backend.app.services.personal_inbox import ensure_personal_inbox_kb

    _enable_scope_secret(monkeypatch)
    _seed_owned_kb(db_session, "kb-a")
    personal_inbox = ensure_personal_inbox_kb(
        db_session,
        tenant_id="default-user",
        owner_user_id="default-user",
    )
    db_session.commit()
    captured = {}

    async def fake_stream(signed_token, payload):
        captured["token"] = signed_token
        captured["payload"] = payload
        yield b'{"type":"done"}\n'

    monkeypatch.setattr(proxy_module, "stream_engine_answer", fake_stream)

    response = client.post(
        "/api/v1/chat/answer",
        json={"query": "hi", "kb_uids": ["kb-a", personal_inbox.kb_uid]},
    )

    assert response.status_code == 200
    scope = _decoded_scope_payload(captured["token"])
    assert scope["allowed_kb_uids"] == ["kb-a"]
