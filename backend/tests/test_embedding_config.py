import importlib


def _reload_backend_config(monkeypatch):
    import backend.app.config as config

    monkeypatch.setenv("EMBEDDING_API_BASE", "")
    monkeypatch.setenv("EMBEDDING_API_KEY", "")
    monkeypatch.setenv("EMBEDDING_MODEL", "")
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    return importlib.reload(config)


def test_backend_embedding_defaults_to_siliconflow(monkeypatch):
    config = _reload_backend_config(monkeypatch)

    assert config.settings.EMBEDDING_API_BASE == "https://api.siliconflow.cn/v1"
    assert config.settings.EMBEDDING_MODEL == "BAAI/bge-m3"


def test_backend_embedding_key_falls_back_to_siliconflow_key(monkeypatch):
    import backend.app.config as config

    monkeypatch.setenv("EMBEDDING_API_KEY", "")
    monkeypatch.setenv("SILICONFLOW_API_KEY", "sf-test-key")
    config = importlib.reload(config)

    assert config.settings.EMBEDDING_API_KEY == "sf-test-key"
