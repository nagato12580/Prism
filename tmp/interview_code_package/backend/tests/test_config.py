import importlib


def _load_settings(monkeypatch, **env):
    keys = {
        "NEO4J_URI",
        "NEO4J_USERNAME",
        "NEO4J_PASSWORD",
        "NEO4J_DATABASE",
        "ENTITY_GRAPH_ENABLED",
    }
    for key in keys:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    config = importlib.import_module("backend.app.config")
    config = importlib.reload(config)
    return config.Settings()


def test_settings_include_default_neo4j_values(monkeypatch):
    settings = _load_settings(monkeypatch)

    assert settings.NEO4J_URI == "bolt://localhost:7687"
    assert settings.NEO4J_USERNAME == "neo4j"
    assert settings.NEO4J_PASSWORD == "password"
    assert settings.NEO4J_DATABASE == "neo4j"
    assert settings.ENTITY_GRAPH_ENABLED is False


def test_settings_read_neo4j_values_from_environment(monkeypatch):
    settings = _load_settings(
        monkeypatch,
        NEO4J_URI="bolt://neo4j:7687",
        NEO4J_USERNAME="graph-user",
        NEO4J_PASSWORD="graph-password",
        NEO4J_DATABASE="prism",
        ENTITY_GRAPH_ENABLED="1",
    )

    assert settings.NEO4J_URI == "bolt://neo4j:7687"
    assert settings.NEO4J_USERNAME == "graph-user"
    assert settings.NEO4J_PASSWORD == "graph-password"
    assert settings.NEO4J_DATABASE == "prism"
    assert settings.ENTITY_GRAPH_ENABLED is True
