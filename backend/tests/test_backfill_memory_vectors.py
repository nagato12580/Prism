from backend.app.models.memory import MemoryEntry, MemoryStatement, MemoryStatus


def _run(db_session, monkeypatch, **kwargs):
    from backend.scripts import backfill_memory_vectors as bf
    monkeypatch.setattr(bf, "upsert_entry_vector", kwargs.get("upsert_entry", lambda e: "memory-e"))
    monkeypatch.setattr(bf, "upsert_statement_vector", kwargs.get("upsert_stmt", lambda s: "memory-s"))
    return bf, bf.backfill_memory_vectors(db_session, limit=10, **{k: v for k, v in kwargs.items() if k in ("force", "user_id")})


def test_backfill_marks_pending_entries_done(db_session, monkeypatch):
    entry = MemoryEntry(
        id="e1",
        user_id="default-user",
        title="偏好深色主题",
        content="用户偏好深色主题阅读。",
        memory_type="preference",
        embedding_status="pending",
    )
    db_session.add(entry)
    db_session.commit()

    bf, stats = _run(db_session, monkeypatch, upsert_entry=lambda e: "memory-new-e1", upsert_stmt=lambda s: "memory-new-s1")

    assert stats["scanned"] == 1
    assert stats["updated"] == 1
    db_session.refresh(entry)
    assert entry.embedding_ref == "memory-new-e1"
    assert entry.embedding_status == "done"
    assert entry.embedding_model == bf.settings.EMBEDDING_MODEL


def test_backfill_skips_done_entries_and_statements(db_session, monkeypatch):
    entry = MemoryEntry(
        id="e-done",
        user_id="default-user",
        title="done entry",
        content="c",
        embedding_status="done",
        embedding_ref="existing",
    )
    statement = MemoryStatement(
        id="s-done",
        user_id="default-user",
        content="done statement",
        statement_type="fact",
        status=MemoryStatus.CONFIRMED,
        embedding_status="done",
        embedding_ref="existing-s",
    )
    db_session.add_all([entry, statement])
    db_session.commit()

    called = {"entry": 0, "statement": 0}
    bf, stats = _run(
        db_session, monkeypatch,
        upsert_entry=lambda e: (called.__setitem__("entry", called["entry"] + 1), "x")[1],
        upsert_stmt=lambda s: (called.__setitem__("statement", called["statement"] + 1), "x")[1],
    )

    assert stats["scanned"] == 2
    assert stats["skipped"] == 2
    assert stats["updated"] == 0
    assert called["entry"] == 0
    assert called["statement"] == 0


def test_backfill_force_re_embeds_done(db_session, monkeypatch):
    entry = MemoryEntry(
        id="e-force",
        user_id="default-user",
        title="force",
        content="c",
        embedding_status="done",
        embedding_ref="old-ref",
    )
    db_session.add(entry)
    db_session.commit()

    bf, stats = _run(db_session, monkeypatch, force=True, upsert_entry=lambda e: "memory-refreshed")

    assert stats["updated"] == 1
    db_session.refresh(entry)
    assert entry.embedding_ref == "memory-refreshed"


def test_backfill_skips_non_confirmed_statements(db_session, monkeypatch):
    draft_stmt = MemoryStatement(
        id="s-draft",
        user_id="default-user",
        content="draft statement",
        statement_type="fact",
        status=MemoryStatus.DRAFT,
        embedding_status="pending",
    )
    db_session.add(draft_stmt)
    db_session.commit()

    bf, stats = _run(db_session, monkeypatch, upsert_entry=lambda e: "x", upsert_stmt=lambda s: "memory-s")

    assert stats["scanned"] == 0
    assert stats["updated"] == 0


def test_backfill_records_failed_on_exception(db_session, monkeypatch):
    entry = MemoryEntry(
        id="e-fail",
        user_id="default-user",
        title="fail",
        content="c",
        embedding_status="pending",
    )
    db_session.add(entry)
    db_session.commit()

    def raise_(e):
        raise RuntimeError("embed service down")

    bf, stats = _run(db_session, monkeypatch, upsert_entry=raise_, upsert_stmt=lambda s: "x")

    assert stats["failed"] == 1
    db_session.refresh(entry)
    assert entry.embedding_status == "failed"
