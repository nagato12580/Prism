from backend.app.models import (
    MemoryDraft,
    MemorySource,
    MemoryStatement,
)


def test_memory_source_preserves_chat_traceability(db_session):
    source = MemorySource(
        user_id="default-user",
        source_type="chat_message",
        source_id="msg-1",
        session_id="session-1",
        message_id="msg-1",
        span_text="We decided to build Memory Inbox first.",
        source_metadata={"prompt_version": "manual"},
    )
    db_session.add(source)
    db_session.commit()

    saved = db_session.query(MemorySource).one()

    assert saved.source_type == "chat_message"
    assert saved.session_id == "session-1"
    assert saved.message_id == "msg-1"
    assert saved.span_text == "We decided to build Memory Inbox first."
    assert saved.source_metadata == {"prompt_version": "manual"}


def test_memory_statement_defaults_exclude_unconfirmed_memory(db_session):
    source = MemorySource(
        user_id="default-user",
        source_type="chat_message",
        source_id="msg-1",
        span_text="The user chose hybrid memory writes.",
    )
    statement = MemoryStatement(
        user_id="default-user",
        content="The user chose hybrid memory writes.",
        statement_type="decision",
        temporal_type="stable",
        source=source,
    )
    db_session.add(statement)
    db_session.commit()

    saved = db_session.query(MemoryStatement).one()

    assert saved.status == "draft"
    assert saved.confidence == 0.7
    assert saved.importance == 0.6
    assert saved.source.span_text == "The user chose hybrid memory writes."


def test_memory_draft_defaults_to_pending_review(db_session):
    draft = MemoryDraft(
        user_id="default-user",
        draft_type="statement",
        payload={"content": "The user wants Memory Inbox first."},
        decision_hint="review",
        risk_level="medium",
        confidence=0.65,
    )
    db_session.add(draft)
    db_session.commit()

    saved = db_session.query(MemoryDraft).one()

    assert saved.status == "draft"
    assert saved.conflict_ids == []
    assert saved.payload["content"] == "The user wants Memory Inbox first."
