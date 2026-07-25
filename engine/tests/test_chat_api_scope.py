from fastapi.testclient import TestClient


def test_chat_answer_verifies_backend_scope_header(monkeypatch):
    from backend.app.security.knowledge_scope import AuthorizedKnowledgeScope, sign_scope
    import engine.app.api.chat as chat_api
    from engine.app.config import settings
    from engine.run import create_app

    monkeypatch.setattr(settings, "KNOWLEDGE_SCOPE_SECRET", "scope-secret")
    captured = {}

    def fake_answer_stream(query, history=None, **kwargs):
        captured["knowledge_scope"] = kwargs.get("knowledge_scope")
        yield '{"type":"done"}\n'

    monkeypatch.setattr(chat_api, "answer_stream", fake_answer_stream)
    token = sign_scope(
        AuthorizedKnowledgeScope(
            actor_id="alice",
            tenant_id="tenant-a",
            allowed_kb_uids=("kb-a",),
            run_id="run-1",
            expires_at=4102444800,
        ),
        secret="scope-secret",
    )

    response = TestClient(create_app()).post(
        "/api/v1/chat/answer",
        json={"query": "hello"},
        headers={"X-Prism-Knowledge-Scope": token},
    )

    assert response.status_code == 200
    assert captured["knowledge_scope"].allowed_kb_uids == ("kb-a",)
