# prism/engine/tests/test_generate_queries_v2.py
import os
import sys
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_project_root))

from dotenv import load_dotenv
load_dotenv(_project_root / ".env")


def test_load_paper_parents_returns_six_papers():
    """All 6 multi-view papers should be loaded with parent chunks."""
    from engine.eval.generate_queries_v2 import load_paper_parents

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    db = sessionmaker(bind=engine)()

    try:
        parents = load_paper_parents(db)
        # 6 papers
        paper_ids = {p["item_id"] for p in parents}
        assert len(paper_ids) == 6, f"Expected 6 papers, got {len(paper_ids)}"

        # Each paper has at least one parent with children
        for paper_id in paper_ids:
            paper_parents = [p for p in parents if p["item_id"] == paper_id]
            assert len(paper_parents) > 0, f"Paper {paper_id} has no parents"
            for p in paper_parents:
                assert len(p["child_ids"]) > 0, f"Parent {p['parent_id']} has no children"
    finally:
        db.close()


def test_generate_question_returns_chinese():
    """Generated question should be in Chinese."""
    from engine.eval.generate_queries_v2 import generate_question

    chunk_text = """多视图子空间聚类是一种将多视图数据集成到统一框架中的方法。
    该方法通过学习每个视图的自我表示矩阵来捕获数据的子空间结构。"""

    question, lang = generate_question(chunk_text, "Test Paper", "fact", 0)
    assert lang == "zh"
    assert len(question) > 5
    # Should contain Chinese characters
    assert any('一' <= c <= '鿿' for c in question)


def test_label_gold_chunks_identifies_direct_chunks():
    """Gold chunk labeling should identify directly relevant chunks."""
    from engine.eval.generate_queries_v2 import label_gold_chunks

    question = "多视图子空间聚类的核心方法是什么？"
    parent_text = "多视图子空间聚类通过学习每个视图的自我表示矩阵来集成多视图数据。"
    children = [
        {"chunk_id": "c1", "chunk_text": "该方法通过学习每个视图的自我表示矩阵来捕获子空间结构。"},
        {"chunk_id": "c2", "chunk_text": "实验使用了三个基准数据集进行评估。"},
        {"chunk_id": "c3", "chunk_text": "对比方法包括谱聚类和深度聚类。"},
    ]

    labels = label_gold_chunks(question, parent_text, children)
    assert len(labels) == 3

    # c1 content ("该方法通过学习每个视图的自我表示矩阵...") directly answers the question
    c1 = next(l for l in labels if l["chunk_id"] == "c1")
    assert c1["relevance"] == "direct", f"Expected c1 to be 'direct', got {c1['relevance']}"

    # All labels should have valid relevance values
    for label in labels:
        assert label["relevance"] in ("direct", "partial", "context")
        assert "chunk_id" in label
