from backend.app.models import ModelProvider, SystemConfig


def test_model_provider_columns_registered():
    cols = {c.name for c in ModelProvider.__table__.columns}
    assert {"id", "provider_id", "display_name", "provider_type", "base_url",
            "api_key_env", "api_key", "capabilities", "enabled_models",
            "is_enabled", "is_builtin"} <= cols


def test_system_config_columns_registered():
    cols = {c.name for c in SystemConfig.__table__.columns}
    assert {"key", "value"} <= cols
