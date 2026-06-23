import json

from backend.app.prompts.asset_parse import build_asset_parse_messages, build_asset_parse_request


def test_build_asset_parse_request_omits_preferences_when_empty():
    msg = build_asset_parse_request(content="hello")
    data = json.loads(msg)
    assert "user_preferences" not in data


def test_build_asset_parse_request_includes_preferences_when_provided():
    msg = build_asset_parse_request(content="hello", user_preferences="【偏好】用户喜欢轻量")
    data = json.loads(msg)
    assert data["user_preferences"] == "【偏好】用户喜欢轻量"


def test_build_asset_parse_messages_passes_preferences():
    system, user = build_asset_parse_messages(content="x", user_preferences="pref block")
    assert system
    assert "pref block" in user


def test_ai_parse_asset_passes_preferences_to_prompt(monkeypatch):
    captured = {}

    class FakeMessage:
        def __init__(self, content):
            self.content = content

    class FakeChoice:
        def __init__(self, content):
            self.message = FakeMessage(content)

    class FakeResp:
        def __init__(self, content):
            self.choices = [FakeChoice(content)]

    class FakeCompletions:
        def __init__(self):
            self.create = lambda **kw: (captured.__setitem__("messages", kw["messages"]), FakeResp('{"title":"t","asset_kind":"idea"}'))[1]

    class FakeClient:
        def __init__(self, **kw):
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr("backend.app.api.assets.settings.LLM_API_BASE", "http://x")
    monkeypatch.setattr("backend.app.api.assets.settings.LLM_API_KEY", "k")
    monkeypatch.setattr("backend.app.api.assets.OpenAI", FakeClient)

    import backend.app.api.assets as assets
    result = assets._ai_parse_asset(content="c", user_preferences="PREF_CTX")
    assert result is not None
    user_msg = captured["messages"][1]["content"]
    assert "PREF_CTX" in user_msg
