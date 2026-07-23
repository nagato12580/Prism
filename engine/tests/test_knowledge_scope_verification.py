import pytest


@pytest.mark.parametrize("now", [200, 200.1, 201])
def test_scope_expiry_is_enforced_at_and_after_deadline(now):
    from backend.app.security.knowledge_scope import AuthorizedKnowledgeScope, sign_scope
    from engine.app.security.knowledge_scope import ExpiredKnowledgeScope, verify_scope

    token = sign_scope(
        AuthorizedKnowledgeScope(
            actor_id="alice",
            tenant_id="tenant-a",
            allowed_kb_uids=("kb-a",),
            run_id="run-1",
            expires_at=200,
        ),
        secret="scope-secret",
    )

    with pytest.raises(ExpiredKnowledgeScope):
        verify_scope(token, secret="scope-secret", now=now)


@pytest.mark.parametrize("token", ["", "one-part", "a.b.c", "not-base64.invalid"])
def test_malformed_scope_is_rejected(token):
    from engine.app.security.knowledge_scope import InvalidKnowledgeScope, verify_scope

    with pytest.raises(InvalidKnowledgeScope):
        verify_scope(token, secret="scope-secret", now=100)
