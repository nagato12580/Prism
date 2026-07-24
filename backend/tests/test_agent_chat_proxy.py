"""Task 6: Backend-authorized streaming chat proxy.

The browser must never own private Engine authorization. The Backend resolves
requested/default KBs with KnowledgeAccessPolicy, signs an
AuthorizedKnowledgeScope, and only then forwards to Engine. A forbidden KB is
rejected with 403 before Engine is contacted.
"""

import backend.app.api.agent_chat_proxy as proxy_module
from backend.app.api.agent_chat_proxy import ChatAnswerRequest


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


def _enable_scope_secret(monkeypatch):
    monkeypatch.setattr(proxy_module.settings, "KNOWLEDGE_SCOPE_SECRET", "test-secret")


def test_chat_answer_request_schema_has_no_secrets():
    fields = set(ChatAnswerRequest.model_fields)
    assert "query" in fields
    assert "kb_uids" in fields
    # The browser must not pass tenant/actor/scope/secrets.
    assert "tenant_id" not in fields
    assert "actor_id" not in fields
    assert "storage_uri" not in fields
    assert "secret" not in fields


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
