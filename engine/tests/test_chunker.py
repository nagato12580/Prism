# prism/engine/tests/test_chunker.py
from engine.app.ingestion.chunker import chunk_text


def test_chunk_short_text_single():
    chunks = chunk_text("短文本。", chunk_size=500)
    assert chunks == ["短文本"]


def test_chunk_empty():
    assert chunk_text("") == []
    assert chunk_text("   ") == []


def test_chunk_split_by_sentence():
    text = "第一句。第二句。第三句。"
    chunks = chunk_text(text, chunk_size=8, overlap=0)
    assert len(chunks) >= 2
    # 每块不超过 8 字符
    for c in chunks:
        assert len(c) <= 8


def test_chunk_overlap():
    text = "句子一很长很长。句子二也很长很长。句子三同样很长很长。"
    chunks = chunk_text(text, chunk_size=15, overlap=5)
    assert len(chunks) >= 2
    # 第二块开头应包含第一块末尾的内容（overlap）
    if len(chunks) >= 2:
        tail = chunks[0][-5:]
        assert chunks[1][:5] == tail or tail in chunks[1]


def test_chunk_long_sentence_hard_split():
    long = "字" * 1200
    chunks = chunk_text(long, chunk_size=500, overlap=100)
    assert len(chunks) == 3  # 500 + 500 + 200


def test_chunk_parent_child_uses_configured_balanced_sizes(monkeypatch):
    import engine.app.ingestion.chunker as chunker

    text = "This sentence has enough tokens for a small regression test. " * 300

    monkeypatch.setattr(chunker.settings, "CHILD_CHUNK_TOKENS", 40)
    monkeypatch.setattr(chunker.settings, "PARENT_CHUNK_TOKENS", 80)
    monkeypatch.setattr(chunker.settings, "CHILD_OVERLAP_RATIO", 0.1)
    small_chunks = chunker.chunk_parent_child(text)

    monkeypatch.setattr(chunker.settings, "CHILD_CHUNK_TOKENS", 384)
    monkeypatch.setattr(chunker.settings, "PARENT_CHUNK_TOKENS", 1536)
    large_chunks = chunker.chunk_parent_child(text)

    assert small_chunks
    assert all(
        chunker.count_tokens(parent.content) <= 80 * 1.15 for parent in small_chunks
    )
    assert all(
        chunker.count_tokens(child.content) <= 40 * 1.25
        for parent in small_chunks
        for child in parent.children
    )
    assert len(small_chunks) > len(large_chunks)
    assert sum(len(parent.children) for parent in small_chunks) > sum(
        len(parent.children) for parent in large_chunks
    )
