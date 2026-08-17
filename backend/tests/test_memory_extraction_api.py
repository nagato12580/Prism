import json

from backend.app.models import ChatMessage, ChatSession, MemoryDraft, MemoryStatement
from backend.app.security.actor import ActorContext
from backend.app.services import memory_extraction as svc


def test_extract_session_endpoint_creates_memory_drafts(client, db_session, monkeypatch):
    session = ChatSession(user_id="default-user", title="Memory extraction")
    db_session.add(session)
    db_session.flush()
    message = ChatMessage(
        session_id=session.id,
        role="user",
        content="我希望 Prism 记住我关注长期记忆系统设计。",
    )
    db_session.add(message)
    db_session.commit()

    def fake_llm(prompt_messages):
        return json.dumps(
            {
                "candidates": [
                    {
                        "content": "用户关注长期记忆系统设计。",
                        "statement_type": "current_focus",
                        "temporal_type": "current",
                        "confidence": 0.9,
                        "importance": 0.8,
                        "risk_level": "medium",
                        "decision_hint": "review",
                        "evidence_message_id": message.id,
                    }
                ]
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(svc, "_call_memory_extraction_llm", fake_llm)

    response = client.post(f"/api/v1/memories/extract/session/{session.id}", json={"limit": 10})

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == session.id
    assert payload["messages_scanned"] == 1
    assert payload["candidates_found"] == 1
    assert payload["drafts_created"] == 1
    assert payload["candidates_skipped"] == 0
    assert payload["drafts"][0]["payload"]["content"] == "用户关注长期记忆系统设计。"
    assert db_session.query(MemoryDraft).count() == 1


def test_extract_session_endpoint_returns_404_for_missing_session(client):
    response = client.post("/api/v1/memories/extract/session/missing-session", json={"limit": 10})

    assert response.status_code == 404


class ImmediateThread:
    def __init__(self, target, args=(), daemon=None):
        self.target = target
        self.args = args

    def start(self):
        self.target(*self.args)


class FakeBackgroundSession:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_add_assistant_message_triggers_auto_memory_extraction_when_enabled(
    client,
    db_session,
    monkeypatch,
):
    from backend.app.api import chat as chat_api
    from backend.app.config import settings

    session = ChatSession(user_id="default-user", title="Auto memory")
    db_session.add(session)
    db_session.commit()
    session_id = session.id
    calls = []
    background_session = FakeBackgroundSession()

    monkeypatch.setattr(settings, "MEMORY_EXTRACTION_AUTO_ENABLED", True, raising=False)
    monkeypatch.setattr(chat_api, "SessionLocal", lambda: background_session)
    monkeypatch.setattr(chat_api.threading, "Thread", ImmediateThread)

    def fake_extract(db, session_id, limit=20):
        calls.append((db, session_id, limit))

    monkeypatch.setattr(chat_api, "extract_session_memories", fake_extract)

    response = client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"role": "assistant", "content": "Remember this durable preference."},
    )

    assert response.status_code == 200
    assert calls == [(background_session, session_id, 20)]
    assert background_session.closed is True


def test_add_assistant_message_ignores_auto_memory_extraction_failures(
    client,
    db_session,
    monkeypatch,
):
    from backend.app.api import chat as chat_api
    from backend.app.config import settings

    session = ChatSession(user_id="default-user", title="Auto memory")
    db_session.add(session)
    db_session.commit()
    session_id = session.id

    monkeypatch.setattr(settings, "MEMORY_EXTRACTION_AUTO_ENABLED", True, raising=False)
    monkeypatch.setattr(chat_api, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(chat_api.threading, "Thread", ImmediateThread)

    def fake_extract(db, session_id, limit=20):
        raise RuntimeError("LLM unavailable")

    monkeypatch.setattr(chat_api, "extract_session_memories", fake_extract)

    response = client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"role": "assistant", "content": "This message should still be saved."},
    )

    assert response.status_code == 200
    assert response.json()["content"] == "This message should still be saved."


def test_add_assistant_message_ignores_auto_memory_thread_start_failures(
    client,
    db_session,
    monkeypatch,
):
    from backend.app.api import chat as chat_api
    from backend.app.config import settings

    class FailingThread:
        def __init__(self, target, args=(), daemon=None):
            pass

        def start(self):
            raise RuntimeError("thread unavailable")

    session = ChatSession(user_id="default-user", title="Auto memory")
    db_session.add(session)
    db_session.commit()
    session_id = session.id

    monkeypatch.setattr(settings, "MEMORY_EXTRACTION_AUTO_ENABLED", True, raising=False)
    monkeypatch.setattr(chat_api.threading, "Thread", FailingThread)

    response = client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"role": "assistant", "content": "Thread failure should not fail chat."},
    )

    assert response.status_code == 200
    assert response.json()["content"] == "Thread failure should not fail chat."


