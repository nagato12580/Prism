import base64
import json

import pytest


def _decode_part(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _encode_part(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def test_scope_round_trip_is_accepted_by_engine_verifier():
    from backend.app.security.knowledge_scope import AuthorizedKnowledgeScope, sign_scope
    from engine.app.security.knowledge_scope import verify_scope

    scope = AuthorizedKnowledgeScope(
        actor_id="alice",
        tenant_id="tenant-a",
        allowed_kb_uids=("kb-a",),
        run_id="run-1",
        expires_at=200,
    )

    verified = verify_scope(sign_scope(scope, secret="scope-secret"), secret="scope-secret", now=100)

    assert verified.actor_id == "alice"
    assert verified.allowed_kb_uids == ("kb-a",)


def test_scope_signature_rejects_tampered_payload():
    from backend.app.security.knowledge_scope import AuthorizedKnowledgeScope, sign_scope
    from engine.app.security.knowledge_scope import InvalidKnowledgeScope, verify_scope

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
    payload, signature = token.split(".")
    decoded = json.loads(_decode_part(payload))
    decoded["allowed_kb_uids"] = ["kb-b"]
    tampered = f"{_encode_part(json.dumps(decoded, sort_keys=True, separators=(',', ':')).encode())}.{signature}"

    with pytest.raises(InvalidKnowledgeScope):
        verify_scope(tampered, secret="scope-secret", now=100)
