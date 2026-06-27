from engine.app.ingestion.chunker import chunk_parent_child


def test_chunk_parent_child_preserves_page_ranges_from_parser_markers():
    text = (
        "[[PAGE:1]]\n"
        "# Intro\n"
        "Attention residuals are shortcuts.\n"
        "[[PAGE:2]]\n"
        "# Method\n"
        "Residual paths are analyzed here.\n"
    )

    parents = chunk_parent_child(text)

    assert parents
    assert parents[0].page_start == 1
    assert parents[0].page_end == 2
    assert parents[0].children[0].page_start == 1
    assert parents[0].children[-1].page_end == 2
    assert "[[PAGE:" not in parents[0].content
