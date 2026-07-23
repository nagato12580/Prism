import os
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "sqlite:///./_rerank_test.db"

from unittest.mock import patch
from engine.app.retrieval.rerank import rerank


def _c(cid, score):
    return {"chunk_id": cid, "score": score, "text": "doc " + cid}


def test_rerank_reorders_by_returned_scores():
    fake_resp = [
        {"index": 1, "relevance_score": 0.9},
        {"index": 0, "relevance_score": 0.2},
    ]  # candidate[1] first, then [0]
    with patch("engine.app.retrieval.rerank._post_rerank", return_value=fake_resp):
        out = rerank("q", [_c("a", 0.9), _c("b", 0.1)], top_n=5)
    assert [o["chunk_id"] for o in out] == ["b", "a"]   # reordered
    assert out[0]["source_marker"] == "rerank"


def test_rerank_degrades_on_failure_preserving_input_order():
    with patch("engine.app.retrieval.rerank._post_rerank", side_effect=RuntimeError("api down")):
        out = rerank("q", [_c("a", 0.9), _c("b", 0.1)], top_n=5)
    assert [o["chunk_id"] for o in out] == ["a", "b"]   # original order, no raise


def test_rerank_disabled_returns_input_unchanged():
    out = rerank("q", [_c("a", 0.9)], top_n=5, enabled=False)
    assert out[0]["chunk_id"] == "a" and out[0].get("source_marker") != "rerank"
