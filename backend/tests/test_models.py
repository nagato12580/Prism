# prism/backend/tests/test_models.py
import pytest
from sqlalchemy.exc import IntegrityError

from backend.app.models import KnowledgeFile, KnowledgeItem, KnowledgeTopic, KnowledgeChunk, ChatSession, ChatMessage


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


def test_topic_resource_relationship_and_metadata(db_session):
    topic = KnowledgeTopic(user_id="default-user", name="Product Docs", description="Launch files")
    db_session.add(topic)
    db_session.commit()

    resource = KnowledgeFile(
        user_id="default-user",
        topic_id=topic.id,
        title="Roadmap",
        original_filename="roadmap.md",
        media_type="document",
        mime_type="text/markdown",
        file_ext=".md",
        file_size=18,
        md5="md5-roadmap",
        storage_path="uploads/default-user/topic/roadmap.md",
        processing_status="completed",
        description="Q3 notes",
        tags=["roadmap", "q3"],
        source_type="upload",
        page_count=1,
        content_text="# Roadmap",
    )
    db_session.add(resource)
    db_session.commit()

    loaded = db_session.query(KnowledgeTopic).filter_by(name="Product Docs").one()
    assert loaded.resources[0].title == "Roadmap"
    assert loaded.resources[0].tags == ["roadmap", "q3"]
    assert loaded.resources[0].uploaded_at is not None


def test_duplicate_resource_md5_is_rejected_per_user_topic(db_session):
    topic = KnowledgeTopic(user_id="default-user", name="Research")
    db_session.add(topic)
    db_session.commit()

    first = KnowledgeFile(
        user_id="default-user",
        topic_id=topic.id,
        title="A",
        original_filename="a.txt",
        media_type="document",
        file_ext=".txt",
        file_size=3,
        md5="same-md5",
        storage_path="uploads/a.txt",
        processing_status="completed",
    )
    second = KnowledgeFile(
        user_id="default-user",
        topic_id=topic.id,
        title="A Copy",
        original_filename="a-copy.txt",
        media_type="document",
        file_ext=".txt",
        file_size=3,
        md5="same-md5",
        storage_path="uploads/a-copy.txt",
        processing_status="completed",
    )
    db_session.add_all([first, second])

    with pytest.raises(IntegrityError):
        db_session.commit()
