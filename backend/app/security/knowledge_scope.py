"""Signed, run-local authorization scope passed from Backend to Engine."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json

from pydantic import BaseModel, ConfigDict, Field


class AuthorizedKnowledgeScope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    actor_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    allowed_kb_uids: tuple[str, ...]
    run_id: str = Field(min_length=1)
    expires_at: int = Field(gt=0)


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def sign_scope(scope: AuthorizedKnowledgeScope, secret: str) -> str:
    if not secret:
        raise ValueError("knowledge scope signing secret is required")
    payload = json.dumps(
        scope.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return f"{_encode(payload)}.{_encode(signature)}"
