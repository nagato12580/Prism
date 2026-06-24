from backend.app.models.memory import MemoryEntry, MemoryInsight, MemoryStatement
from backend.app.models.memory import MemoryStatus
from backend.app.services import memory_reflection


def _fake_llm(insights):
    def _call(block):
        return insights
    return _call


def _seed(db_session, n=5):
    for i in range(n):
        db_session.add(MemoryEntry(
            id=f"e{i}",
            user_id="default-user",
            title=f"偏好{i}",
            content=f"用户偏好轻量方案{i}的细节描述",
            memory_type="preference",
            importance=0.7,
        ))
    db_session.commit()


def test_reflection_creates_insights(db_session, monkeypatch):
    _seed(db_session, 5)
    monkeypatch.setattr(memory_reflection, "_call_reflection_llm", _fake_llm([
        {"theme": "技术偏好", "content": "用户偏好轻量、低依赖的方案。", "importance": 0.8},
        {"theme": "学习习惯", "content": "用户倾向先理解原理再动手。", "importance": 0.7},
    ]))

    result = memory_reflection.run_reflection(db_session)

    assert result["insights"] == 2
    insights = db_session.query(MemoryInsight).all()
    assert len(insights) == 2
    themes = {i.theme for i in insights}
    assert themes == {"技术偏好", "学习习惯"}
    assert all(i.status == "confirmed" for i in insights)


def test_reflection_upserts_by_theme(db_session, monkeypatch):
    _seed(db_session, 5)
    db_session.add(MemoryInsight(
        id="old-i",
        user_id="default-user",
        theme="技术偏好",
        content="旧洞察。",
        importance=0.5,
        status="confirmed",
    ))
    db_session.commit()

    monkeypatch.setattr(memory_reflection, "_call_reflection_llm", _fake_llm([
        {"theme": "技术偏好", "content": "更新后的洞察。", "importance": 0.9},
    ]))

    memory_reflection.run_reflection(db_session)

    insights = db_session.query(MemoryInsight).filter(MemoryInsight.theme == "技术偏好").all()
    assert len(insights) == 1
    assert insights[0].content == "更新后的洞察。"
    assert insights[0].importance == 0.9


def test_reflection_skips_too_few_memories(db_session, monkeypatch):
    _seed(db_session, 2)
    monkeypatch.setattr(memory_reflection, "_call_reflection_llm", _fake_llm([]))

    result = memory_reflection.run_reflection(db_session)
    assert result["skipped"] == "too_few_memories"
    assert result["insights"] == 0


def test_reflection_skips_when_llm_empty(db_session, monkeypatch):
    _seed(db_session, 5)
    monkeypatch.setattr(memory_reflection, "_call_reflection_llm", _fake_llm([]))

    result = memory_reflection.run_reflection(db_session)
    assert result["skipped"] == "no_llm_or_empty"


def test_reflection_skips_on_llm_exception(db_session, monkeypatch):
    _seed(db_session, 5)
    def boom(block):
        raise RuntimeError("llm down")
    monkeypatch.setattr(memory_reflection, "_call_reflection_llm", boom)

    result = memory_reflection.run_reflection(db_session)
    assert result["skipped"] == "no_llm_or_empty"


def test_reflection_includes_confirmed_statements(db_session, monkeypatch):
    _seed(db_session, 3)
    db_session.add(MemoryStatement(
        id="s1",
        user_id="default-user",
        content="用户每天早上复习知识。",
        statement_type="habit",
        status=MemoryStatus.CONFIRMED,
        importance=0.8,
    ))
    db_session.add(MemoryStatement(
        id="s2",
        user_id="default-user",
        content="草稿未确认。",
        statement_type="fact",
        status=MemoryStatus.DRAFT,
    ))
    db_session.commit()

    captured = {}
    def capture_llm(block):
        captured["block"] = block
        return [{"theme": "习惯", "content": "用户有稳定的复习习惯。", "importance": 0.7}]

    monkeypatch.setattr(memory_reflection, "_call_reflection_llm", capture_llm)
    memory_reflection.run_reflection(db_session)

    assert "复习知识" in captured["block"]
    assert "草稿未确认" not in captured["block"]


def test_list_insights_returns_confirmed_ordered(db_session):
    db_session.add_all([
        MemoryInsight(id="i1", user_id="default-user", theme="A", content="a", importance=0.9, status="confirmed"),
        MemoryInsight(id="i2", user_id="default-user", theme="B", content="b", importance=0.7, status="confirmed"),
        MemoryInsight(id="i3", user_id="default-user", theme="C", content="c", importance=0.5, status="draft"),
    ])
    db_session.commit()

    insights = memory_reflection.list_insights(db_session)
    assert [i.theme for i in insights] == ["A", "B"]
