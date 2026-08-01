def test_create_asset_item_without_parsed_uses_heuristic_fallback(db_session):
    from backend.app.services.asset_items import create_asset_item_from_raw

    item = create_asset_item_from_raw(
        db_session,
        raw_text="下周要给季度评审准备一份自动化测试复盘。",
        raw_title="",
        raw_source_type="chat",
        raw_metadata={"entrypoint": "chat_capture"},
        parsed=None,
    )

    assert item.status == "pending_review"
    assert item.source_type == "chat"
    assert item.raw_metadata == {"entrypoint": "chat_capture"}
    assert item.title
    assert item.user_id == "default-user"


def test_create_asset_item_empty_content_raises_value_error(db_session):
    from backend.app.services.asset_items import create_asset_item_from_raw

    try:
        create_asset_item_from_raw(db_session, raw_text="   ")
    except ValueError:
        return
    raise AssertionError("expected ValueError for empty content")


def test_create_asset_item_uses_provided_parsed_fields(db_session):
    from backend.app.services.asset_items import create_asset_item_from_raw

    item = create_asset_item_from_raw(
        db_session,
        raw_text="some knowledge content",
        parsed={
            "title": "LLM title",
            "summary": "LLM summary",
            "asset_kind": "knowledge",
            "tags": ["tag-a"],
            "category": "分类",
            "rewritten_content": "rewritten",
            "confidence": {"overall": 0.9},
            "rationale": "ok",
        },
    )

    assert item.title == "LLM title"
    assert item.asset_kind == "knowledge"
    assert item.status == "pending_review"
    assert item.raw_metadata == {}
