from backend.app.models import ModelProvider, SystemConfig


def test_model_provider_columns_registered():
    cols = {c.name for c in ModelProvider.__table__.columns}
    assert {"id", "provider_id", "display_name", "provider_type", "base_url",
            "api_key_env", "api_key", "capabilities", "enabled_models",
            "is_enabled", "is_builtin"} <= cols


def test_system_config_columns_registered():
    cols = {c.name for c in SystemConfig.__table__.columns}
    assert {"key", "value"} <= cols


import pytest
from backend.app.models import ModelProvider, SystemConfig
from backend.app.services.model_providers import (
    ProviderConflict,
    ProviderInUse,
    ProviderNotFound,
    create_provider,
    delete_provider,
    get_default_chat_model,
    set_default_chat_model,
)


def _seed_default(db, spec="deepseek:deepseek-chat"):
    db.add(SystemConfig(key="default_chat_model", value=spec))
    db.commit()


def test_create_provider_encrypts_inline_key(db_session):
    p = create_provider(
        db_session, provider_id="siliconflow", display_name="SF", provider_type="openai",
        base_url="https://api.siliconflow.cn/v1", api_key="sk-abc", enabled_models=["bge-m3"],
    )
    assert p.api_key != "sk-abc"
    assert "sk-abc" not in p.api_key


def test_create_duplicate_provider_raises_conflict(db_session):
    create_provider(db_session, provider_id="deepseek", display_name="D", provider_type="openai", base_url="https://x")
    with pytest.raises(ProviderConflict):
        create_provider(db_session, provider_id="deepseek", display_name="D2", provider_type="openai", base_url="https://x")


def test_delete_provider_in_use_raises(db_session):
    p = create_provider(db_session, provider_id="deepseek", display_name="D", provider_type="openai", base_url="https://x", enabled_models=["deepseek-chat"])
    _seed_default(db_session, "deepseek:deepseek-chat")
    with pytest.raises(ProviderInUse):
        delete_provider(db_session, provider_id="deepseek")


def test_set_and_get_default(db_session):
    set_default_chat_model(db_session, "deepseek:deepseek-chat")
    assert get_default_chat_model(db_session) == "deepseek:deepseek-chat"
    set_default_chat_model(db_session, "openai:gpt-4o")
    assert get_default_chat_model(db_session) == "openai:gpt-4o"


def test_delete_missing_provider_raises_not_found(db_session):
    with pytest.raises(ProviderNotFound):
        delete_provider(db_session, provider_id="ghost")
