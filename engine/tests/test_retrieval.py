# engine/tests/test_retrieval.py
import pytest


def test_hybrid_components_import():
    from engine.app.retrieval import vector_search, bm25_search, hybrid, unified
    assert vector_search is not None
    assert bm25_search is not None
    assert hybrid is not None
    assert unified is not None


def test_rerank_import():
    from engine.app.retrieval import rerank
    assert rerank is not None
