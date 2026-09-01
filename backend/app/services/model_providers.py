# prism/backend/app/services/model_providers.py
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.models import ModelProvider, SystemConfig
from backend.app.utils.time import local_now
from backend.app.services.model_cache import (
    DEFAULT_CHAT_KEY,
    encrypt_secret,
    refresh_model_cache,
)


class ProviderNotFound(LookupError):
    pass


class ProviderConflict(ValueError):
    pass


class ProviderInUse(PermissionError):
    pass


class ProviderValidationError(ValueError):
    pass


def _load(db: Session, provider_id: str) -> ModelProvider:
    row = db.query(ModelProvider).filter_by(provider_id=provider_id).one_or_none()
    if row is None:
        raise ProviderNotFound(f"provider not found: {provider_id}")
    return row


def _assert_not_default(db: Session, provider_id: str) -> None:
    row = db.query(SystemConfig).filter_by(key=DEFAULT_CHAT_KEY).one_or_none()
    if row and row.value and row.value.split(":", 1)[0] == provider_id:
        raise ProviderInUse(f"provider {provider_id} is referenced by default model")


def list_providers(db: Session) -> list[ModelProvider]:
    return db.query(ModelProvider).order_by(ModelProvider.created_at.asc()).all()


def create_provider(
    db: Session,
    *,
    provider_id: str,
    display_name: str,
    provider_type: str = "openai",
    base_url: str,
    api_key_env: str | None = None,
    api_key: str | None = None,
    capabilities: dict | None = None,
    enabled_models: list[str] | None = None,
    headers_json: dict | None = None,
    extra_json: dict | None = None,
    is_enabled: bool = True,
) -> ModelProvider:
    if not provider_id or not display_name or not base_url:
        raise ProviderValidationError("provider_id, display_name, base_url are required")
    if db.query(ModelProvider).filter_by(provider_id=provider_id).one_or_none() is not None:
        raise ProviderConflict(f"provider already exists: {provider_id}")
    row = ModelProvider(
        provider_id=provider_id,
        display_name=display_name,
        provider_type=provider_type,
        base_url=base_url,
        api_key_env=api_key_env,
        api_key=encrypt_secret(api_key),
        capabilities=capabilities or {},
        enabled_models=enabled_models or [],
        headers_json=headers_json,
        extra_json=extra_json,
        is_enabled=is_enabled,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    refresh_model_cache(db)
    return row


def update_provider(db: Session, *, provider_id: str, **fields) -> ModelProvider:
    row = _load(db, provider_id)
    if fields.get("is_enabled") is False:
        _assert_not_default(db, provider_id)
    if "api_key" in fields:
        if fields["api_key"]:  # blank = keep existing
            row.api_key = encrypt_secret(fields["api_key"])
        fields = {k: v for k, v in fields.items() if k != "api_key"}
    for name, value in fields.items():
        if value is not None and hasattr(row, name):
            setattr(row, name, value)
    row.updated_at = local_now()
    db.commit()
    db.refresh(row)
    refresh_model_cache(db)
    return row


def delete_provider(db: Session, *, provider_id: str) -> None:
    row = _load(db, provider_id)
    _assert_not_default(db, provider_id)
    db.delete(row)
    db.commit()
    refresh_model_cache(db)


def get_default_chat_model(db: Session) -> str | None:
    row = db.query(SystemConfig).filter_by(key=DEFAULT_CHAT_KEY).one_or_none()
    return row.value if row else None


def _validate_spec(db: Session, spec: str) -> None:
    if ":" not in spec:
        raise ProviderValidationError(f"invalid model spec (expected provider_id:model_id): {spec}")
    provider_id, model_id = spec.split(":", 1)
    if not provider_id or not model_id:
        raise ProviderValidationError(f"invalid model spec: {spec}")
    provider = db.query(ModelProvider).filter_by(provider_id=provider_id).one_or_none()
    if provider is None:
        raise ProviderValidationError(f"provider not found: {provider_id}")
    if not provider.is_enabled:
        raise ProviderValidationError(f"provider is disabled: {provider_id}")
    if model_id not in (provider.enabled_models or []):
        raise ProviderValidationError(f"model not enabled on provider: {spec}")


def set_default_chat_model(db: Session, spec: str) -> None:
    _validate_spec(db, spec)
    row = db.query(SystemConfig).filter_by(key=DEFAULT_CHAT_KEY).one_or_none()
    if row is None:
        row = SystemConfig(key=DEFAULT_CHAT_KEY, value=spec)
        db.add(row)
    else:
        row.value = spec
        row.updated_at = local_now()
    db.commit()
    refresh_model_cache(db)


def test_connection(spec: str) -> dict:
    from backend.app.services.model_cache import load_model_cache

    entry = load_model_cache().get("models", {}).get(spec)
    if entry is None:
        return {"status": "unavailable", "reason": "spec not found"}
    try:
        from openai import OpenAI

        client = OpenAI(base_url=entry["base_url"], api_key=entry["api_key"] or "none", timeout=10.0, max_retries=1)
        client.models.list()
        return {"status": "available"}
    except Exception as exc:
        return {"status": "error", "reason": str(exc)}


def _seed_into(db: Session) -> None:
    if db.query(ModelProvider).count() > 0:
        return
    model = settings.LLM_MODEL or "qwen-plus"
    db.add(ModelProvider(
        provider_id="default",
        display_name="默认（来自 .env）",
        provider_type="openai",
        base_url=settings.LLM_API_BASE or "",
        api_key_env="LLM_API_KEY",
        capabilities={"chat": True, "embedding": False, "rerank": False},
        enabled_models=[model],
        is_enabled=True,
        is_builtin=True,
    ))
    db.add(SystemConfig(key=DEFAULT_CHAT_KEY, value=f"default:{model}"))
    db.commit()
    refresh_model_cache(db)


def seed_model_providers() -> None:
    from backend.app.database import SessionLocal

    db = SessionLocal()
    try:
        _seed_into(db)
    finally:
        db.close()
