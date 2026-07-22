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


def test_registry_capabilities_returns_all_parsers():
    from engine.app.ingestion.parsers import build_default_registry

    registry = build_default_registry()
    caps = registry.capabilities()
    parser_ids = {cap["parser_id"] for cap in caps}
    assert parser_ids >= {"markdown", "text", "pdf", "docx", "xlsx", "pptx"}


def test_markdown_parser_handles_markdown_extension(tmp_path: Path):
    from engine.app.ingestion.parsers import build_default_registry

    path = tmp_path / "readme.markdown"
    path.write_text("# Title", encoding="utf-8")
    result = build_default_registry().parse(path, media_type="document", config={})
    assert result.parser_id == "markdown"


def test_pdf_parser_is_registered():
    from engine.app.ingestion.parsers import build_default_registry

    registry = build_default_registry()
    caps = registry.capabilities()
    pdf_cap = next(cap for cap in caps if cap["parser_id"] == "pdf")
    assert ".pdf" in pdf_cap["extensions"]


def test_docx_parser_is_registered():
    from engine.app.ingestion.parsers import build_default_registry

    registry = build_default_registry()
    caps = registry.capabilities()
    docx_cap = next(cap for cap in caps if cap["parser_id"] == "docx")
    assert ".docx" in docx_cap["extensions"]


def test_xlsx_parser_is_registered():
    from engine.app.ingestion.parsers import build_default_registry

    registry = build_default_registry()
    caps = registry.capabilities()
    xlsx_cap = next(cap for cap in caps if cap["parser_id"] == "xlsx")
    assert ".xlsx" in xlsx_cap["extensions"]


def test_pptx_parser_is_registered():
    from engine.app.ingestion.parsers import build_default_registry

    registry = build_default_registry()
    caps = registry.capabilities()
    pptx_cap = next(cap for cap in caps if cap["parser_id"] == "pptx")
    assert ".pptx" in pptx_cap["extensions"]


def test_empty_markdown_raises_parser_error(tmp_path: Path):
    from engine.app.ingestion.parsers import ParserError, build_default_registry

    path = tmp_path / "empty.md"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ParserError):
        build_default_registry().parse(path, media_type="document", config={})
