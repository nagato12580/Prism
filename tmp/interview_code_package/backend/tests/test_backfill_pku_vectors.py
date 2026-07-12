def _pku(**overrides):
    from backend.app.models import PersonalKnowledgeUnit

    data = {
        "user_id": "user-1",
        "source_kind": "document_chunk",
        "source_id": "chunk-1",
        "unit_type": "claim",
        "statement": "Metadata filters narrow retrieval candidates.",
        "normalized_statement": "metadata filters narrow retrieval candidates",
        "normalized_statement_hash": overrides.pop("normalized_statement_hash", "hash-1"),
        "evidence_span": "Metadata filters narrow retrieval candidates.",
        "status": "active",
        "embedding_status": "pending",
        "embedding_ref": "",
    }
    data.update(overrides)
    return PersonalKnowledgeUnit(**data)


def test_backfill_pku_vectors_updates_active_pending_pkus(db_session, monkeypatch):
    from backend.scripts import backfill_pku_vectors as script

    pending = _pku(normalized_statement_hash="pending")
    deprecated = _pku(normalized_statement_hash="deprecated", status="deprecated")
    done = _pku(normalized_statement_hash="done", embedding_status="done", embedding_ref="pku-existing")
    db_session.add_all([pending, deprecated, done])
    db_session.commit()

    monkeypatch.setattr(script, "upsert_pku_vector", lambda pku: f"pku:{pku.id}")

    stats = script.backfill_pku_vectors(db_session, user_id="user-1")

    assert stats == {"scanned": 2, "updated": 1, "skipped": 1, "failed": 0}
    assert pending.embedding_ref == f"pku:{pending.id}"
    assert pending.embedding_model == script.settings.EMBEDDING_MODEL
    assert pending.embedding_status == "done"
    assert deprecated.embedding_status == "pending"
    assert done.embedding_ref == "pku-existing"


def test_backfill_pku_vectors_force_refreshes_done_pkus(db_session, monkeypatch):
    from backend.scripts import backfill_pku_vectors as script

    done = _pku(normalized_statement_hash="done-force", embedding_status="done", embedding_ref="pku-existing")
    db_session.add(done)
    db_session.commit()

    monkeypatch.setattr(script, "upsert_pku_vector", lambda pku: f"pku-refreshed:{pku.id}")

    stats = script.backfill_pku_vectors(db_session, user_id="user-1", force=True)

    assert stats == {"scanned": 1, "updated": 1, "skipped": 0, "failed": 0}
    assert done.embedding_ref == f"pku-refreshed:{done.id}"
    assert done.embedding_status == "done"


def test_backfill_pku_vectors_marks_failed_when_upsert_raises(db_session, monkeypatch):
    from backend.scripts import backfill_pku_vectors as script

    pending = _pku(normalized_statement_hash="failed")
    db_session.add(pending)
    db_session.commit()

    def fail(_pku):
        raise RuntimeError("embedding service unavailable")

    monkeypatch.setattr(script, "upsert_pku_vector", fail)

    stats = script.backfill_pku_vectors(db_session, user_id="user-1")

    assert stats == {"scanned": 1, "updated": 0, "skipped": 0, "failed": 1}
    assert pending.embedding_status == "failed"
