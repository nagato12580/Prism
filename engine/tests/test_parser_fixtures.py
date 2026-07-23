# engine/tests/test_parser_fixtures.py
"""Tests that verify real PDF/DOCX/XLSX/PPTX parsing through the registry."""
import pytest
from pathlib import Path


def _generate_pdf(path: Path):
    try:
        from reportlab.pdfgen import canvas
    except ImportError:
        pytest.skip("reportlab not installed")
    c = canvas.Canvas(str(path))
    c.drawString(100, 750, "Hello PDF world")
    c.save()


def _generate_docx(path: Path):
    try:
        from docx import Document
    except ImportError:
        pytest.skip("python-docx not installed")
    doc = Document()
    doc.add_paragraph("Hello DOCX world")
    doc.add_paragraph("Second paragraph")
    doc.save(str(path))


def _generate_xlsx(path: Path):
    try:
        from openpyxl import Workbook
    except ImportError:
        pytest.skip("openpyxl not installed")
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws["A1"] = "Hello"
    ws["B1"] = "XLSX"
    ws["A2"] = "Row2Col1"
    ws["B2"] = "Row2Col2"
    wb.save(str(path))


def _generate_pptx(path: Path):
    try:
        from pptx import Presentation
    except ImportError:
        pytest.skip("python-pptx not installed")
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.shapes.title.text = "Hello PPTX world"
    prs.save(str(path))


def test_registry_parses_real_pdf(tmp_path):
    _generate_pdf(tmp_path / "test.pdf")
    from engine.app.ingestion.parsers import build_default_registry
    registry = build_default_registry()
    result = registry.parse(tmp_path / "test.pdf", media_type="document", config={})
    assert result.parser_id == "pdf"
    assert "Hello PDF world" in result.markdown


def test_registry_parses_real_docx(tmp_path):
    _generate_docx(tmp_path / "test.docx")
    from engine.app.ingestion.parsers import build_default_registry
    registry = build_default_registry()
    result = registry.parse(tmp_path / "test.docx", media_type="document", config={})
    assert result.parser_id == "docx"
    assert "Hello DOCX world" in result.markdown


def test_registry_parses_real_xlsx(tmp_path):
    _generate_xlsx(tmp_path / "test.xlsx")
    from engine.app.ingestion.parsers import build_default_registry
    registry = build_default_registry()
    result = registry.parse(tmp_path / "test.xlsx", media_type="spreadsheet", config={})
    assert result.parser_id == "xlsx"
    assert "Hello" in result.markdown
    assert "XLSX" in result.markdown


def test_registry_parses_real_pptx(tmp_path):
    _generate_pptx(tmp_path / "test.pptx")
    from engine.app.ingestion.parsers import build_default_registry
    registry = build_default_registry()
    result = registry.parse(tmp_path / "test.pptx", media_type="document", config={})
    assert result.parser_id == "pptx"
    assert "Hello PPTX world" in result.markdown


def test_parser_error_wraps_low_level_exception(tmp_path):
    """A corrupted file should produce a ParserError, not crash."""
    path = tmp_path / "corrupt.pdf"
    path.write_bytes(b"not a pdf")
    from engine.app.ingestion.parsers import ParserError, build_default_registry
    registry = build_default_registry()
    with pytest.raises(ParserError):
        registry.parse(path, media_type="document", config={})


def test_media_type_is_passed_to_parsers(tmp_path):
    _generate_pdf(tmp_path / "test.pdf")
    from engine.app.ingestion.parsers import build_default_registry
    registry = build_default_registry()
    result = registry.parse(tmp_path / "test.pdf", media_type="report", config={"page_count": 5})
    assert result.parser_id == "pdf"
    assert result.page_count == 5
