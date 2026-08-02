from backend.app.models import KnowledgeBaseMembership, KnowledgeBaseRole, KnowledgeGovernanceStatus, KnowledgeTopic, TeamMember, TeamRole


def auth_headers(user: str, tenant: str = "tenant-a", roles: str = ""):
    headers = {"X-Prism-Actor": user, "X-Prism-Tenant": tenant}
    if roles:
        headers["X-Prism-Roles"] = roles
    return headers


def seed_team_admin(db_session, user_id="admin"):
    db_session.add(TeamMember(tenant_id="tenant-a", user_id=user_id, role=TeamRole.ADMIN.value, status="active"))
    db_session.commit()


def seed_topic(db_session, owner="alice", status=KnowledgeGovernanceStatus.PERSONAL.value, name="KB"):
    topic = KnowledgeTopic(tenant_id="tenant-a", owner_user_id=owner, name=name, governance_status=status)
    db_session.add(topic)
    db_session.commit()
    return topic


def test_list_hides_unowned_personal_kb(client, db_session):
    visible = seed_topic(db_session, owner="alice", name="Mine")
    hidden = seed_topic(db_session, owner="bob", name="Hidden")

    response = client.get("/api/v1/knowledge-bases", headers=auth_headers("alice"))
    assert response.status_code == 200
    ids = {item["kb_uid"] for item in response.json()["items"]}
    assert visible.kb_uid in ids
    assert hidden.kb_uid not in ids


def test_transfer_accept_flow(client, db_session):
    seed_team_admin(db_session)
    topic = seed_topic(db_session, owner="alice")

    response = client.post(
        f"/api/v1/knowledge-bases/{topic.kb_uid}/transfer-request",
        json={"message": "please share"},
        headers=auth_headers("alice"),
    )
    assert response.status_code == 200
    assert response.json()["governance_status"] == "pending_transfer"
    assert response.json()["can_delete"] is False

    pending = client.get(
        "/api/v1/knowledge-bases/admin/transfer-requests",
        headers=auth_headers("admin"),
    )
    assert pending.status_code == 200
    assert topic.kb_uid in {item["kb_uid"] for item in pending.json()["items"]}

    accepted = client.post(
        f"/api/v1/knowledge-bases/admin/transfer-requests/{topic.kb_uid}/accept",
        headers=auth_headers("admin"),
    )
    assert accepted.status_code == 200
    assert accepted.json()["governance_status"] == "managed"

    membership = db_session.query(KnowledgeBaseMembership).filter_by(
        tenant_id="tenant-a",
        kb_uid=topic.kb_uid,
        user_id="alice",
    ).one()
    assert membership.role == KnowledgeBaseRole.EDITOR.value


def test_managed_kb_requires_membership_for_member_visibility(client, db_session):
    topic = seed_topic(db_session, owner="alice", status=KnowledgeGovernanceStatus.MANAGED.value)

    hidden = client.get("/api/v1/knowledge-bases", headers=auth_headers("bob"))
    assert hidden.status_code == 200
    assert topic.kb_uid not in {item["kb_uid"] for item in hidden.json()["items"]}

    db_session.add(KnowledgeBaseMembership(
        tenant_id="tenant-a",
        kb_uid=topic.kb_uid,
        user_id="bob",
        role=KnowledgeBaseRole.VIEWER.value,
        granted_by="admin",
    ))
    db_session.commit()

    visible = client.get("/api/v1/knowledge-bases", headers=auth_headers("bob"))
    assert visible.status_code == 200
    item = next(item for item in visible.json()["items"] if item["kb_uid"] == topic.kb_uid)
    assert item["my_role"] == "viewer"
    assert item["can_read"] is True
    assert item["can_contribute"] is False


def test_admin_can_grant_membership(client, db_session):
    seed_team_admin(db_session)
    topic = seed_topic(db_session, owner="alice", status=KnowledgeGovernanceStatus.MANAGED.value)

    response = client.put(
        f"/api/v1/knowledge-bases/{topic.kb_uid}/members/bob",
        json={"role": "contributor"},
        headers=auth_headers("admin"),
    )
    assert response.status_code == 200
    assert response.json()["role"] == "contributor"
