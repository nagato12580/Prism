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
    ProviderValidationError,
    create_provider,
    delete_provider,
    get_default_chat_model,
    set_default_chat_model,
    update_provider,
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
    create_provider(db_session, provider_id="deepseek", display_name="D", provider_type="openai", base_url="https://x", enabled_models=["deepseek-chat"])
    create_provider(db_session, provider_id="openai", display_name="O", provider_type="openai", base_url="https://x", enabled_models=["gpt-4o"])
    set_default_chat_model(db_session, "deepseek:deepseek-chat")
    assert get_default_chat_model(db_session) == "deepseek:deepseek-chat"
    set_default_chat_model(db_session, "openai:gpt-4o")
    assert get_default_chat_model(db_session) == "openai:gpt-4o"


def test_set_default_invalid_spec_raises(db_session):
    with pytest.raises(ProviderValidationError):
        set_default_chat_model(db_session, "no-colon")


def test_set_default_unknown_provider_raises(db_session):
    with pytest.raises(ProviderValidationError):
        set_default_chat_model(db_session, "ghost:model")


def test_set_default_disabled_provider_raises(db_session):
    create_provider(db_session, provider_id="deepseek", display_name="D", provider_type="openai", base_url="https://x", enabled_models=["deepseek-chat"], is_enabled=False)
    with pytest.raises(ProviderValidationError):
        set_default_chat_model(db_session, "deepseek:deepseek-chat")


def test_set_default_model_not_enabled_raises(db_session):
    create_provider(db_session, provider_id="deepseek", display_name="D", provider_type="openai", base_url="https://x", enabled_models=["deepseek-chat"])
    with pytest.raises(ProviderValidationError):
        set_default_chat_model(db_session, "deepseek:other-model")


def test_delete_missing_provider_raises_not_found(db_session):
    with pytest.raises(ProviderNotFound):
        delete_provider(db_session, provider_id="ghost")


def test_disable_provider_in_use_raises(db_session):
    create_provider(
        db_session, provider_id="deepseek", display_name="D",
        provider_type="openai", base_url="https://x", enabled_models=["deepseek-chat"],
    )
    _seed_default(db_session, "deepseek:deepseek-chat")
    with pytest.raises(ProviderInUse):
        update_provider(db_session, provider_id="deepseek", is_enabled=False)


from backend.app.models import TeamMember, TeamRole


def auth_headers(user, roles=""):
    h = {"X-Prism-Actor": user, "X-Prism-Tenant": "tenant-a"}
    if roles:
        h["X-Prism-Roles"] = roles
    return h


def test_model_provider_endpoints_require_admin(client, db_session):
    for method, path, kw in [
        ("get", "/api/v1/model-providers/providers", {}),
        ("post", "/api/v1/model-providers/providers", {"json": {"provider_id": "x", "display_name": "X", "base_url": "https://x"}}),
        ("get", "/api/v1/model-providers/config/default", {}),
    ]:
        r = getattr(client, method)(path, headers=auth_headers("bob"), **kw)
        assert r.status_code == 403, f"{method.upper()} {path}"


def test_admin_create_and_list_provider(client, db_session):
    db_session.add(TeamMember(tenant_id="tenant-a", user_id="admin", role=TeamRole.ADMIN.value, status="active"))
    db_session.commit()
    created = client.post(
        "/api/v1/model-providers/providers",
        json={"provider_id": "deepseek", "display_name": "DeepSeek", "provider_type": "openai",
              "base_url": "https://api.deepseek.com/v1", "api_key": "sk-abc", "enabled_models": ["deepseek-chat"]},
        headers=auth_headers("admin"),
    )
    assert created.status_code == 200
    body = created.json()
    assert body["provider_id"] == "deepseek"
    assert body["has_api_key"] is True
    assert "sk-abc" not in str(body)  # 明文 key 不回传

    listed = client.get("/api/v1/model-providers/providers", headers=auth_headers("admin"))
    assert listed.status_code == 200
    assert [p["provider_id"] for p in listed.json()["items"]] == ["deepseek"]


from backend.app.services.model_providers import seed_model_providers


def test_seed_creates_default_provider_and_model(db_session, monkeypatch):
    from backend.app import services  # noqa
    import backend.app.services.model_providers as mp

    monkeypatch.setattr(mp.settings, "LLM_API_BASE", "https://api.deepseek.com/v1")
    monkeypatch.setattr(mp.settings, "LLM_MODEL", "deepseek-chat")
    # 让 seed 用传入的 session 而非自开 SessionLocal
    mp._seed_into(db_session)

    providers = db_session.query(ModelProvider).all()
    assert [p.provider_id for p in providers] == ["default"]
    assert providers[0].enabled_models == ["deepseek-chat"]
    assert mp.get_default_chat_model(db_session) == "default:deepseek-chat"
