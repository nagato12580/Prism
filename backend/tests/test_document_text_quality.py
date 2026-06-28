from backend.app.services.document_text_quality import assess_document_text


def test_normal_paper_text_passes_quality_gate():
    text = "Representation learning improves retrieval. " * 1000

    result = assess_document_text(
        text,
        page_count=12,
        max_chars=300000,
        max_chars_per_page=12000,
    )

    assert result.ok is True
    assert result.error_code == ""


def test_multi_million_character_document_is_blocked():
    text = "x" * 2_180_754

    result = assess_document_text(
        text,
        page_count=858,
        max_chars=300000,
        max_chars_per_page=12000,
    )

    assert result.ok is False
    assert result.error_code == "text_too_large"
    assert "2180754" in result.message
    assert "858" in result.message


def test_missing_page_count_uses_total_character_limit():
    text = "x" * 300_001

    result = assess_document_text(
        text,
        page_count=None,
        max_chars=300000,
        max_chars_per_page=12000,
    )

    assert result.ok is False
    assert result.error_code == "text_too_large"


def test_too_many_characters_per_page_is_blocked():
    text = "x" * 130_000

    result = assess_document_text(
        text,
        page_count=10,
        max_chars=300000,
        max_chars_per_page=12000,
    )

    assert result.ok is False
    assert result.error_code == "text_density_too_high"
