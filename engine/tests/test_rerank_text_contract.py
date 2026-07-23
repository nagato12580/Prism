import os

if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "sqlite:///./_rerank_text_contract_test.db"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base
from backend.app.models import KnowledgeChunk, KnowledgeItem
from engine.app.retrieval.contracts import SearchScope


SCOPE = SearchScope(
    tenant_id="tenant-test",
    kb_uid="kb-test",
    index_generation="gen-test",
    graph_generation="graph-test",
)


def _candidate(chunk_uid: str, text: str = "real chunk text") -> dict:
    return {
        "chunk_uid": chunk_uid,
        "chunk_id": chunk_uid,
        "text": text,
        "rrf_score": 0.01,
        "score": 0.01,
    }


def test_reranker_receives_chunk_text_not_uuid(monkeypatch):
    from engine.app.retrieval import rerank as module

    payload = {}

    def fake_post(query, documents, top_n):
        payload.update(query=query, documents=documents, top_n=top_n)
        return [{"index": 0, "relevance_score": 0.9}]

    monkeypatch.setattr(module, "_post_rerank", fake_post)

    out = module.rerank("query", [_candidate("uuid-c1")], top_n=20, enabled=True)

    assert payload["documents"] == ["real chunk text"]
    assert out[0]["rerank_score"] == 0.9


def test_reranker_passes_remaining_budget_to_urlopen(monkeypatch):
    from engine.app.retrieval import rerank as module
    from engine.app.retrieval.execution_control import RetrievalExecutionControl
    seen = {}
    def fake_post(_query, _documents, _top_n, timeout):
        seen["timeout"] = timeout
        return [{"index": 0, "relevance_score": 0.9}]
    monkeypatch.setattr(module, "_post_rerank", fake_post)
    module.rerank(
        "query", [_candidate("uuid-c1")], 1, enabled=True,
        control=RetrievalExecutionControl.with_timeout(60),
    )
    assert 0 < seen["timeout"] <= 30


def test_unified_loads_child_text_before_rerank(monkeypatch):
    from engine.app.retrieval import unified

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add(
        KnowledgeItem(
            id="item-1",
            tenant_id="tenant-test",
            kb_uid="kb-test",
            title="Contract fixture",
            user_id="user-1",
        )
    )
    db.add(
        KnowledgeChunk(
            id="row-child",
            chunk_uid="child-public-uid",
            tenant_id="tenant-test",
            kb_uid="kb-test",
            file_uid="file-1",
            generation="gen-test",
            item_id="item-1",
            chunk_text="child text used for rerank",
            chunk_type="child",
        )
    )
    db.commit()

    monkeypatch.setattr(unified, "embed_query", lambda query: [0.1])
    monkeypatch.setattr(
        unified,
        "recall",
        lambda *a, **k: {
            "status": "ok",
            "results": [{
                "chunk_uid": "child-public-uid",
                "item_id": "item-1",
                "file_uid": "file-1",
                "rrf_score": 0.01,
                "channels": {"dense": {"raw_rank": 1, "raw_score": 0.8}},
                "metadata": {},
            }],
            "channels": [],
        },
    )
    seen = {}

    def fake_rerank(query, candidates, top_n, **kwargs):
        seen["documents"] = [row.get("text") for row in candidates]
        return candidates

    monkeypatch.setattr(unified, "rerank", fake_rerank)

    try:
        unified.unified_search("query", 1, db=db, graph_client=None, scope=SCOPE)
    finally:
        db.close()

    assert seen["documents"] == ["child text used for rerank"]


def test_invalid_provider_response_preserves_rrf_order_and_warns(monkeypatch):
    from engine.app.retrieval import rerank as module

    candidates = [_candidate("c1", "first"), _candidate("c2", "second")]
    monkeypatch.setattr(
        module,
        "_post_rerank",
        lambda *a, **k: [{"index": 0, "relevance_score": "not-numeric"}],
    )
    warnings = []

    out = module.rerank("query", candidates, top_n=2, enabled=True, warnings=warnings)

    assert [row["chunk_uid"] for row in out] == ["c1", "c2"]
    assert warnings[0]["code"] == "RERANK_UNAVAILABLE"
    assert all("rerank_score" not in row for row in out)


