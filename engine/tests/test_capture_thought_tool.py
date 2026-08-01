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


def test_capture_thought_creates_pending_review_item(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    Session().close()
    monkeypatch.setattr(asset_tools, "_Session", Session)

    ctx = ToolContext(citations=[], stats_holder={})
    tool = next(t for t in build_enabled_tools(ctx) if t.name == "capture_thought")

    payload = json.loads(tool.invoke({"text": "下周给季度评审准备自动化测试复盘。", "title": None}))

    assert payload["status"] == "ok"
    assert payload["item_id"]
    row = Session().query(PersonalAssetItem).filter_by(id=payload["item_id"]).one()
    assert row.status == "pending_review"
    assert row.source_type == "chat"
    assert row.raw_metadata == {"entrypoint": "chat_capture"}


def test_capture_thought_empty_text_returns_error(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    Session().close()
    monkeypatch.setattr(asset_tools, "_Session", Session)

    ctx = ToolContext(citations=[], stats_holder={})
    tool = next(t for t in build_enabled_tools(ctx) if t.name == "capture_thought")

    payload = json.loads(tool.invoke({"text": "   ", "title": None}))

    assert payload["status"] == "error"
