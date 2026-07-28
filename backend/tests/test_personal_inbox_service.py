from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError


def test_render_personal_asset_unit_markdown_includes_unit_and_source_items(db_session):
    from backend.app.models import PersonalAssetItem, PersonalAssetUnit
    from backend.app.services.personal_inbox import render_personal_asset_unit_markdown

    item = PersonalAssetItem(
        id="item-a",
        user_id="default-user",
        raw_text="raw should not appear by default",
        title="Fragment A",
        summary="Fragment summary",
        rewritten_content="Clean rewritten fragment",
        status="confirmed",
    )
    unit = PersonalAssetUnit(
        id="unit-a",
        user_id="default-user",
        title="Inbox Unit",
        summary="Unit summary",
        content="Unit content",
        tags=["tag-a"],
        source_asset_ids=["item-a"],
        status="confirmed",
    )
    db_session.add_all([item, unit])
    db_session.commit()

    markdown = render_personal_asset_unit_markdown(db_session, unit)

    assert "# Inbox Unit" in markdown
    assert "Unit summary" in markdown
    assert "Unit content" in markdown
    assert "Fragment A" in markdown
    assert "Fragment summary" in markdown
    assert "Clean rewritten fragment" in markdown
    assert "raw should not appear by default" not in markdown


def test_ensure_personal_inbox_kb_is_idempotent(db_session):
    from backend.app.services.personal_inbox import ensure_personal_inbox_kb

    first = ensure_personal_inbox_kb(db_session, tenant_id="tenant-a", owner_user_id="user-a")
    second = ensure_personal_inbox_kb(db_session, tenant_id="tenant-a", owner_user_id="user-a")

    assert first.kb_uid == second.kb_uid
    assert first.name == "个人随手记"
    assert first.system_type == "personal_inbox"
    assert first.is_system is True
    assert first.delete_disabled is True


def test_ensure_personal_inbox_kb_integrity_error_preserves_pending_work(db_session):
    from backend.app.models import KnowledgeTopic, PersonalAssetUnit
    from backend.app.services import personal_inbox

    conflicting_deleted = KnowledgeTopic(
        kb_uid=personal_inbox._personal_inbox_kb_uid("tenant-a", "user-a"),
        tenant_id="tenant-a",
        owner_user_id="user-a",
        name="Deleted Inbox",
        system_type="personal_inbox",
        deleted_at=datetime(2026, 1, 1),
    )
    db_session.add(conflicting_deleted)
    db_session.commit()

    pending_unit = PersonalAssetUnit(
        id="pending-work",
        user_id="user-a",
        title="Pending Work",
        content="Must survive nested conflict",
        status="confirmed",
    )
    db_session.add(pending_unit)

    with pytest.raises(IntegrityError):
        personal_inbox.ensure_personal_inbox_kb(
            db_session,
            tenant_id="tenant-a",
            owner_user_id="user-a",
        )

    db_session.flush()
    assert db_session.get(PersonalAssetUnit, "pending-work") is not None


def test_sync_confirmed_unit_creates_single_markdown_file(db_session, tmp_path, monkeypatch):
    from backend.app.models import KnowledgeFile, PersonalAssetUnit
    from backend.app.services import personal_inbox
    from backend.app.storage.files import LocalFileStorage

    monkeypatch.setattr(personal_inbox, "_storage", lambda: LocalFileStorage(tmp_path))
    published = []
    monkeypatch.setattr(personal_inbox, "_publish_job", lambda job_id: published.append(job_id))

    unit = PersonalAssetUnit(
        id="unit-a",
        user_id="user-a",
        title="Unit A",
        summary="Summary A",
        content="Content A",
        source_asset_ids=[],
        status="confirmed",
    )
    db_session.add(unit)
    db_session.commit()

    first = personal_inbox.sync_personal_asset_unit_to_kb(
        db_session,
        unit,
        tenant_id="tenant-a",
        owner_user_id="user-a",
    )
    second = personal_inbox.sync_personal_asset_unit_to_kb(
        db_session,
        unit,
        tenant_id="tenant-a",
        owner_user_id="user-a",
    )

    rows = db_session.query(KnowledgeFile).filter_by(source_kind="personal_asset_unit", source_id="unit-a").all()
    assert len(rows) == 1
    assert first.file_uid == second.file_uid
    assert rows[0].original_filename.endswith(".md")
    assert rows[0].mime_type == "text/markdown"
    assert rows[0].system_type == "personal_inbox"
    assert rows[0].content_text and "Content A" in rows[0].content_text
    assert published


