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
