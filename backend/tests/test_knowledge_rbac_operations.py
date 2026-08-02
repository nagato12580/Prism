"""Task 5: Fine-grained RBAC enforcement tests for knowledge operations.

Covers file upload, mindmap generation, and chat proxy authorization
with managed KB membership roles (viewer/contributor/editor).
"""

from backend.app.models import KnowledgeBaseMembership, KnowledgeBaseRole, KnowledgeGovernanceStatus, KnowledgeTopic


def auth_headers(user: str, tenant: str = "tenant-a"):
    return {"X-Prism-Actor": user, "X-Prism-Tenant": tenant}


def seed_managed(db_session, owner="alice"):
    topic = KnowledgeTopic(
        tenant_id="tenant-a",
        owner_user_id=owner,
        name="Managed",
        governance_status=KnowledgeGovernanceStatus.MANAGED.value,
        active_index_generation="idx-1",
    )
    db_session.add(topic)
    db_session.commit()
    return topic


def grant(db_session, topic, user_id, role):
    db_session.add(KnowledgeBaseMembership(
        tenant_id=topic.tenant_id,
        kb_uid=topic.kb_uid,
        user_id=user_id,
        role=role,
        granted_by="admin",
    ))
    db_session.commit()


def test_viewer_cannot_upload_file(client, db_session):
    topic = seed_managed(db_session)
    grant(db_session, topic, "viewer", KnowledgeBaseRole.VIEWER.value)

    response = client.post(
        f"/api/v1/knowledge-bases/{topic.kb_uid}/files",
        files={"file": ("note.txt", b"hello", "text/plain")},
        headers=auth_headers("viewer"),
    )
    assert response.status_code == 403


def test_contributor_cannot_generate_mindmap(client, db_session):
    topic = seed_managed(db_session)
    grant(db_session, topic, "contributor", KnowledgeBaseRole.CONTRIBUTOR.value)

    response = client.post(
        f"/api/v1/knowledge-bases/{topic.kb_uid}/mindmap/generate",
        json={"idempotency_key": "mindmap-1"},
        headers=auth_headers("contributor"),
    )
    assert response.status_code == 403


def test_editor_can_generate_mindmap(client, db_session, monkeypatch):
    topic = seed_managed(db_session)
    grant(db_session, topic, "editor", KnowledgeBaseRole.EDITOR.value)

    def fake_publish(job_id: str) -> None:
        return None

    monkeypatch.setattr("backend.app.api.knowledge_enrichment._publish_job_id", fake_publish)

    response = client.post(
        f"/api/v1/knowledge-bases/{topic.kb_uid}/mindmap/generate",
        json={"idempotency_key": "mindmap-2"},
        headers=auth_headers("editor"),
    )
    assert response.status_code == 202


def test_chat_proxy_rejects_unreadable_requested_kb(client, db_session):
    topic = seed_managed(db_session)

    response = client.post(
        "/api/v1/chat/answer",
        json={"query": "hello", "kb_uids": [topic.kb_uid]},
        headers=auth_headers("bob"),
    )
    assert response.status_code == 403
