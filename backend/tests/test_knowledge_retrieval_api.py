from backend.app.models import KnowledgeTopic


def _create_kb(client, db_session, *, actor="alice", tenant="tenant-a"):
    headers = {"X-Prism-Actor": actor, "X-Prism-Tenant": tenant}
    response = client.post("/api/v1/knowledge-bases", headers=headers, json={"name": "Retrieval KB"})
    kb_uid = response.json()["kb_uid"]
    topic = db_session.query(KnowledgeTopic).filter_by(kb_uid=kb_uid).one()
    topic.active_index_generation = "index-active"
    topic.active_graph_generation = "graph-active"
    db_session.commit()
    return kb_uid, headers


def _engine_payload(status="ok"):
    return {
        "status": status,
        "evidence": [] if status == "no_hits" else [{
            "evidence_id": None,
            "tenant_id": "tenant-a",
            "kb_uid": "kb-a",
            "file_uid": "file-a",
            "item_id": "item-a",
            "chunk_uid": "chunk-a",
            "parent_chunk_uid": None,
            "display_title": "Safe title",
            "original_filename": "safe.pdf",
            "excerpt": "Safe excerpt",
            "page_start": 1,
            "page_end": 1,
            "char_start": 0,
            "char_end": 12,
            "channel_scores": {"dense": {"raw_score": 0.9, "raw_rank": 1}},
            "rrf_score": 0.02,
            "rerank_score": None,
            "rerank_model": None,
            "retrieval_channels": ["dense"],
            "graph_path": [],
            "graph_explanation": None,
            "evidence_type": "chunk",
            "index_generation": "index-active",
            "degradation_flags": [],
            "storage_path": "C:/private/do-not-leak.pdf",
            "provider_payload": {"raw": "secret"},
        }],
        "warnings": ([{"code": "GRAPH_UNAVAILABLE", "message": "offline", "retryable": True}]
                     if status == "degraded" else []),
    }


def test_public_query_distinguishes_no_hits_from_unavailable(client, db_session, monkeypatch):
    from backend.app.api import knowledge_retrieval

    kb_uid, headers = _create_kb(client, db_session)
    monkeypatch.setattr(knowledge_retrieval, "call_engine_retrieval", lambda request: _engine_payload("no_hits"))
    no_hits = client.post(f"/api/v1/knowledge-bases/{kb_uid}/retrieval/query", headers=headers, json={"query": "missing"})
    assert no_hits.status_code == 200
    assert no_hits.json() == {"status": "no_hits", "evidence": [], "warnings": []}

    monkeypatch.setattr(knowledge_retrieval, "call_engine_retrieval", lambda request: _engine_payload("unavailable"))
    unavailable = client.post(f"/api/v1/knowledge-bases/{kb_uid}/retrieval/query", headers=headers, json={"query": "outage"})
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "RETRIEVAL_UNAVAILABLE"


