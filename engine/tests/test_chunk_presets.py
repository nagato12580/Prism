# engine/tests/test_chunk_presets.py
import pytest


@pytest.mark.parametrize("preset_id", ["general", "qa", "book", "laws", "semantic", "separator"])
def test_each_preset_returns_parent_child_chunks(preset_id):
    from engine.app.ingestion.presets import chunk_with_preset

    text = "# Chapter\nQuestion? Answer.\nArticle 1 text. Section 2 content here."
    chunks = chunk_with_preset(text, preset_id, {})
    assert chunks
    assert all(hasattr(parent, "children") and parent.children for parent in chunks)


def test_unknown_preset_fails_explicitly():
    from engine.app.ingestion.presets import UnknownChunkPreset, chunk_with_preset

    with pytest.raises(UnknownChunkPreset):
        chunk_with_preset("text", "missing", {})


def test_general_preset_uses_reasonable_defaults():
    from engine.app.ingestion.presets import chunk_with_preset, PRESETS

    preset = PRESETS["general"]
    assert preset.parent_tokens > 0
    assert preset.child_tokens > 0
    assert preset.overlap_tokens >= 0


def test_overrides_are_applied():
    from engine.app.ingestion.presets import chunk_with_preset

    text = "A. " * 100
    result = chunk_with_preset(text, "general", {"parent_tokens": 200, "child_tokens": 100})
    assert result
