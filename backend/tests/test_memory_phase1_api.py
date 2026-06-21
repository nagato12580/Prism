from backend.app.models import MemoryDraft, MemorySource, MemoryStatement


def test_create_and_list_memory_drafts(client):
    response = client.post(
        "/api/v1/memories/drafts",
        json={
            "draft_type": "statement",
            "payload": {
                "content": "The user chose a phased hybrid memory design.",
                "statement_type": "decision",
                "temporal_type": "stable",
            },
            "decision_hint": "auto_confirm",
            "risk_level": "low",
            "confidence": 0.88,
            "source": {
                "source_type": "chat_message",
                "source_id": "msg-1",
                "session_id": "session-1",
                "message_id": "msg-1",
                "span_text": "We choose phased hybrid.",
                "metadata": {"prompt_version": "manual"},
            },
        },
    )

    assert response.status_code == 200
    created = response.json()
    assert created["draft_type"] == "statement"
    assert created["status"] == "draft"
    assert created["source"]["span_text"] == "We choose phased hybrid."
    assert created["source"]["metadata"] == {"prompt_version": "manual"}

    listed = client.get("/api/v1/memories/drafts").json()

    assert [item["id"] for item in listed] == [created["id"]]


def test_confirm_statement_draft_creates_confirmed_statement(client, db_session):
    source = MemorySource(
        user_id="default-user",
        source_type="chat_message",
        source_id="msg-1",
        span_text="The user wants Memory Inbox first.",
    )
    draft = MemoryDraft(
        user_id="default-user",
        draft_type="statement",
        payload={
            "content": "The user wants Memory Inbox first.",
            "statement_type": "preference",
            "temporal_type": "current",
            "importance": 0.8,
        },
        confidence=0.9,
        risk_level="low",
        source=source,
    )
    db_session.add(draft)
    db_session.commit()

    response = client.post(f"/api/v1/memories/drafts/{draft.id}/confirm")

    assert response.status_code == 200
    payload = response.json()
    assert payload["draft"]["status"] == "confirmed"
    assert payload["statement"]["content"] == "The user wants Memory Inbox first."
    assert payload["statement"]["status"] == "confirmed"

    statements = client.get("/api/v1/memories/statements").json()
    assert [item["content"] for item in statements] == ["The user wants Memory Inbox first."]


def test_reject_draft_marks_it_rejected(client, db_session):
    draft = MemoryDraft(
        user_id="default-user",
        draft_type="statement",
        payload={"content": "Uncertain memory"},
    )
    db_session.add(draft)
    db_session.commit()

    response = client.post(f"/api/v1/memories/drafts/{draft.id}/reject")

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"


def test_supersede_draft_confirms_new_statement_and_supersedes_old(client, db_session):
    source = MemorySource(
        user_id="default-user",
        source_type="chat_message",
        source_id="msg-1",
        span_text="The user now prefers review-first memory.",
    )
    old = MemoryStatement(
        user_id="default-user",
        content="The user prefers automatic memory writes.",
        statement_type="preference",
        temporal_type="current",
        status="confirmed",
    )
    draft = MemoryDraft(
        user_id="default-user",
        draft_type="statement",
        payload={
            "content": "The user prefers review-first memory.",
            "statement_type": "preference",
            "temporal_type": "current",
        },
        conflict_ids=[],
        source=source,
    )
    db_session.add_all([old, draft])
    db_session.commit()

    response = client.post(
        f"/api/v1/memories/drafts/{draft.id}/supersede",
        json={"superseded_statement_id": old.id},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["statement"]["status"] == "confirmed"

    db_session.refresh(old)
    assert old.status == "superseded"
    assert old.superseded_by_id == payload["statement"]["id"]

    statements = client.get("/api/v1/memories/statements").json()
    assert [item["content"] for item in statements] == ["The user prefers review-first memory."]


def test_confirm_rejects_non_string_statement_content(client, db_session):
    draft = MemoryDraft(
        user_id="default-user",
        draft_type="statement",
        payload={"content": 123},
    )
    db_session.add(draft)
    db_session.commit()

    response = client.post(f"/api/v1/memories/drafts/{draft.id}/confirm")

    assert response.status_code == 400
    assert "non-empty string" in response.json()["detail"]
    assert db_session.query(MemoryStatement).count() == 0


def test_supersede_requires_confirmed_existing_statement(client, db_session):
    old = MemoryStatement(
        user_id="default-user",
        content="Draft statement should not be superseded.",
        statement_type="preference",
        temporal_type="current",
        status="draft",
    )
    draft = MemoryDraft(
        user_id="default-user",
        draft_type="statement",
        payload={
            "content": "The user prefers review-first memory.",
            "statement_type": "preference",
            "temporal_type": "current",
        },
    )
    db_session.add_all([old, draft])
    db_session.commit()

    response = client.post(
        f"/api/v1/memories/drafts/{draft.id}/supersede",
        json={"superseded_statement_id": old.id},
    )

    assert response.status_code == 400
    assert "confirmed" in response.json()["detail"]
    db_session.refresh(old)
    assert old.status == "draft"
