# backend/tests/test_knowledge_access.py
import pytest

from backend.app.models import KnowledgeTopic
from backend.app.security.actor import ActorContext


def test_policy_allows_owner_read(db_session):
    from backend.app.services.knowledge_access import KnowledgeAccessPolicy

    topic = KnowledgeTopic(
        tenant_id="tenant-a",
        owner_user_id="owner",
        name="Shared",
    )
    db_session.add(topic)
    db_session.commit()

    actor = ActorContext(actor_id="owner", tenant_id="tenant-a", roles=())
    result = KnowledgeAccessPolicy(db_session).require_read(actor, topic.kb_uid)
    assert result.kb_uid == topic.kb_uid


def test_policy_rejects_non_owner(db_session):
    from backend.app.services.knowledge_access import KnowledgeAccessDenied, KnowledgeAccessPolicy

    topic = KnowledgeTopic(
        tenant_id="tenant-a",
        owner_user_id="owner",
        name="Private",
    )
    db_session.add(topic)
    db_session.commit()

    actor = ActorContext(actor_id="other", tenant_id="tenant-a", roles=())
    with pytest.raises(KnowledgeAccessDenied):
        KnowledgeAccessPolicy(db_session).require_read(actor, topic.kb_uid)


def test_policy_rejects_wrong_tenant(db_session):
    from backend.app.services.knowledge_access import KnowledgeAccessDenied, KnowledgeAccessPolicy

    topic = KnowledgeTopic(
        tenant_id="tenant-a",
        owner_user_id="owner",
        name="Tenant-isolated",
    )
    db_session.add(topic)
    db_session.commit()

    actor = ActorContext(actor_id="owner", tenant_id="tenant-b", roles=())
    with pytest.raises(KnowledgeAccessDenied):
        KnowledgeAccessPolicy(db_session).require_read(actor, topic.kb_uid)


def test_policy_raises_not_found_for_missing_kb(db_session):
    from backend.app.services.knowledge_access import KnowledgeNotFound, KnowledgeAccessPolicy

    actor = ActorContext(actor_id="owner", tenant_id="tenant-a", roles=())
    with pytest.raises(KnowledgeNotFound):
        KnowledgeAccessPolicy(db_session).require_read(actor, "nonexistent")


def test_policy_excludes_deleted_topic(db_session):
    from backend.app.services.knowledge_access import KnowledgeNotFound, KnowledgeAccessPolicy
    from backend.app.utils.time import local_now

    topic = KnowledgeTopic(
        tenant_id="tenant-a",
        owner_user_id="owner",
        name="Deleted KB",
        deleted_at=local_now(),
    )
    db_session.add(topic)
    db_session.commit()

    actor = ActorContext(actor_id="owner", tenant_id="tenant-a", roles=())
    with pytest.raises(KnowledgeNotFound):
        KnowledgeAccessPolicy(db_session).require_read(actor, topic.kb_uid)


def test_require_manage_same_as_read_for_phase_one(db_session):
    from backend.app.services.knowledge_access import KnowledgeAccessPolicy

    topic = KnowledgeTopic(
        tenant_id="tenant-a",
        owner_user_id="owner",
        name="Manageable",
    )
    db_session.add(topic)
    db_session.commit()

    actor = ActorContext(actor_id="owner", tenant_id="tenant-a", roles=())
    result = KnowledgeAccessPolicy(db_session).require_manage(actor, topic.kb_uid)
    assert result.kb_uid == topic.kb_uid
