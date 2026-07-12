import json

from backend.app.models import ChatMessage, ChatSession, MemoryDraft, MemorySource, MemoryStatement
from backend.app.services import memory_extraction as svc


def test_build_memory_extraction_messages_include_recent_chat_context(db_session):
    session = ChatSession(user_id="default-user", title="Memory design")
    db_session.add(session)
    db_session.flush()
    db_session.add_all(
        [
            ChatMessage(session_id=session.id, role="user", content="我希望 agent 记住我关心什么话题。"),
            ChatMessage(session_id=session.id, role="assistant", content="我们会先做 Memory Inbox。"),
        ]
    )
    db_session.commit()

    messages = svc.load_session_messages(db_session, session.id, limit=10)
    prompt_messages = svc.build_memory_extraction_messages(messages)
    joined = json.dumps(prompt_messages, ensure_ascii=False)

    assert "candidates" in joined
    assert "evidence_message_id" in joined
    assert "我希望 agent 记住我关心什么话题" in joined
    assert "Memory Inbox" in joined


def test_parse_memory_candidates_accepts_fenced_json():
    raw = """```json
    {
      "candidates": [
        {
          "content": "用户希望 agent 记住长期讨论的问题。",
          "statement_type": "preference",
          "temporal_type": "stable",
          "confidence": 0.88,
          "importance": 0.8,
          "risk_level": "medium",
          "decision_hint": "review",
          "evidence_message_id": "msg-1"
        }
      ]
    }
    ```"""

    candidates = svc.parse_memory_candidates(raw)

    assert len(candidates) == 1
    assert candidates[0].content == "用户希望 agent 记住长期讨论的问题。"
    assert candidates[0].statement_type == "preference"
    assert candidates[0].evidence_message_id == "msg-1"


def test_parse_memory_candidates_skips_invalid_candidates():
    raw = {
        "candidates": [
            {"content": "", "statement_type": "preference"},
            {"content": "有效记忆", "confidence": 1.4, "importance": -1},
            {"content": "低置信度记忆", "confidence": 0.2},
        ]
    }

    candidates = svc.parse_memory_candidates(json.dumps(raw, ensure_ascii=False))

    assert len(candidates) == 1
    assert candidates[0].content == "有效记忆"
    assert candidates[0].confidence == 1.0
    assert candidates[0].importance == 0.0


