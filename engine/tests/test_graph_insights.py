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


from engine.app.graph.insights import graph_insights_context


class _FakeGraph:
    def __init__(self, communities, surprising, gods_in_comm):
        self._communities = communities; self._surprising = surprising; self._gods_in_comm = gods_in_comm
    def entity_community(self, entity_id):
        return self._communities.get(entity_id)
    def surprising_endpoints(self, entity_id):
        return self._surprising.get(entity_id, [])
    def god_neighbors(self, entity_id, limit=10):
        return []  # not used here


def _db_with(entities, community_rows, summary_questions):
    from backend.app.database import Base, engine as _engine
    from backend.app.models import KnowledgeEntity, EntityAlias, GraphCommunity, GraphInsightSummary
    from sqlalchemy.orm import sessionmaker
    Base.metadata.drop_all(_engine)
    Base.metadata.create_all(_engine)
    db = sessionmaker(bind=_engine)()
    for eid, name in entities:
        db.add(KnowledgeEntity(id=eid, user_id="default-user", entity_type="concept", canonical_name=name, normalized_key=name, status="active"))
        db.add(EntityAlias(id="al_" + eid, entity_id=eid, alias=name, normalized_key=name))
    for cid, label in community_rows:
        db.add(GraphCommunity(id=f"gc{cid}", user_id="default-user", community_id=cid, label=label, cohesion=0.4))
    db.add(GraphInsightSummary(id="gs1", user_id="default-user", suggested_questions=summary_questions))
    db.commit()
    return db


def test_graph_insights_context_composes_block_when_seeds_hit():
    from backend.app.models import KnowledgeEntity
    db = _db_with([("e1", "混合检索")], [(0, "混合检索优化")],
                  [{"type": "god", "question": "X 真的中心吗?", "why": "w"}])
    g = _FakeGraph(communities={"e1": 0}, surprising={"e1": ["e2"]}, gods_in_comm={0: ["eGOD"]})
    # add e2 name + a god entity to db so rendering has names
    db.add(KnowledgeEntity(id="e2", user_id="default-user", entity_type="concept", canonical_name="RRF融合", normalized_key="rrf", status="active"))
    db.add(KnowledgeEntity(id="eGOD", user_id="default-user", entity_type="concept", canonical_name="枢纽概念", normalized_key="hub", status="active"))
    db.commit()
    try:
        block = graph_insights_context("混合检索和别的有什么关系", user_id="default-user", db=db, graph_client=g)
        assert "隐藏联系" in block or "surprising" in block or "RRF融合" in block
        assert "混合检索优化" in block            # community label rendered
        assert "可追问" in block or "追问" in block  # question rendered
    finally:
        db.close()


def test_graph_insights_context_empty_when_no_signal():
    assert graph_insights_context("你好", user_id="default-user", db=None, graph_client=None) == ""


def test_graph_insights_context_empty_when_seeds_miss():
    db = _db_with([("e1", "混合检索")], [(0, "主题0")], [])
    g = _FakeGraph(communities={"e1": 0}, surprising={}, gods_in_comm={})
    try:
        # query talks about something unrelated -> no seed -> ""
        assert graph_insights_context("xyzabc 不存在的概念", user_id="default-user", db=db, graph_client=g) == ""
    finally:
        db.close()


def test_graph_insights_context_disabled_returns_empty():
    db = _db_with([("e1", "混合检索")], [(0, "主题0")], [])
    g = _FakeGraph(communities={"e1": 0}, surprising={"e1": ["e2"]}, gods_in_comm={})
    try:
        assert graph_insights_context("混合检索的关系", user_id="default-user", db=db, graph_client=g, enabled=False) == ""
    finally:
        db.close()
