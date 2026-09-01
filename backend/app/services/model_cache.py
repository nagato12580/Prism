# prism/backend/app/services/model_cache.py
import base64
import hashlib

from backend.app.config import settings


def _fernet():
    from cryptography.fernet import Fernet

    key = base64.urlsafe_b64encode(hashlib.sha256(settings.JWT_SECRET.encode()).digest())
    return Fernet(key)


def encrypt_secret(plain: str | None) -> str | None:
    if not plain:
        return None
    return _fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str | None) -> str | None:
    if not token:
        return None
    return _fernet().decrypt(token.encode("ascii")).decode("utf-8")


def mask_secret(plain: str | None) -> str | None:
    if not plain:
        return None
    return f"••••{plain[-4:]}"


import json
import logging
import os
from dataclasses import dataclass

import redis
from sqlalchemy.orm import Session

from backend.app.models import ModelProvider, SystemConfig

CACHE_KEY = "prism:model-cache"
DEFAULT_CHAT_KEY = "default_chat_model"

logger = logging.getLogger(__name__)


class ModelSpecNotFound(RuntimeError):
    pass


class ModelSpecTypeMismatch(RuntimeError):
    pass


@dataclass(frozen=True)
class ResolvedChatModel:
    model: str
    base_url: str
    api_key: str
    provider_type: str


def _resolve_api_key(provider: ModelProvider) -> str:
    if provider.api_key_env:
        return os.getenv(provider.api_key_env) or ""
    return decrypt_secret(provider.api_key) or ""


def _get_default_chat_model(db: Session) -> str | None:
    row = db.query(SystemConfig).filter_by(key=DEFAULT_CHAT_KEY).one_or_none()
    return row.value if row else None


def build_model_cache(db: Session) -> dict:
    models: dict[str, dict] = {}
    for p in db.query(ModelProvider).filter_by(is_enabled=True).all():
        api_key = _resolve_api_key(p)
        for model_id in (p.enabled_models or []):
            spec = f"{p.provider_id}:{model_id}"
            models[spec] = {
                "spec": spec,
                "model_type": "chat",
                "display_name": model_id,
                "provider_id": p.provider_id,
                "provider_type": p.provider_type,
                "api_key": api_key,
                "base_url": p.base_url,
                "headers": p.headers_json or {},
                "extra": p.extra_json or {},
            }
    return {"models": models, "default_chat_model": _get_default_chat_model(db)}


def _redis():
    return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)


def refresh_model_cache(db: Session) -> None:
    payload = json.dumps(build_model_cache(db))
    try:
        _redis().set(CACHE_KEY, payload)
    except Exception:
        # Best-effort: if Redis is unavailable (e.g. unit tests without Redis),
        # the next load_model_cache() falls back to rebuilding from the DB.
        logger.debug("Model cache refresh skipped (Redis unavailable); next load falls back to DB", exc_info=True)


def load_model_cache() -> dict:
    try:
        raw = _redis().get(CACHE_KEY)
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    from backend.app.database import SessionLocal

    db = SessionLocal()
    try:
        return build_model_cache(db)
    finally:
        db.close()


def resolve_default_chat_model() -> ResolvedChatModel:
    cache = load_model_cache()
    default = cache.get("default_chat_model")
    if not default:
        raise ModelSpecNotFound("default chat model is not configured")
    entry = cache.get("models", {}).get(default)
    if entry is None:
        raise ModelSpecNotFound(f"default chat model spec not found in cache: {default}")
    if entry.get("model_type") != "chat":
        raise ModelSpecTypeMismatch(f"spec {default} is not a chat model")
    return ResolvedChatModel(
        model=entry["spec"].split(":", 1)[1],
        base_url=entry["base_url"],
        api_key=entry["api_key"] or "",
        provider_type=entry["provider_type"],
    )