def test_extract_session_memories_creates_traceable_drafts(db_session, monkeypatch):
    session = ChatSession(user_id="default-user", title="Memory design")
    db_session.add(session)
    db_session.flush()
    message = ChatMessage(
        session_id=session.id,
        role="user",
        content="我希望 agent 记住我正在设计长期记忆系统。",
    )
    db_session.add(message)
    db_session.commit()

    def fake_llm(prompt_messages):
        return json.dumps(
            {
                "candidates": [
                    {
                        "content": "用户正在设计长期记忆系统。",
                        "statement_type": "current_focus",
                        "temporal_type": "current",
                        "confidence": 0.9,
                        "importance": 0.85,
                        "risk_level": "medium",
                        "decision_hint": "review",
                        "evidence_message_id": message.id,
                    }
                ]
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(svc, "_call_memory_extraction_llm", fake_llm)

    result = svc.extract_session_memories(db_session, session.id)

    assert result.messages_scanned == 1
    assert result.candidates_found == 1
    assert result.drafts_created == 1
    draft = db_session.query(MemoryDraft).one()
    source = db_session.query(MemorySource).one()
    assert draft.payload["content"] == "用户正在设计长期记忆系统。"
    assert draft.payload["statement_type"] == "current_focus"
    assert draft.source_id == source.id
    assert source.source_type == "chat_message"
    assert source.session_id == session.id
    assert source.message_id == message.id


def test_extract_session_memories_skips_duplicate_drafts_and_statements(db_session, monkeypatch):
    session = ChatSession(user_id="default-user", title="Memory design")
    db_session.add(session)
    db_session.flush()
    message = ChatMessage(session_id=session.id, role="user", content="我偏好审核台优先。")
    source = MemorySource(
        user_id="default-user",
        source_type="chat_message",
        source_id=message.id,
        session_id=session.id,
        message_id=message.id,
        span_text=message.content,
    )
    existing = MemoryStatement(
        user_id="default-user",
        content="用户偏好审核台优先。",
        statement_type="preference",
        status="confirmed",
        source=source,
    )
    db_session.add_all([message, source, existing])
    db_session.commit()

    def fake_llm(prompt_messages):
        return json.dumps(
            {
                "candidates": [
                    {
                        "content": " 用户偏好审核台优先。 ",
                        "statement_type": "preference",
                        "confidence": 0.9,
                        "evidence_message_id": message.id,
                    }
                ]
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(svc, "_call_memory_extraction_llm", fake_llm)

    result = svc.extract_session_memories(db_session, session.id)

    assert result.drafts_created == 0
    assert result.candidates_skipped == 1
    assert db_session.query(MemoryDraft).count() == 0


def test_extract_session_memories_detects_conflicts_with_existing_statements(db_session, monkeypatch):
    from backend.app.models.memory import MemoryStatus

    session = ChatSession(user_id="default-user", title="Pref shift")
    db_session.add(session)
    db_session.flush()
    message = ChatMessage(session_id=session.id, role="user", content="我现在改成用深色主题了。")
    source = MemorySource(
        user_id="default-user",
        source_type="chat_message",
        source_id=message.id,
        session_id=session.id,
        message_id=message.id,
        span_text=message.content,
    )
    existing = MemoryStatement(
        user_id="default-user",
        content="用户偏好使用浅色主题阅读。",
        statement_type="preference",
        temporal_type="stable",
        status=MemoryStatus.CONFIRMED,
        source=source,
    )
    db_session.add_all([message, source, existing])
    db_session.commit()
    existing_id = existing.id

    def fake_llm(prompt_messages):
        return json.dumps(
            {
                "candidates": [
                    {
                        "content": "用户偏好使用深色主题阅读。",
                        "statement_type": "preference",
                        "confidence": 0.85,
                        "evidence_message_id": message.id,
                    }
                ]
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(svc, "_call_memory_extraction_llm", fake_llm)

    result = svc.extract_session_memories(db_session, session.id)

    assert result.drafts_created == 1
    draft = db_session.query(MemoryDraft).one()
    assert existing_id in (draft.conflict_ids or [])


def test_detect_conflicts_ignores_different_statement_types():
    from backend.app.services.memory_extraction import MemoryCandidate, _detect_conflicts

    candidate = MemoryCandidate(content="用户偏好深色主题", statement_type="preference")
    confirmed = [("s1", "用户偏好深色主题阅读", "goal")]

    assert _detect_conflicts(candidate, confirmed) == []


def test_detect_conflicts_requires_sufficient_overlap():
    from backend.app.services.memory_extraction import MemoryCandidate, _detect_conflicts

    candidate = MemoryCandidate(content="用户喜欢深夜整理碎片", statement_type="habit")
    confirmed = [("s1", "用户偏好深色主题阅读", "habit")]

    assert _detect_conflicts(candidate, confirmed) == []


def test_parse_memory_candidates_parses_explicitness_and_sensitivity():
    raw = json.dumps({
        "candidates": [
            {
                "content": "用户使用 Python 作为主力语言",
                "statement_type": "preference",
                "temporal_type": "stable",
                "confidence": 0.9,
                "importance": 0.8,
                "explicitness": 0.95,
                "sensitivity_flag": False,
                "evidence_message_id": "msg-a",
            },
            {
                "content": "用户身份证号为 xxx",
                "statement_type": "fact",
                "confidence": 0.85,
                "explicitness": 1.0,
                "sensitivity_flag": True,
                "evidence_message_id": "msg-b",
            },
        ]
    }, ensure_ascii=False)

    candidates = svc.parse_memory_candidates(raw)

    assert len(candidates) == 2
    assert candidates[0].explicitness == 0.95
    assert candidates[0].sensitivity_flag is False
    assert candidates[1].explicitness == 1.0
    assert candidates[1].sensitivity_flag is True


def test_parse_memory_candidates_handles_sensitivity_as_int():
    """sensitivity_flag may come as 0/1 int, parse as bool."""
    raw = json.dumps({
        "candidates": [
            {"content": "test", "sensitivity_flag": 1, "explicitness": 0.85},
        ]
    })
    candidates = svc.parse_memory_candidates(raw)
    assert len(candidates) == 1
    assert candidates[0].sensitivity_flag is True


def test_load_session_messages_with_watermark_splits_correctly(db_session):
    session = ChatSession(user_id="default-user", title="Watermark test")
    db_session.add(session)
    db_session.flush()

    msgs = []
    for i in range(10):
        m = ChatMessage(session_id=session.id, role="user", content=f"msg{i}")
        db_session.add(m)
        msgs.append(m)
    db_session.commit()

    # Watermark at message index 3 (split at msg idx 4)
    watermark_id = msgs[3].id
    context, new = svc.load_session_messages_with_watermark(
        db_session, session.id, watermark_id, context_window=5,
    )

    # Context should include messages before watermark (limited to 5)
    assert len(context) <= 5
    # New messages = msgs[4:] = 6 messages
    assert len(new) == 6
    assert new[0].content == "msg4"
    assert new[-1].content == "msg9"


def test_load_session_messages_with_watermark_no_watermark_returns_all_new(db_session):
    session = ChatSession(user_id="default-user", title="No watermark")
    db_session.add(session)
    db_session.flush()

    for i in range(3):
        db_session.add(ChatMessage(session_id=session.id, role="user", content=f"msg{i}"))
    db_session.commit()

    context, new = svc.load_session_messages_with_watermark(
        db_session, session.id, "", context_window=5,
    )

    # No watermark → all messages are new, context is empty
    assert len(context) == 0
    assert len(new) == 3


def test_load_session_messages_with_watermark_404_on_missing_session(db_session):
    import pytest
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        svc.load_session_messages_with_watermark(db_session, "nonexistent-id")
    assert exc_info.value.status_code == 404


def test_evaluate_auto_confirm_sensitivity_veto(db_session):
    """sensitivity_flag=True must force 'review' regardless of score."""
    from backend.app.services.memory_extraction import MemoryCandidate

    candidate = MemoryCandidate(
        content="用户的身份证号是 xxx",
        statement_type="fact",
        confidence=0.99,
        explicitness=1.0,
        sensitivity_flag=True,
    )

    score, decision, conflicts = svc.evaluate_auto_confirm(
        db_session, candidate, session_id="",
    )

    assert decision == "review"
    assert score == 0.0  # vetoed


def test_evaluate_auto_confirm_low_confidence_decision_review(db_session):
    """Low confidence on a decision type should result in review."""
    candidate = svc.MemoryCandidate(
        content="用户决定使用微服务架构",
        statement_type="decision",
        confidence=0.6,
        explicitness=0.5,
        sensitivity_flag=False,
        importance=0.7,
    )

    score, decision, conflicts = svc.evaluate_auto_confirm(
        db_session, candidate, session_id="",
    )

    assert decision == "review"
    # Score should be well below 0.85 threshold
    assert score < 0.85
