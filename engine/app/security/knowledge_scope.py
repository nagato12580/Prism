"""Verification for Backend-signed knowledge-run scopes."""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class InvalidKnowledgeScope(ValueError):
    """The token is malformed, invalidly signed, or has an invalid payload."""


class ExpiredKnowledgeScope(InvalidKnowledgeScope):
    """The signed scope is valid but no longer usable."""


class AuthorizedKnowledgeScope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    actor_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    allowed_kb_uids: tuple[str, ...]
    run_id: str = Field(min_length=1)
    expires_at: int = Field(gt=0)


def _decode(value: str) -> bytes:
    return base64.b64decode(
        value + "=" * (-len(value) % 4),
        altchars=b"-_",
        validate=True,
    )


def verify_scope(
    token: str,
    secret: str,
    *,
    now: int | float | None = None,
) -> AuthorizedKnowledgeScope:
    if not token or not secret:
        raise InvalidKnowledgeScope("knowledge scope token and secret are required")
    try:
        payload_part, signature_part = token.split(".")
        payload = _decode(payload_part)
        signature = _decode(signature_part)
    except (ValueError, binascii.Error) as exc:
        raise InvalidKnowledgeScope("malformed knowledge scope token") from exc

    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        raise InvalidKnowledgeScope("invalid knowledge scope signature")
    try:
        scope = AuthorizedKnowledgeScope.model_validate(json.loads(payload))
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
        raise InvalidKnowledgeScope("invalid knowledge scope payload") from exc
    if scope.expires_at <= (time.time() if now is None else now):
        raise ExpiredKnowledgeScope("knowledge scope has expired")
    return scope