def test_missing_provider_score_preserves_rrf_order_and_warns(monkeypatch):
    from engine.app.retrieval import rerank as module

    candidates = [_candidate("c1", "first"), _candidate("c2", "second")]
    monkeypatch.setattr(
        module,
        "_post_rerank",
        lambda *a, **k: [{"index": 1}, {"index": 0, "relevance_score": 0.2}],
    )
    warnings = []

    out = module.rerank("query", candidates, top_n=2, enabled=True, warnings=warnings)

    assert [row["chunk_uid"] for row in out] == ["c1", "c2"]
    assert warnings[0]["code"] == "RERANK_UNAVAILABLE"
    assert all("rerank_score" not in row for row in out)


def test_provider_failure_preserves_rrf_order_without_fabricated_scores(monkeypatch):
    from engine.app.retrieval import rerank as module

    candidates = [_candidate("c1", "first"), _candidate("c2", "second")]
    monkeypatch.setattr(module, "_post_rerank", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    warnings = []

    out = module.rerank("query", candidates, top_n=2, enabled=True, warnings=warnings)

    assert [row["chunk_uid"] for row in out] == ["c1", "c2"]
    assert warnings == [{"code": "RERANK_UNAVAILABLE", "message": "down", "retryable": True}]
    assert all("rerank_score" not in row for row in out)


def test_unified_response_propagates_rerank_unavailable_warning(monkeypatch):
    from engine.app.retrieval import rerank as rerank_module
    from engine.app.retrieval import unified

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add(KnowledgeItem(id="item-2", tenant_id="tenant-test", kb_uid="kb-test", title="x", user_id="u"))
    db.add(KnowledgeChunk(
        id="row-2", chunk_uid="public-c2", tenant_id="tenant-test", kb_uid="kb-test",
        file_uid="file-2", generation="gen-test", item_id="item-2",
        chunk_text="provider document", chunk_type="child",
    ))
    db.commit()
    monkeypatch.setattr(unified, "embed_query", lambda query: [0.1])
    monkeypatch.setattr(unified, "recall", lambda *a, **k: {
        "status": "ok",
        "results": [{"chunk_uid": "public-c2", "item_id": "item-2", "file_uid": "file-2",
                     "rrf_score": 0.01, "channels": {"dense": {"raw_rank": 1, "raw_score": 1.0}},
                     "metadata": {}}],
        "channels": [],
    })
    monkeypatch.setattr(rerank_module, "_post_rerank", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))

    try:
        out = unified.unified_search("query", 1, db=db, graph_client=None, scope=SCOPE)
    finally:
        db.close()

    assert out[0]["warnings"][0]["code"] == "RERANK_UNAVAILABLE"


def test_parent_expansion_is_scoped_to_public_uid_and_generation(monkeypatch):
    from engine.app.chat import answer

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    for item_id, tenant, kb in (("item-good", "tenant-test", "kb-test"), ("item-bad", "other", "other")):
        db.add(KnowledgeItem(id=item_id, tenant_id=tenant, kb_uid=kb, title=item_id, user_id="u"))
    db.add_all([
        KnowledgeChunk(id="parent-good", chunk_uid="parent-public", tenant_id="tenant-test", kb_uid="kb-test",
                       file_uid="file-good", generation="gen-test", item_id="item-good", chunk_text="authorized parent", chunk_type="parent"),
        KnowledgeChunk(id="child-good", chunk_uid="shared-public", tenant_id="tenant-test", kb_uid="kb-test",
                       file_uid="file-good", generation="gen-test", item_id="item-good", chunk_text="authorized child",
                       chunk_type="child", parent_id="parent-good", parent_chunk_uid="parent-public"),
        KnowledgeChunk(id="parent-bad", chunk_uid="parent-public", tenant_id="other", kb_uid="other",
                       file_uid="file-bad", generation="other-gen", item_id="item-bad", chunk_text="forbidden parent", chunk_type="parent"),
        KnowledgeChunk(id="child-bad", chunk_uid="shared-public", tenant_id="other", kb_uid="other",
                       file_uid="file-bad", generation="other-gen", item_id="item-bad", chunk_text="forbidden child",
                       chunk_type="child", parent_id="parent-bad", parent_chunk_uid="parent-public"),
    ])
    db.commit(); db.close()
    monkeypatch.setattr(answer, "_Session", Session)

    details = answer._load_chunks(["shared-public"], scope=SCOPE)

    assert details["shared-public"]["text"] == "authorized parent"
