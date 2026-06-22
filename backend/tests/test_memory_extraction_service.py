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
