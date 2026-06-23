from backend.app.models.memory import MemoryEntry, MemoryStatement
from backend.app.models.memory import MemoryStatus
from backend.app.services import memory_context


def test_recall_returns_empty_when_no_hits(db_session, monkeypatch):
    monkeypatch.setattr(memory_context, "search_memory_vectors", lambda **kw: [])
    assert memory_context.recall_preference_context(db_session, "some content") == ""


def test_recall_returns_empty_when_embedding_not_configured(db_session, monkeypatch):
    monkeypatch.setattr(memory_context.settings, "EMBEDDING_API_BASE", "")
    monkeypatch.setattr(memory_context.settings, "EMBEDDING_API_KEY", "")
    assert memory_context.recall_preference_context(db_session, "content") == ""


def test_recall_builds_block_from_preference_entries(db_session, monkeypatch):
    entry = MemoryEntry(
        id="e1",
        user_id="default-user",
        title="偏好轻量方案",
        content="用户希望 Prism 第一版先轻量实现。",
        memory_type="preference",
        importance=0.8,
    )
    db_session.add(entry)
    db_session.commit()

    def fake_search(**kw):
        return [{"memory_id": entry.id, "kind": "entry", "memory_type": "preference", "score": 0.82}]

    monkeypatch.setattr(memory_context, "search_memory_vectors", fake_search)

    block = memory_context.recall_preference_context(db_session, "做一个新功能方案")

    assert "轻量方案" in block
    assert block.startswith("【用户长期偏好")


def test_recall_filters_non_preference_types(db_session, monkeypatch):
    entry_pref = MemoryEntry(
        id="ep",
        user_id="default-user",
        title="偏好深色",
        content="用户偏好深色主题。",
        memory_type="preference",
    )
    entry_fact = MemoryEntry(
        id="ef",
        user_id="default-user",
        title="事实记忆",
        content="用户用过 React。",
        memory_type="fact",
    )
    db_session.add_all([entry_pref, entry_fact])
    db_session.commit()

    def fake_search(**kw):
        return [
            {"memory_id": "ef", "kind": "entry", "memory_type": "fact", "score": 0.9},
            {"memory_id": "ep", "kind": "entry", "memory_type": "preference", "score": 0.7},
        ]

    monkeypatch.setattr(memory_context, "search_memory_vectors", fake_search)

    block = memory_context.recall_preference_context(db_session, "主题设计")

    assert "深色" in block
    assert "React" not in block


def test_recall_filters_low_score(db_session, monkeypatch):
    entry = MemoryEntry(
        id="e1",
        user_id="default-user",
        title="偏好",
        content="用户偏好X。",
        memory_type="preference",
    )
    db_session.add(entry)
    db_session.commit()

    def fake_search(**kw):
        return [{"memory_id": entry.id, "kind": "entry", "memory_type": "preference", "score": 0.20}]

    monkeypatch.setattr(memory_context, "search_memory_vectors", fake_search)

    assert memory_context.recall_preference_context(db_session, "x", min_score=0.5) == ""


def test_recall_filters_non_confirmed_statements(db_session, monkeypatch):
    draft_stmt = MemoryStatement(
        id="sd",
        user_id="default-user",
        content="草稿偏好",
        statement_type="preference",
        status=MemoryStatus.DRAFT,
    )
    db_session.add(draft_stmt)
    db_session.commit()

    def fake_search(**kw):
        return [{"memory_id": draft_stmt.id, "kind": "statement", "memory_type": "preference", "score": 0.9}]

    monkeypatch.setattr(memory_context, "search_memory_vectors", fake_search)

    assert memory_context.recall_preference_context(db_session, "偏好") == ""


def test_recall_returns_empty_on_vector_exception(db_session, monkeypatch):
    def boom(**kw):
        raise RuntimeError("milvus down")

    monkeypatch.setattr(memory_context, "search_memory_vectors", boom)
    assert memory_context.recall_preference_context(db_session, "content") == ""
