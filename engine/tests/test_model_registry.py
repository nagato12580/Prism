from backend.app.services.model_cache import ResolvedChatModel


def test_create_chat_model_uses_resolved_spec(monkeypatch):
    from engine.app.agent import runner

    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(runner, "ChatOpenAI", FakeChatOpenAI)
    monkeypatch.setattr(
        runner, "resolve_default_chat_model",
        lambda: ResolvedChatModel(model="deepseek-chat", base_url="https://api.deepseek.com/v1",
                                  api_key="sk-x", provider_type="openai"),
    )
    model = runner.create_chat_model()
    assert captured["model"] == "deepseek-chat"
    assert captured["base_url"] == "https://api.deepseek.com/v1"
    assert captured["api_key"] == "sk-x"
    assert model is not None