def test_sync_unconfirmed_unit_raises_value_error_and_creates_no_file(db_session, tmp_path, monkeypatch):
    from backend.app.models import KnowledgeFile, PersonalAssetUnit
    from backend.app.services import personal_inbox
    from backend.app.storage.files import LocalFileStorage

    monkeypatch.setattr(personal_inbox, "_storage", lambda: LocalFileStorage(tmp_path))

    unit = PersonalAssetUnit(
        id="unit-draft",
        user_id="user-a",
        title="Draft Unit",
        content="Draft content",
        status="pending_review",
    )
    db_session.add(unit)
    db_session.commit()

    with pytest.raises(ValueError):
        personal_inbox.sync_personal_asset_unit_to_kb(
            db_session,
            unit,
            tenant_id="tenant-a",
            owner_user_id="user-a",
        )

    rows = db_session.query(KnowledgeFile).filter_by(source_kind="personal_asset_unit", source_id="unit-draft").all()
    assert rows == []


def test_sync_rejects_unit_owned_by_another_user(db_session, tmp_path, monkeypatch):
    from backend.app.models import KnowledgeFile, PersonalAssetUnit
    from backend.app.services import personal_inbox
    from backend.app.storage.files import LocalFileStorage

    monkeypatch.setattr(personal_inbox, "_storage", lambda: LocalFileStorage(tmp_path))

    unit = PersonalAssetUnit(
        id="unit-other-owner",
        user_id="user-b",
        title="Other Owner Unit",
        content="Other owner content",
        status="confirmed",
    )
    db_session.add(unit)
    db_session.commit()

    with pytest.raises(ValueError):
        personal_inbox.sync_personal_asset_unit_to_kb(
            db_session,
            unit,
            tenant_id="tenant-a",
            owner_user_id="user-a",
        )

    rows = db_session.query(KnowledgeFile).filter_by(source_kind="personal_asset_unit").all()
    assert rows == []


def test_sync_update_commit_failure_preserves_previous_storage(db_session, tmp_path, monkeypatch):
    from backend.app.models import PersonalAssetUnit
    from backend.app.services import personal_inbox
    from backend.app.storage.files import LocalFileStorage

    storage = LocalFileStorage(tmp_path)
    monkeypatch.setattr(personal_inbox, "_storage", lambda: storage)
    monkeypatch.setattr(personal_inbox, "_publish_job", lambda job_id: None)

    unit = PersonalAssetUnit(
        id="unit-storage-safe",
        user_id="user-a",
        title="Storage Safe",
        content="Old content",
        status="confirmed",
    )
    db_session.add(unit)
    db_session.commit()
    file_row = personal_inbox.sync_personal_asset_unit_to_kb(
        db_session,
        unit,
        tenant_id="tenant-a",
        owner_user_id="user-a",
        publish=False,
    )
    old_storage_uri = file_row.storage_uri
    assert old_storage_uri
    assert b"Old content" in storage.read_bytes(old_storage_uri)

    unit.content = "New content"
    db_session.commit()
    real_commit = db_session.commit

    def fail_next_commit():
        raise RuntimeError("simulated commit failure")

    monkeypatch.setattr(db_session, "commit", fail_next_commit)
    with pytest.raises(RuntimeError, match="simulated commit failure"):
        personal_inbox.sync_personal_asset_unit_to_kb(
            db_session,
            unit,
            tenant_id="tenant-a",
            owner_user_id="user-a",
            publish=False,
        )

    monkeypatch.setattr(db_session, "commit", real_commit)
    assert storage.exists(old_storage_uri)
    assert b"Old content" in storage.read_bytes(old_storage_uri)


def test_backfill_personal_inbox_syncs_confirmed_units_only(db_session, tmp_path, monkeypatch):
    from backend.app.models import KnowledgeFile, PersonalAssetUnit
    from backend.app.services import personal_inbox
    from backend.app.storage.files import LocalFileStorage

    monkeypatch.setattr(personal_inbox, "_storage", lambda: LocalFileStorage(tmp_path))
    monkeypatch.setattr(personal_inbox, "_publish_job", lambda job_id: None)

    confirmed = PersonalAssetUnit(
        id="unit-confirmed",
        user_id="user-a",
        title="Confirmed Unit",
        content="Confirmed content",
        status="confirmed",
    )
    draft = PersonalAssetUnit(
        id="unit-draft",
        user_id="user-a",
        title="Draft Unit",
        content="Draft content",
        status="pending_review",
    )
    other_user = PersonalAssetUnit(
        id="unit-other",
        user_id="user-b",
        title="Other Unit",
        content="Other content",
        status="confirmed",
    )
    db_session.add_all([confirmed, draft, other_user])
    db_session.commit()

    count = personal_inbox.backfill_personal_inbox(
        db_session,
        tenant_id="tenant-a",
        owner_user_id="user-a",
    )

    rows = db_session.query(KnowledgeFile).filter_by(source_kind="personal_asset_unit").all()
    assert count == 1
    assert [row.source_id for row in rows] == ["unit-confirmed"]
