# engine/tests/test_parser_registry.py
from pathlib import Path

import pytest


def test_registry_selects_markdown_parser(tmp_path: Path):
    from engine.app.ingestion.parsers import build_default_registry

    path = tmp_path / "a.md"
    path.write_text("# Title\nBody", encoding="utf-8")
    result = build_default_registry().parse(path, media_type="document", config={})
    assert result.markdown.startswith("# Title")
    assert result.parser_id == "markdown"


def test_registry_selects_text_parser(tmp_path: Path):
    from engine.app.ingestion.parsers import build_default_registry

    path = tmp_path / "a.txt"
    path.write_text("Plain text", encoding="utf-8")
    result = build_default_registry().parse(path, media_type="document", config={})
    assert result.markdown == "Plain text"
    assert result.parser_id == "text"


def test_registry_rejects_unsupported_extension(tmp_path: Path):
    from engine.app.ingestion.parsers import UnsupportedDocument, build_default_registry

    path = tmp_path / "a.bin"
    path.write_bytes(b"binary")
    with pytest.raises(UnsupportedDocument):
        build_default_registry().parse(path, media_type="document", config={})


def test_registry_capabilities_returns_parsers_and_extensions():
    from engine.app.ingestion.parsers import build_default_registry

    registry = build_default_registry()
    caps = registry.capabilities()
    assert len(caps) > 0
    ids = {cap["parser_id"] for cap in caps}
    assert "markdown" in ids
    assert "text" in ids


def test_markdown_parser_handles_markdown_extension(tmp_path: Path):
    from engine.app.ingestion.parsers import build_default_registry

    path = tmp_path / "readme.markdown"
    path.write_text("# Title", encoding="utf-8")
    result = build_default_registry().parse(path, media_type="document", config={})
    assert result.parser_id == "markdown"
