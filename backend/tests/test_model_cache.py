from backend.app.services.model_cache import (
    decrypt_secret,
    encrypt_secret,
    mask_secret,
)


def test_encrypt_decrypt_roundtrip():
    token = encrypt_secret("sk-secret-1234")
    assert token is not None and token != "sk-secret-1234"
    assert decrypt_secret(token) == "sk-secret-1234"


def test_encrypt_none_returns_none():
    assert encrypt_secret(None) is None
    assert decrypt_secret(None) is None


def test_mask_secret():
    assert mask_secret("sk-abcdefgh") == "••••efgh"
    assert mask_secret(None) is None


import pytest
from backend.app.models import ModelProvider, SystemConfig
from backend.app.services.model_cache import (
    ModelSpecNotFound,
    build_model_cache,
    resolve_default_chat_model,
)


def _provider(**overrides):
    base = dict(
        provider_id="deepseek", display_name="DeepSeek", provider_type="openai",
        base_url="https://api.deepseek.com/v1", api_key_env="LLM_API_KEY",
        capabilities={"chat": True}, enabled_models=["deepseek-chat"], is_enabled=True,
    )
    base.update(overrides)
    return ModelProvider(**base)


def test_build_model_cache_resolves_default(db_session):
    db_session.add(_provider())
    db_session.add(SystemConfig(key="default_chat_model", value="deepseek:deepseek-chat"))
    db_session.commit()

    cache = build_model_cache(db_session)
    assert cache["default_chat_model"] == "deepseek:deepseek-chat"
    entry = cache["models"]["deepseek:deepseek-chat"]
    assert entry["base_url"] == "https://api.deepseek.com/v1"
    assert entry["model_type"] == "chat"


def test_resolve_default_chat_model_raises_when_unset(monkeypatch, db_session):
    monkeypatch.setattr(
        "backend.app.services.model_cache.load_model_cache",
        lambda: {"models": {}, "default_chat_model": None},
    )
    with pytest.raises(ModelSpecNotFound):
        resolve_default_chat_model()
