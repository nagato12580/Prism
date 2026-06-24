from backend.app.models.memory import MemoryEntry, MemoryStatement
from backend.app.models.memory import MemoryStatus
from backend.app.services import memory_access, memory_consolidation


def test_bump_memory_access_increments_entries_and_statements(db_session):
    entry = MemoryEntry(id="e1", user_id="default-user", title="t", content="c", importance=0.5)
    stmt = MemoryStatement(
        id="s1",
        user_id="default-user",
        content="用户偏好X。",
        statement_type="preference",
        status=MemoryStatus.CONFIRMED,
        importance=0.5,
    )
    db_session.add_all([entry, stmt])
    db_session.commit()

    updated = memory_access.bump_memory_access(db_session, memory_ids=[("e1", "entry"), ("s1", "statement")])

    assert updated == 2
    db_session.refresh(entry)
    db_session.refresh(stmt)
    assert entry.access_count == 1
    assert entry.last_accessed_at is not None
    assert stmt.access_count == 1


def test_bump_memory_access_accumulates(db_session):
    entry = MemoryEntry(id="e1", user_id="default-user", title="t", content="c", access_count=3)
    db_session.add(entry)
    db_session.commit()

    memory_access.bump_memory_access(db_session, memory_ids=[("e1", "entry")])
    memory_access.bump_memory_access(db_session, memory_ids=[("e1", "entry")])

    db_session.refresh(entry)
    assert entry.access_count == 5


def test_bump_memory_access_skips_wrong_user(db_session):
    entry = MemoryEntry(id="e1", user_id="other-user", title="t", content="c")
    db_session.add(entry)
    db_session.commit()

    updated = memory_access.bump_memory_access(db_session, memory_ids=[("e1", "entry")])
    assert updated == 0


def test_consolidation_promotes_high_frequency_low_importance_entries(db_session):
    high_freq = MemoryEntry(
        id="e-hf",
        user_id="default-user",
        title="高频低权",
        content="被频繁召回的记忆。",
        importance=0.4,
        access_count=5,
    )
    low_freq = MemoryEntry(
        id="e-lf",
        user_id="default-user",
        title="低频",
        content="很少被召回。",
        importance=0.4,
        access_count=1,
    )
    already_high = MemoryEntry(
        id="e-ah",
        user_id="default-user",
        title="已高权",
        content="已经高重要度。",
        importance=0.9,
        access_count=10,
    )
    db_session.add_all([high_freq, low_freq, already_high])
    db_session.commit()

    result = memory_consolidation.run_consolidation(db_session)

    assert result["total_promoted"] == 1
    db_session.refresh(high_freq)
    db_session.refresh(low_freq)
    db_session.refresh(already_high)
    assert abs(float(high_freq.importance) - 0.85) < 1e-6
    assert abs(float(low_freq.importance) - 0.4) < 1e-6
    assert abs(float(already_high.importance) - 0.9) < 1e-6
    detail_entry = next(d for d in result["details"]["entries"] if d["id"] == "e-hf")
    assert detail_entry["old_importance"] == 0.4
    assert detail_entry["new_importance"] == 0.85


def test_consolidation_promotes_confirmed_statements_only(db_session):
    confirmed = MemoryStatement(
        id="s-c",
        user_id="default-user",
        content="确认的高频记忆。",
        statement_type="preference",
        status=MemoryStatus.CONFIRMED,
        importance=0.4,
        access_count=4,
    )
    draft = MemoryStatement(
        id="s-d",
        user_id="default-user",
        content="草稿高频。",
        statement_type="preference",
        status=MemoryStatus.DRAFT,
        importance=0.4,
        access_count=4,
    )
    db_session.add_all([confirmed, draft])
    db_session.commit()

    result = memory_consolidation.run_consolidation(db_session)

    assert result["promoted_statements"] == 1
    db_session.refresh(draft)
    assert abs(float(draft.importance) - 0.4) < 1e-6


def test_consolidation_preview_does_not_modify(db_session):
    entry = MemoryEntry(
        id="e1",
        user_id="default-user",
        title="t",
        content="c",
        importance=0.4,
        access_count=5,
    )
    db_session.add(entry)
    db_session.commit()

    preview = memory_consolidation.consolidation_candidates(db_session)

    assert len(preview["entries"]) == 1
    db_session.refresh(entry)
    assert abs(float(entry.importance) - 0.4) < 1e-6


def test_consolidation_respects_threshold(db_session):
    below = MemoryEntry(id="e1", user_id="default-user", title="t", content="c", importance=0.4, access_count=2)
    db_session.add(below)
    db_session.commit()

    result = memory_consolidation.run_consolidation(db_session, access_threshold=3)
    assert result["total_promoted"] == 0


def test_consolidation_caps_importance(db_session):
    entry = MemoryEntry(id="e1", user_id="default-user", title="t", content="c", importance=0.92, access_count=5)
    db_session.add(entry)
    db_session.commit()

    memory_consolidation.run_consolidation(db_session, target_importance=0.95)
    db_session.refresh(entry)
    assert float(entry.importance) <= 0.95
