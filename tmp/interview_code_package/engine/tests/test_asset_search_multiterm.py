import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database import Base
from backend.app.models import PersonalAssetItem
from engine.app.agent.rag.agentic import AgenticRagResult
from engine.app.agent.tools.base import ToolContext, build_enabled_tools
import engine.app.agent.tools.assets as asset_tools
import engine.app.agent.tools.knowledge  # noqa: F401
import engine.app.agent.tools.memory  # noqa: F401
import engine.app.agent.tools.clarify  # noqa: F401
import engine.app.agent.tools.datetime  # noqa: F401
import engine.app.agent.tools.web_search  # noqa: F401


class FakeRagRunner:
    def run(self, query: str):
        return AgenticRagResult(
            status="sufficient",
            summary=f"evidence for {query}",
            evidence=[],
            sources=[],
            iterations=1,
        )


def test_asset_search_uses_multi_term_recall_and_explains_matches(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add(
        PersonalAssetItem(
            raw_text="Use AI to generate Playwright UI automation tests when prompts include page state.",
            title="Playwright prompt notes",
            body="Use AI to generate UI automation assertions and improve locator prompts.",
            summary="Prompt optimization for UI automation.",
            asset_kind="note",
            category="Testing",
            tags=["AI", "UI", "automation", "prompt"],
            user_id="default-user",
            status="confirmed",
        )
    )
    session.commit()
    session.close()
    monkeypatch.setattr(asset_tools, "_Session", Session)

    ctx = ToolContext(rag_runner=FakeRagRunner(), citations=[], stats_holder={})
    tool = next(t for t in build_enabled_tools(ctx) if t.name == "asset_search")

    payload = json.loads(tool.invoke({"query": "AI辅助UI自动化测试方案与提示词优化经验", "limit": 5}))

    assert payload["status"] == "success"
    assert payload["query_terms"]
    assert payload["assets"][0]["title"] == "Playwright prompt notes"
    assert {"ai", "ui"}.issubset(set(payload["assets"][0]["matched_terms"]))
    assert payload["assets"][0]["match_reasons"]
    assert ctx.stats_holder["asset_search"]["query_terms"] == payload["query_terms"]
