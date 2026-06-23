from engine.app.agent.active_recall import has_recall_signal, recall_memory_context


def test_has_recall_signal_detects_first_person():
    assert has_recall_signal("我之前偏好轻量方案")
    assert has_recall_signal("我喜欢深色主题")
    assert has_recall_signal("记得我说过的目标吗")


def test_has_recall_signal_detects_preference_words():
    assert has_recall_signal("这个项目的目标是什么")
    assert has_recall_signal("用户偏好简短回答")


def test_has_recall_signal_skips_non_personal_queries():
    assert not has_recall_signal("什么是 RAG")
    assert not has_recall_signal("解释一下向量数据库")
    assert not has_recall_signal("")
    assert not has_recall_signal("hi")


def test_recall_returns_empty_when_no_signal():
    assert recall_memory_context("什么是知识图谱") == ""


def test_recall_returns_empty_when_no_vector_hits(monkeypatch):
    monkeypatch.setattr("engine.app.agent.active_recall.search_memory_vectors", lambda **kw: [])
    assert recall_memory_context("我之前偏好什么") == ""


def test_recall_filters_low_score_and_builds_block(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from backend.app.database import Base
    from backend.app.models import MemoryEntry, MemoryStatement
    from backend.app.models.memory import MemoryStatus

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    entry = MemoryEntry(
        id="e1",
        user_id="default-user",
        title="偏好深色主题",
        content="用户偏好深色主题阅读。",
        memory_type="preference",
        importance=0.8,
    )
    stmt = MemoryStatement(
        id="s1",
        user_id="default-user",
        content="用户每天早上复习知识。",
        statement_type="habit",
        status=MemoryStatus.CONFIRMED,
        importance=0.7,
    )
    session.add_all([entry, stmt])
    session.commit()
    entry_id, stmt_id = entry.id, stmt.id
    session.close()

    import engine.app.agent.active_recall as ar
    ar._Session = Session

    def fake_vector_search(*, text, user_id, top_k):
        return [
            {"memory_id": entry_id, "kind": "entry", "memory_type": "preference", "score": 0.82},
            {"memory_id": stmt_id, "kind": "statement", "memory_type": "habit", "score": 0.20},
        ]

    monkeypatch.setattr(ar, "search_memory_vectors", fake_vector_search)

    block = recall_memory_context("我偏好什么主题", min_score=0.5)

    assert "深色主题" in block
    assert "复习知识" not in block
    assert block.startswith("【关于用户的已知记忆")


def test_recall_skips_non_confirmed_statements(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from backend.app.database import Base
    from backend.app.models import MemoryStatement
    from backend.app.models.memory import MemoryStatus

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    draft_stmt = MemoryStatement(
        id="s-draft",
        user_id="default-user",
        content="草稿未确认记忆",
        statement_type="fact",
        status=MemoryStatus.DRAFT,
    )
    session.add(draft_stmt)
    session.commit()
    draft_id = draft_stmt.id
    session.close()

    import engine.app.agent.active_recall as ar
    ar._Session = Session

    def fake_vector_search(*, text, user_id, top_k):
        return [{"memory_id": draft_id, "kind": "statement", "memory_type": "fact", "score": 0.9}]

    monkeypatch.setattr(ar, "search_memory_vectors", fake_vector_search)

    assert recall_memory_context("我记得什么") == ""


def test_recall_returns_empty_on_vector_exception(monkeypatch):
    import engine.app.agent.active_recall as ar

    def boom(**kw):
        raise RuntimeError("milvus down")

    monkeypatch.setattr(ar, "search_memory_vectors", boom)
    assert recall_memory_context("我之前的目标") == ""


def test_recall_respects_timeout(monkeypatch):
    import time
    import engine.app.agent.active_recall as ar

    def slow_search(**kw):
        time.sleep(0.4)
        return [{"memory_id": "x", "kind": "entry", "memory_type": "p", "score": 0.9}]

    monkeypatch.setattr(ar, "search_memory_vectors", slow_search)
    assert recall_memory_context("我偏好", timeout_seconds=0.1) == ""
