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
