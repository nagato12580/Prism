# engine/tests/test_chunk_presets.py
import pytest


def test_separator_preset_splits_on_delimiter():
    from engine.app.ingestion.presets import chunk_with_preset

    text = "Section A\n---\nSection B\n---\nSection C"
    result = chunk_with_preset(text, "separator", {})
    assert len(result) == 3
    for parent in result:
        assert "\n---\n" not in parent.content


def test_qa_preset_splits_on_q_delimiter():
    from engine.app.ingestion.presets import chunk_with_preset

    text = "Q: What is X?\nAnswer.\nQ: And Y?\nSecond answer."
    result = chunk_with_preset(text, "qa", {"parent_tokens": 500, "child_tokens": 200})
    assert len(result) >= 1


# Real Chinese legal text for laws preset testing.
_LEGAL_TEXT = (
    "第一章 总则\n"
    "第1条 为了规范市场秩序，保护消费者合法权益，根据有关法律，制定本法。"
    "市场交易应当遵循自愿、平等、公平、诚实信用的原则。\n"
    "第2条 本法适用于中华人民共和国境内从事市场交易的经营者。"
    "经营者是指在市场中从事商品经营或者营利性服务的个人和组织。\n"
    "第3条 国家实行统一的市场监管制度，保障市场的公平竞争。"
    "各级人民政府应当加强对市场监管工作的领导。\n"
    "第二章 市场交易规则\n"
    "第4条 经营者应当依法取得营业执照，并在核准的范围内从事经营活动。"
    "未经登记，不得从事经营活动。\n"
    "第5条 经营者销售商品或者提供服务，应当明码标价，不得有价格欺诈行为。"
)


def test_laws_preset_splits_on_chinese_article():
    from engine.app.ingestion.presets import chunk_with_preset

    result = chunk_with_preset(
        _LEGAL_TEXT,
        "laws",
        {"parent_tokens": 300, "child_tokens": 100},
    )
    # With "\n第" separator, the text should be split into multiple sections.
    assert len(result) >= 3
    # Each parent chunk should NOT contain "\n第" (already split on it).
    for parent in result:
        assert "\n第" not in parent.content


def test_semantic_calls_injected_splitter(monkeypatch):
    """Inject a fake splitter and verify it is called with the correct text."""
    from engine.app.ingestion import presets as presets_module
    from engine.app.ingestion.chunker import ParentChunk

    call_records = []

    class FakeSplitter:
        def __init__(self, chunk_size=1000, chunk_overlap=0, separators=None):
            pass
        def create_documents(self, texts):
            call_records.append(texts)
            return [type("FakeDoc", (), {"page_content": text}) for text in texts]

    class FakeModule:
        RecursiveCharacterTextSplitter = FakeSplitter

    # Inject fake langchain_text_splitter module
    import sys
    sys.modules["langchain.text_splitter"] = FakeModule
    monkeypatch.setattr(
        presets_module, "__name__", presets_module.__name__
    )
    # Force reimport of langchain inside presets
    monkeypatch.setitem(
        sys.modules,
        "langchain.text_splitter",
        FakeModule,
    )

    from engine.app.ingestion.presets import chunk_with_preset

    text = "Paragraph one.\n\nParagraph two.\n\nParagraph three."
    result = chunk_with_preset(text, "semantic", {"parent_tokens": 500, "child_tokens": 200})

    assert len(call_records) >= 1
    assert call_records[0][0] == text
    assert len(result) >= 1
    assert all(len(p.children) > 0 for p in result)

    del sys.modules["langchain.text_splitter"]


def test_semantic_unavailable_raises_typed_error(monkeypatch):
    """When langchain is not importable, SemanticChunkerUnavailable is raised."""
    import sys

    # Remove langchain modules to simulate unavailability
    saved = {k: sys.modules.pop(k, None) for k in list(sys.modules) if "langchain" in k}

    try:
        from engine.app.ingestion.presets import SemanticChunkerUnavailable, chunk_with_preset

        with pytest.raises(SemanticChunkerUnavailable):
            chunk_with_preset("text", "semantic", {})
    finally:
        for k, v in saved.items():
            if v is not None:
                sys.modules[k] = v


def test_chunk_config_snapshot_is_deterministic():
    from engine.app.ingestion.presets import chunk_config_snapshot

    s1 = chunk_config_snapshot("general")
    s2 = chunk_config_snapshot("general")
    assert s1 == s2
    assert s1.parent_tokens == 1200
    assert s1.preset_id == "general"

    s3 = chunk_config_snapshot("separator")
    assert s3.separator == "\n---\n"

    s4 = chunk_config_snapshot("general", {"parent_tokens": 800})
    assert s4.parent_tokens == 800
    assert s4.preset_id == "general"


def test_preset_overrides_not_affect_stored_preset():
    from engine.app.ingestion.presets import PRESETS, chunk_config_snapshot

    original = PRESETS["general"].parent_tokens
    chunk_config_snapshot("general", {"parent_tokens": 500})
    assert PRESETS["general"].parent_tokens == original


def test_invalid_override_keys_raise_value_error():
    from engine.app.ingestion.presets import chunk_with_preset

    with pytest.raises(ValueError):
        chunk_with_preset("text", "general", {"bad_key": 100})


def test_negative_override_values_raise_value_error():
    from engine.app.ingestion.presets import chunk_with_preset

    with pytest.raises(ValueError):
        chunk_with_preset("text", "general", {"parent_tokens": -1})


def test_snapshot_is_serializable():
    from engine.app.ingestion.presets import chunk_config_snapshot

    snap = chunk_config_snapshot("qa")
    d = snap.to_dict()
    assert d["preset_id"] == "qa"
    assert d["parent_tokens"] == 900
    assert d["separator"] == "\nQ:"