def test_add_message_does_not_trigger_auto_memory_extraction_when_disabled(
    client,
    db_session,
    monkeypatch,
):
    from backend.app.api import chat as chat_api
    from backend.app.config import settings

    session = ChatSession(user_id="default-user", title="Auto memory")
    db_session.add(session)
    db_session.commit()
    session_id = session.id
    calls = []

    monkeypatch.setattr(settings, "MEMORY_EXTRACTION_AUTO_ENABLED", False, raising=False)
    monkeypatch.setattr(chat_api.threading, "Thread", ImmediateThread)

    def fake_extract(db, session_id, limit=20):
        calls.append((session_id, limit))

    monkeypatch.setattr(chat_api, "extract_session_memories", fake_extract)

    response = client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"role": "assistant", "content": "Do not extract while disabled."},
    )

    assert response.status_code == 200
    assert calls == []


def test_add_user_message_does_not_trigger_auto_memory_extraction(
    client,
    db_session,
    monkeypatch,
):
    from backend.app.api import chat as chat_api
    from backend.app.config import settings

    session = ChatSession(user_id="default-user", title="Auto memory")
    db_session.add(session)
    db_session.commit()
    session_id = session.id
    calls = []

    monkeypatch.setattr(settings, "MEMORY_EXTRACTION_AUTO_ENABLED", True, raising=False)
    monkeypatch.setattr(chat_api.threading, "Thread", ImmediateThread)

    def fake_extract(db, session_id, limit=20):
        calls.append((session_id, limit))

    monkeypatch.setattr(chat_api, "extract_session_memories", fake_extract)

    response = client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"role": "user", "content": "This is not an assistant reply."},
    )

    assert response.status_code == 200
    assert calls == []


def test_auto_memory_extraction_ignores_session_open_failures(monkeypatch):
    from backend.app.api import chat as chat_api

    def fail_session_open():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(chat_api, "SessionLocal", fail_session_open)

    chat_api._run_memory_extraction_best_effort("session-id")


def test_count_drafts_returns_count(client):
    """GET /memories/drafts/count returns draft count and by_risk breakdown."""
    # Create a draft manually via the create endpoint
    payload = {
        "draft_type": "statement",
        "payload": {"content": "test count draft", "statement_type": "fact"},
        "decision_hint": "review",
        "risk_level": "medium",
        "confidence": 0.7,
    }
    client.post("/api/v1/memories/drafts", json=payload)

    resp = client.get("/api/v1/memories/drafts/count?status=draft")
    assert resp.status_code == 200
    data = resp.json()
    assert "count" in data
    assert data["count"] >= 1
    assert "by_risk" in data


def test_confirm_draft_is_idempotent_after_success(db_session):
    from backend.app.api.memories import confirm_memory_draft

    content = "用户的论文是《Hierarchical Anchoring for Geometry-Semantics Collaborative Multi-View Clustering》。"
    draft = MemoryDraft(
        user_id="default-user",
        draft_type="statement",
        payload={
            "content": content,
            "statement_type": "fact",
            "temporal_type": "stable",
            "importance": 0.9,
        },
        decision_hint="review",
        risk_level="medium",
        confidence=0.9,
    )
    db_session.add(draft)
    db_session.commit()
    actor = ActorContext(actor_id="default-user", tenant_id="default-user")

    first = confirm_memory_draft(draft.id, db_session, actor)
    second = confirm_memory_draft(draft.id, db_session, actor)

    assert second.statement.id == first.statement.id
    statements = db_session.query(MemoryStatement).filter(MemoryStatement.content == content).all()
    assert len(statements) == 1


def test_trigger_scheduled_extraction_returns_stats(client):
    """POST /memories/extract/scheduled triggers a round and returns stats."""
    resp = client.post("/api/v1/memories/extract/scheduled")
    assert resp.status_code == 200
    data = resp.json()
    assert "sessions_scanned" in data
    assert "sessions_extracted" in data
    assert "auto_confirmed" in data
    assert "inbox_created" in data
    assert "errors" in data