def test_unauthorized_kb_is_rejected_before_engine_call(client, db_session, monkeypatch):
    from backend.app.api import knowledge_retrieval

    kb_uid, _ = _create_kb(client, db_session)
    called = False

    def forbidden_call(request):
        nonlocal called
        called = True
        raise AssertionError("engine must not be called")

    monkeypatch.setattr(knowledge_retrieval, "call_engine_retrieval", forbidden_call)
    response = client.post(
        f"/api/v1/knowledge-bases/{kb_uid}/retrieval/query",
        headers={"X-Prism-Actor": "bob", "X-Prism-Tenant": "tenant-a"},
        json={"query": "secret"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "KNOWLEDGE_ACCESS_DENIED"
    assert called is False


def test_degraded_maps_to_206_and_strips_internal_fields(client, db_session, monkeypatch):
    from backend.app.api import knowledge_retrieval

    kb_uid, headers = _create_kb(client, db_session)
    captured = {}

    def fake_call(request):
        captured.update(request)
        return _engine_payload("degraded")

    monkeypatch.setattr(knowledge_retrieval, "call_engine_retrieval", fake_call)
    response = client.post(
        f"/api/v1/knowledge-bases/{kb_uid}/retrieval/query",
        headers=headers,
        json={"query": "architecture", "mode": "deep", "filters": {"file_uids": ["file-a"]}, "config": {"top_k": 5}},
    )
    assert response.status_code == 206
    assert captured["scope"] == {
        "tenant_id": "tenant-a", "kb_uid": kb_uid,
        "index_generation": "index-active", "graph_generation": "graph-active",
    }
    evidence = response.json()["evidence"][0]
    assert "tenant_id" not in evidence
    assert "storage_path" not in evidence
    assert "provider_payload" not in evidence
    assert evidence["index_generation"] == "index-active"


def test_public_query_input_boundaries(client, db_session, monkeypatch):
    from backend.app.api import knowledge_retrieval

    kb_uid, headers = _create_kb(client, db_session)
    monkeypatch.setattr(knowledge_retrieval, "call_engine_retrieval", lambda request: _engine_payload())
    for body in (
        {"query": ""},
        {"query": "x" * 2001},
        {"query": "ok", "mode": "unsafe"},
        {"query": "ok", "config": {"top_k": 0}},
        {"query": "ok", "config": {"top_k": 101}},
        {"query": "ok", "filters": {"storage_path": "C:/private"}},
        {"query": "ok", "config": {"provider": "raw"}},
    ):
        response = client.post(f"/api/v1/knowledge-bases/{kb_uid}/retrieval/query", headers=headers, json=body)
        assert response.status_code == 422


def test_public_query_rejects_oversized_filter_collections_and_elements(client, db_session, monkeypatch):
    from backend.app.api import knowledge_retrieval

    kb_uid, headers = _create_kb(client, db_session)
    monkeypatch.setattr(knowledge_retrieval, "call_engine_retrieval", lambda request: _engine_payload())
    filters = [
        {"file_uids": [f"file-{i}" for i in range(101)]},
        {"file_uids": ["x" * 129]},
        {"source_types": [f"type-{i}" for i in range(101)]},
        {"source_types": ["x" * 65]},
    ]
    for value in filters:
        response = client.post(
            f"/api/v1/knowledge-bases/{kb_uid}/retrieval/query",
            headers=headers,
            json={"query": "safe", "filters": value},
        )
        assert response.status_code == 422


def test_malformed_engine_payload_maps_to_safe_unavailable(client, db_session, monkeypatch):
    from backend.app.api import knowledge_retrieval

    kb_uid, headers = _create_kb(client, db_session)
    for payload in (
        {"status": "surprise", "evidence": [], "warnings": []},
        {"status": "ok", "evidence": [{"chunk_uid": 123}], "warnings": []},
        {"status": "ok", "warnings": []},
    ):
        monkeypatch.setattr(knowledge_retrieval, "call_engine_retrieval", lambda request, p=payload: p)
        response = client.post(
            f"/api/v1/knowledge-bases/{kb_uid}/retrieval/query",
            headers=headers,
            json={"query": "safe"},
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "RETRIEVAL_UNAVAILABLE"


def test_transport_error_does_not_leak_internal_url(client, db_session, monkeypatch):
    import httpx
    from backend.app.api import knowledge_retrieval

    kb_uid, headers = _create_kb(client, db_session)

    def fail(request):
        raise httpx.ConnectError("connection refused at http://engine.internal:5180/private")

    monkeypatch.setattr(knowledge_retrieval, "call_engine_retrieval", fail)
    response = client.post(
        f"/api/v1/knowledge-bases/{kb_uid}/retrieval/query",
        headers=headers,
        json={"query": "safe"},
    )
    assert response.status_code == 503
    message = response.json()["error"]["message"]
    assert message == "Retrieval service is unavailable"
    assert "engine.internal" not in response.text


def test_call_engine_retrieval_signs_scope_into_trusted_header(monkeypatch):
    import backend.app.api.knowledge_retrieval as retrieval_api

    monkeypatch.setattr(retrieval_api.settings, "KNOWLEDGE_SCOPE_SECRET", "scope-secret")
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return _engine_payload("no_hits")

    def fake_post(url, *, json, headers, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(retrieval_api.httpx, "post", fake_post)

    payload = {
        "scope": {
            "tenant_id": "legacy-personal",
            "kb_uid": "kb-legacy",
            "index_generation": "index-active",
            "graph_generation": "graph-active",
        },
        "query": "architecture",
        "mode": "deep",
        "filters": {"file_uids": ["file-a"]},
        "config": {"top_k": 5},
    }
    retrieval_api.call_engine_retrieval(payload)

    assert captured["json"] == {
        "query": "architecture",
        "mode": "deep",
        "filters": {"file_uids": ["file-a"]},
        "config": {"top_k": 5},
    }
    assert "X-Prism-Knowledge-Scope" in captured["headers"]
    assert captured["headers"]["X-Prism-Knowledge-Scope"]


def test_retrieval_requires_scope_secret_before_contacting_engine(client, db_session, monkeypatch):
    import backend.app.api.knowledge_retrieval as retrieval_api

    kb_uid, headers = _create_kb(client, db_session)
    monkeypatch.setattr(retrieval_api.settings, "KNOWLEDGE_SCOPE_SECRET", "")

    called = False

    def fail_if_called(request):
        nonlocal called
        called = True
        raise AssertionError("engine must not be called without scope secret")

    monkeypatch.setattr(retrieval_api, "call_engine_retrieval", fail_if_called)
    response = client.post(
        f"/api/v1/knowledge-bases/{kb_uid}/retrieval/query",
        headers=headers,
        json={"query": "safe"},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "RETRIEVAL_UNAVAILABLE"
    assert called is False
