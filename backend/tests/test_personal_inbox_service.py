import pytest


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
