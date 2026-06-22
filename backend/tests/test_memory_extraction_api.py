import json

from backend.app.models import ChatMessage, ChatSession, MemoryDraft
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
