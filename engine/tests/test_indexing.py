# engine/tests/test_indexing.py
import pytest


def test_embedding_profile_has_required_fields():
    from engine.app.indexing.profiles import EmbeddingProfile

    profile = EmbeddingProfile("test", "model", 768, "COSINE", True)
    assert profile.provider == "test"
    assert profile.dimension == 768
    assert profile.collection_name == profile.document_collection


def test_default_profile_exists():
    from engine.app.indexing.profiles import DEFAULT_PROFILE

    assert DEFAULT_PROFILE.dimension == 1024
    assert DEFAULT_PROFILE.provider == "siliconflow"
    assert DEFAULT_PROFILE.model == "BAAI/bge-m3"


def test_activate_generation_updates_topic(db_session):
    from engine.app.indexing.publisher import activate_generation
    from backend.app.models import KnowledgeTopic

    topic = KnowledgeTopic(tenant_id="t1", owner_user_id="u1", name="Index KB")
    db_session.add(topic)
    db_session.commit()

    updated = activate_generation(
        db_session, topic.kb_uid, "gen-1", expected_old=None
    )
    assert updated.active_index_generation == "gen-1"


def test_mark_index_complete_updates_file(db_session):
    from engine.app.indexing.publisher import mark_index_complete
    from backend.app.models import KnowledgeTopic, KnowledgeFile
    from backend.app.models.knowledge_types import StageStatus

    topic = KnowledgeTopic(tenant_id="t1", owner_user_id="u1", name="Mark KB")
    db_session.add(topic)
    db_session.flush()

    file_row = KnowledgeFile(
        tenant_id="t1", kb_uid=topic.kb_uid, file_uid="f1",
        original_filename="test.md", index_status=StageStatus.RUNNING.value,
    )
    db_session.add(file_row)
    db_session.commit()

    updated = mark_index_complete(db_session, "f1", "gen-1")
    assert updated.index_status == StageStatus.SUCCEEDED.value
    assert updated.active_index_generation == "gen-1"
