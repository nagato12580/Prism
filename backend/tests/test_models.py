# prism/backend/tests/test_models.py
from backend.app.models import KnowledgeItem, KnowledgeChunk, ChatSession, ChatMessage


def test_create_knowledge_item_with_chunk(db_session):
    item = KnowledgeItem(title="测试条目", content="内容", source_type="manual", tags=["test"])
    db_session.add(item)
    db_session.commit()

    chunk = KnowledgeChunk(item_id=item.id, chunk_text="分块文本", chunk_index=0)
    db_session.add(chunk)
    db_session.commit()

    loaded = db_session.query(KnowledgeItem).first()
    assert loaded.title == "测试条目"
    assert loaded.tags == ["test"]
    assert len(loaded.chunks) == 1
    assert loaded.chunks[0].chunk_text == "分块文本"


def test_chat_session_message_cascade(db_session):
    session = ChatSession(title="测试会话")
    db_session.add(session)
    db_session.commit()

    msg = ChatMessage(session_id=session.id, role="user", content="你好")
    db_session.add(msg)
    db_session.commit()

    loaded = db_session.query(ChatSession).first()
    assert loaded.title == "测试会话"
    assert len(loaded.messages) == 1
    assert loaded.messages[0].role == "user"
