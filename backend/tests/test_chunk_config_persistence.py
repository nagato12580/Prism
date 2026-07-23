# backend/tests/test_chunk_config_persistence.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.app.database import Base
from backend.app.models import KnowledgeTopic, KnowledgeFile, KnowledgeItem


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def _make_topic_and_item(db_session, name, chunk_config=None):
    topic = KnowledgeTopic(
        tenant_id="t1", owner_user_id="u1", name=name,
        chunk_config=chunk_config,
    )
    db_session.add(topic)
    db_session.flush()
    item = KnowledgeItem(
        tenant_id="t1", kb_uid=topic.kb_uid, title="test-item",
    )
    db_session.add(item)
    db_session.flush()
    return topic, item


def test_snapshot_written_to_knowledge_file(db_session):
    from engine.app.ingestion.presets import chunk_config_snapshot

    topic, item = _make_topic_and_item(
        db_session, "snap-test",
        chunk_config={"preset": "qa", "parent_tokens": 900},
    )

    snap = chunk_config_snapshot("qa")
    d = snap.to_dict()

    file_row = KnowledgeFile(
        tenant_id="t1",
        kb_uid=topic.kb_uid,
        file_uid="file-snap-1",
        item_id=item.id,
        chunk_config_snapshot=d,
    )
    db_session.add(file_row)
    db_session.commit()

    loaded = db_session.get(KnowledgeFile, file_row.id)
    assert loaded.chunk_config_snapshot["preset_id"] == "qa"
    assert loaded.chunk_config_snapshot["parent_tokens"] == 900
    assert loaded.chunk_config_snapshot["separator"] == "\nQ:"


def test_kb_config_change_does_not_alter_existing_file_snapshot(db_session):
    from engine.app.ingestion.presets import chunk_config_snapshot

    topic, item = _make_topic_and_item(
        db_session, "config-test",
        chunk_config={"preset": "general", "parent_tokens": 1200},
    )

    snap1 = chunk_config_snapshot("general")
    file_row = KnowledgeFile(
        tenant_id="t1",
        kb_uid=topic.kb_uid,
        file_uid="file-snap-2",
        item_id=item.id,
        chunk_config_snapshot=snap1.to_dict(),
    )
    db_session.add(file_row)
    db_session.commit()

    topic.chunk_config = {"preset": "laws", "parent_tokens": 600}
    db_session.commit()

    loaded = db_session.get(KnowledgeFile, file_row.id)
    assert loaded.chunk_config_snapshot["preset_id"] == "general"
    assert loaded.chunk_config_snapshot["parent_tokens"] == 1200

    db_session.refresh(topic)
    assert topic.chunk_config["preset"] == "laws"


def test_retry_uses_original_snapshot(db_session):
    from engine.app.ingestion.presets import chunk_config_snapshot

    topic, item = _make_topic_and_item(
        db_session, "retry-test",
        chunk_config={"preset": "separator", "parent_tokens": 1200},
    )

    original_snap = chunk_config_snapshot("separator")
    file_row = KnowledgeFile(
        tenant_id="t1",
        kb_uid=topic.kb_uid,
        file_uid="file-snap-3",
        item_id=item.id,
        chunk_config_snapshot=original_snap.to_dict(),
    )
    db_session.add(file_row)
    db_session.commit()

    topic.chunk_config = {"preset": "book", "parent_tokens": 1600}
    db_session.commit()

    loaded = db_session.get(KnowledgeFile, file_row.id)
    snap_from_file = loaded.chunk_config_snapshot
    assert snap_from_file["preset_id"] == "separator"
    assert snap_from_file["separator"] == "\n---\n"
