# prism/backend/tests/test_file_parser.py
from pathlib import Path
from backend.app.utils.file_parser import extract_text


def test_extract_txt(tmp_path):
    f = tmp_path / "note.md"
    f.write_text("# 标题\n正文内容", encoding="utf-8")
    text = extract_text(str(f))
    assert "标题" in text
    assert "正文内容" in text


def test_extract_unsupported_raises(tmp_path):
    f = tmp_path / "bad.xyz"
    f.write_text("data", encoding="utf-8")
    import pytest
    with pytest.raises(ValueError, match="不支持的文件类型"):
        extract_text(str(f))
