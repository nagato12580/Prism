import os
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "sqlite:///./_insights_test.db"

from backend.app.database import Base, engine as _engine
from sqlalchemy.orm import sessionmaker


def _db():
    Base.metadata.create_all(_engine)
    return sessionmaker(bind=_engine)()


def test_graph_community_and_summary_tables_exist_and_writable():
    from backend.app.models import GraphCommunity, GraphInsightSummary
    db = _db()
    try:
        db.add(GraphCommunity(id="gc1", user_id="default-user", community_id=0, label="混合检索优化", cohesion=0.42))
        db.add(GraphInsightSummary(id="gs1", user_id="default-user",
                                   suggested_questions=[{"type": "god", "question": "Q?", "why": "w"}]))
        db.commit()
        assert db.query(GraphCommunity).filter_by(user_id="default-user", community_id=0).one().label == "混合检索优化"
        assert db.query(GraphInsightSummary).filter_by(user_id="default-user").one().suggested_questions[0]["question"] == "Q?"
    finally:
        db.close()


from unittest.mock import patch
from engine.app.graph.insights import has_insight_signal, generate_community_labels


def test_has_insight_signal_positive_and_negative():
    assert has_insight_signal("混合检索和重排有什么关系") is True     # "关系" triggers
    assert has_insight_signal("还有别的相关内容吗") is True          # "还有/相关" triggers
    assert has_insight_signal("你好") is False


@patch("engine.app.graph.insights.chat")
def test_generate_community_labels_uses_llm_and_returns_mapping(mock_chat):
    mock_chat.return_value = "混合检索优化"
    communities_by_cid = {0: ["混合检索", "RRF融合", "重排"]}
    labels = generate_community_labels(communities_by_cid, user_id="default-user")
    assert labels == {0: "混合检索优化"}
    assert mock_chat.call_count == 1


@patch("engine.app.graph.insights.chat")
def test_generate_community_labels_llm_failure_returns_empty(mock_chat):
    mock_chat.side_effect = RuntimeError("llm down")
    assert generate_community_labels({0: ["a", "b"]}) == {}


from engine.app.graph.insights import compute_suggested_questions


def test_compute_suggested_questions_drops_bridge_and_keeps_god_ambiguous():
    # graphify returns questions with type tags; we drop bridge_node (concept-filtered)
    fake_questions = [
        {"type": "bridge_node", "question": "Why does A connect C0 to C1?", "why": "betweenness"},
        {"type": "god", "question": "Is X really central?", "why": "high inferred degree"},
        {"type": "ambiguous_edge", "question": "Rel between P and Q?", "why": "ambiguous"},
    ]
    out = compute_suggested_questions(_graph=lambda: None, _questions_override=fake_questions, top_n=5)
    types = {q["type"] for q in out}
    assert "bridge_node" not in types
    assert {"god", "ambiguous_edge"} <= types


def test_compute_suggested_questions_returns_empty_on_failure():
    def _boom(**kw):
        raise RuntimeError("graphify")
    out = compute_suggested_questions(_questions_fn=_boom, top_n=5)
    assert out == []
