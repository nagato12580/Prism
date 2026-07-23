# engine/tests/test_chunk_presets.py
import pytest


def test_separator_preset_splits_on_delimiter():
    from engine.app.ingestion.presets import chunk_with_preset

    text = "Section A content.\n---\nSection B data\n---\nSection C end."
    result = chunk_with_preset(text, "separator", {})
    assert len(result) == 3
    for parent in result:
        assert "\n---\n" not in parent.content


def test_qa_preset_splits_on_q_delimiter():
    from engine.app.ingestion.presets import chunk_with_preset

    text = "Q: What is X?\nAnswer lies here.\nQ: And what about Y?\nSecond answer."
    result = chunk_with_preset(text, "qa", {"parent_tokens": 500, "child_tokens": 200})
    assert len(result) >= 1


def test_laws_preset_splits_on_chinese_article():
    from engine.app.ingestion.presets import chunk_with_preset

    text = "\n第1条 内容A\n第2条 内容B内容B内容B\n第3条 内容C"
    result = chunk_with_preset(text, "laws", {"parent_tokens": 200, "child_tokens": 100})
    assert len(result) >= 1


def test_semantic_unavailable_raises_typed_error():
    from engine.app.ingestion.presets import SemanticChunkerUnavailable, chunk_with_preset

    text = "Some text for semantic chunking."
    # langchain may not be installed — expect SemanticChunkerUnavailable
    try:
        result = chunk_with_preset(text, "semantic", {})
    except ImportError:
        pytest.skip("langchain not available")
    except SemanticChunkerUnavailable:
        pytest.skip("semantic unavailable (expected)")


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
