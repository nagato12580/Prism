import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database import Base
from backend.app.models import PersonalAssetItem
from engine.app.agent.tools.base import ToolContext, build_enabled_tools
import engine.app.agent.tools.assets as asset_tools
import engine.app.agent.tools.knowledge  # noqa: F401
import engine.app.agent.tools.memory  # noqa: F401
import engine.app.agent.tools.clarify  # noqa: F401
import engine.app.agent.tools.datetime  # noqa: F401
import engine.app.agent.tools.web_search  # noqa: F401


def _session_factory():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    Session().close()
    return Session


def _capture_tool():
    ctx = ToolContext(citations=[], stats_holder={})
    return next(t for t in build_enabled_tools(ctx) if t.name == "capture_thought")


def test_capture_thought_creates_pending_review_item(monkeypatch):
    Session = _session_factory()
    monkeypatch.setattr(asset_tools, "_Session", Session)
    monkeypatch.setattr(asset_tools, "_normalize_capture_with_llm", lambda text, title="": None)

    payload = json.loads(_capture_tool().invoke({"text": "下周给季度评审准备自动化测试复盘。", "title": None}))

    assert payload["status"] == "ok"
    assert payload["item_id"]
    assert payload["llm_normalized"] is False
    row = Session().query(PersonalAssetItem).filter_by(id=payload["item_id"]).one()
    assert row.status == "pending_review"
    assert row.source_type == "chat"
    assert row.raw_metadata == {"entrypoint": "chat_capture"}


def test_capture_thought_normalizes_to_markdown(monkeypatch):
    Session = _session_factory()
    monkeypatch.setattr(asset_tools, "_Session", Session)

    def fake_normalize(text, title=""):
        return {
            "title": "季度评审准备",
            "asset_kind": "task",
            "summary": "下周一需要给季度评审准备自动化测试复盘。",
            "category": "工作待办",
            "tags": ["自动化测试", "季度评审"],
            "rewritten_content": "## 待办\n\n- [ ] 准备季度评审的自动化测试复盘",
        }

    monkeypatch.setattr(asset_tools, "_normalize_capture_with_llm", fake_normalize)

    payload = json.loads(_capture_tool().invoke({"text": "下周一要给季度评审准备自动化测试复盘", "title": None}))

    assert payload["status"] == "ok"
    assert payload["llm_normalized"] is True
    row = Session().query(PersonalAssetItem).filter_by(id=payload["item_id"]).one()
    assert row.title == "季度评审准备"
    assert row.asset_kind == "task"
    assert row.rewritten_content == "## 待办\n\n- [ ] 准备季度评审的自动化测试复盘"


def test_capture_thought_empty_text_returns_error(monkeypatch):
    Session = _session_factory()
    monkeypatch.setattr(asset_tools, "_Session", Session)

    payload = json.loads(_capture_tool().invoke({"text": "   ", "title": None}))

    assert payload["status"] == "error"
