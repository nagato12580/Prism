import json
import asyncio

import pytest
from pydantic import ValidationError

from backend.app.models import EvaluationDataset, EvaluationRun, KnowledgeJob, KnowledgeTopic
from backend.app.schemas.knowledge_evaluation import EvaluationItemInput, EvaluationRunCreate


HEADERS = {"X-Prism-Actor": "owner", "X-Prism-Tenant": "tenant"}
RUN_HEADERS = {**HEADERS, "Idempotency-Key": "evaluation-request"}


def _topic(db):
    row = KnowledgeTopic(
        kb_uid="kb-eval", tenant_id="tenant", owner_user_id="owner", name="Evaluation KB",
        active_index_generation="index-one", active_graph_generation="graph-one",
        retrieval_config={"top_k": 3}, embedding_profile={"model": "embed-one"}, graph_config={"mode": "fast"},
    )
    db.add(row)
    db.commit()
    return row


async def _asgi_chunked_post(app, path, chunks, headers=()):
    messages = [
        {"type": "http.request", "body": chunk, "more_body": index < len(chunks) - 1}
        for index, chunk in enumerate(chunks)
    ]
    receive_count = 0
    sent = []
    async def receive():
        nonlocal receive_count
        message = messages[receive_count]
        receive_count += 1
        return message
    async def send(message):
        sent.append(message)
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "POST", "scheme": "http", "path": path, "raw_path": path.encode(),
        "query_string": b"", "root_path": "", "server": ("testserver", 80),
        "client": ("testclient", 50000), "headers": list(headers),
    }
    await app(scope, receive, send)
    return sent, receive_count


def test_chunked_evaluation_body_limit_stops_reading_after_overflow(client):
    from backend.app.main import MAX_EVALUATION_REQUEST_BYTES
    chunks = [b"x" * (MAX_EVALUATION_REQUEST_BYTES // 2 + 1)] * 3
    sent, receive_count = asyncio.run(_asgi_chunked_post(
        client.app, "/api/v1/knowledge-bases/kb-eval/evaluation-datasets/generated", chunks,
    ))
    start = next(message for message in sent if message["type"] == "http.response.start")
    assert start["status"] == 413
    assert receive_count == 2


def test_legal_chunked_evaluation_body_is_replayed_to_route(client, db_session):
    _topic(db_session)
    body = json.dumps({"name": "chunked", "items": [{"query": "q"}]}).encode()
    headers = tuple((key.lower().encode(), value.encode()) for key, value in HEADERS.items())
    headers += ((b"content-type", b"application/json"),)
    sent, receive_count = asyncio.run(_asgi_chunked_post(
        client.app, "/api/v1/knowledge-bases/kb-eval/evaluation-datasets/generated",
        [body[:10], body[10:]], headers,
    ))
    start = next(message for message in sent if message["type"] == "http.response.start")
    assert start["status"] == 201
    assert receive_count == 2


def test_evaluation_models_use_exact_table_names():
    from backend.app.models import EvaluationDataset, EvaluationDatasetItem, EvaluationRun, EvaluationRunItem

    assert [model.__tablename__ for model in (EvaluationDataset, EvaluationDatasetItem, EvaluationRun, EvaluationRunItem)] == [
        "evaluation_dataset", "evaluation_dataset_item", "evaluation_run", "evaluation_run_item"
    ]


def test_evaluation_models_use_only_scoped_internal_foreign_keys():
    from backend.app.models import EvaluationDataset, EvaluationDatasetItem, EvaluationRun, EvaluationRunItem

    def specs(model):
        return {
            (tuple(element.parent.name for element in fk.elements), fk.referred_table.name)
            for fk in model.__table__.foreign_key_constraints
        }

    assert specs(EvaluationDataset) == {(('kb_uid',), 'knowledge_topic')}
    assert specs(EvaluationDatasetItem) == {
        (("dataset_id", "tenant_id", "kb_uid"), "evaluation_dataset")
    }
    assert specs(EvaluationRun) == {
        (("kb_uid",), "knowledge_topic"),
        (("dataset_id", "tenant_id", "kb_uid"), "evaluation_dataset"),
    }
    assert specs(EvaluationRunItem) == {
        (("run_id", "tenant_id", "kb_uid"), "evaluation_run"),
        (("dataset_item_id", "tenant_id", "kb_uid"), "evaluation_dataset_item"),
    }
    assert "uq_knowledge_topic_tenant_kb" not in {
        constraint.name for constraint in KnowledgeTopic.__table__.constraints
    }
    assert all(
        relationship.primaryjoin is not None
        for model in (EvaluationDataset, EvaluationDatasetItem, EvaluationRun, EvaluationRunItem)
        for relationship in model.__mapper__.relationships
    )


def test_jsonl_import_export_and_extra_forbid(client, db_session):
    _topic(db_session)
    body = {"name": "gold", "jsonl": json.dumps({"query": "q", "gold_chunk_uids": ["c1"], "gold_answer": "a"})}
    created = client.post("/api/v1/knowledge-bases/kb-eval/evaluation-datasets/import", headers=HEADERS, json=body)
    assert created.status_code == 201, created.text
    dataset_uid = created.json()["dataset_uid"]
    exported = client.get(f"/api/v1/knowledge-bases/kb-eval/evaluation-datasets/{dataset_uid}/export", headers=HEADERS)
    assert exported.status_code == 200
    assert json.loads(exported.text)["gold_chunk_uids"] == ["c1"]
    invalid = client.post("/api/v1/knowledge-bases/kb-eval/evaluation-datasets/import", headers=HEADERS, json={**body, "unexpected": True})
    assert invalid.status_code == 422


def test_run_freezes_active_snapshots_and_enqueues_job(client, db_session, monkeypatch):
    pushed = []
    class Redis:
        def lpush(self, queue, message): pushed.append((queue, message))
    monkeypatch.setattr("backend.app.api.knowledge_evaluation._redis_client", lambda: Redis())
    topic = _topic(db_session)
    dataset = client.post(
        "/api/v1/knowledge-bases/kb-eval/evaluation-datasets/generated", headers=HEADERS,
        json={"name": "generated", "items": [{"query": "q", "gold_chunk_uids": ["c1"]}]},
    ).json()
    response = client.post(
        "/api/v1/knowledge-bases/kb-eval/evaluation-runs", headers=RUN_HEADERS,
        json={"dataset_uid": dataset["dataset_uid"], "config": {"mode": "deep", "top_k": 3, "graph_hops": 2}},
    )
    assert response.status_code == 201, response.text
    run = response.json()
    assert run["index_generation"] == "index-one"
    assert run["graph_generation"] == "graph-one"
    assert run["retrieval_config"]["top_k"] == 3
    assert run["model"] is None
    topic.active_index_generation = "index-two"
    topic.active_graph_generation = "graph-two"
    db_session.commit()
    detail = client.get(f"/api/v1/knowledge-bases/kb-eval/evaluation-runs/{run['run_uid']}", headers=HEADERS).json()
    assert detail["index_generation"] == "index-one"
    from backend.app.models import KnowledgeJob
    assert db_session.query(KnowledgeJob).filter_by(job_type="evaluation", resource_id=run["id"]).count() == 1
    assert pushed


def test_run_config_is_single_typed_allowlist():
    allowed = EvaluationRunCreate(dataset_uid="dataset", config={"mode": "deep", "top_k": 7, "graph_hops": 2})
    assert allowed.config.model_dump() == {"mode": "deep", "top_k": 7, "graph_hops": 2, "timeout_seconds": 120}
    assert allowed.model is None
    for config in ({"provider": "secret"}, {"model": "unused"}, {"max_iterations": 2}):
        with pytest.raises(ValidationError):
            EvaluationRunCreate(dataset_uid="dataset", config=config)


def test_run_rejects_missing_index_without_creating_job(client, db_session, monkeypatch):
    topic = _topic(db_session)
    topic.active_index_generation = None
    db_session.commit()
    dataset = client.post(
        "/api/v1/knowledge-bases/kb-eval/evaluation-datasets/generated", headers=HEADERS,
        json={"name": "generated", "items": [{"query": "q", "gold_chunk_uids": ["c1"]}]},
    ).json()
    monkeypatch.setattr(
        "backend.app.api.knowledge_evaluation._redis_client",
        lambda: (_ for _ in ()).throw(AssertionError("Redis must not be initialized")),
    )

    response = client.post(
        "/api/v1/knowledge-bases/kb-eval/evaluation-runs", headers=RUN_HEADERS,
        json={"dataset_uid": dataset["dataset_uid"]},
    )

    assert response.status_code == 409
    assert db_session.query(EvaluationRun).count() == 0
    assert db_session.query(KnowledgeJob).filter_by(job_type="evaluation").count() == 0


def test_run_snapshots_exclude_secret_and_unknown_topic_config(client, db_session, monkeypatch):
    class Redis:
        def lpush(self, _queue, _message): pass
    monkeypatch.setattr("backend.app.api.knowledge_evaluation._redis_client", lambda: Redis())
    topic = _topic(db_session)
    topic.retrieval_config = {"top_k": 3, "rrf_k": 60, "api_key": "secret", "unknown": "private"}
    topic.embedding_profile = {"model": "embed-one", "dimension": 768, "api_key": "secret"}
    topic.graph_config = {"mode": "fast", "graph_hops": 2, "password": "secret"}
    db_session.commit()
    dataset = client.post(
        "/api/v1/knowledge-bases/kb-eval/evaluation-datasets/generated", headers=HEADERS,
        json={"name": "generated", "items": [{"query": "q"}]},
    ).json()

    response = client.post(
        "/api/v1/knowledge-bases/kb-eval/evaluation-runs", headers=RUN_HEADERS,
        json={"dataset_uid": dataset["dataset_uid"]},
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["retrieval_config"] == {"top_k": 3, "rrf_k": 60}
    assert payload["embedding_profile"] == {"model": "embed-one", "dimension": 768}
    assert payload["graph_config"] == {"mode": "fast", "graph_hops": 2}


def test_public_snapshot_drops_nested_values_even_under_allowed_keys():
    from backend.app.api.knowledge_evaluation import _safe_snapshot

    assert _safe_snapshot(
        {"model": {"name": "embed", "api_key": "secret"}, "dimension": 768},
        "embedding",
    ) == {"dimension": 768}


def test_evaluation_item_bounds_gold_uid_and_query():
    EvaluationItemInput(query="q", gold_chunk_uids=["x" * 128])
    for body in (
        {"query": "q", "gold_chunk_uids": [""]},
        {"query": "q", "gold_chunk_uids": ["x" * 129]},
        {"query": "x" * 2001},
    ):
        with pytest.raises(ValidationError):
            EvaluationItemInput.model_validate(body)


def test_jsonl_import_rejects_more_than_ten_thousand_items(client, db_session):
    _topic(db_session)
    jsonl = "\n".join('{"query":"q"}' for _ in range(10001))

    response = client.post(
        "/api/v1/knowledge-bases/kb-eval/evaluation-datasets/import",
        headers=HEADERS,
        json={"name": "too-many", "jsonl": jsonl},
    )

    assert response.status_code == 422
    assert db_session.query(KnowledgeJob).count() == 0


def test_delete_rejects_active_or_cancel_requested_job_then_allows_terminal(client, db_session, monkeypatch):
    class Redis:
        def lpush(self, _queue, _message): pass
    monkeypatch.setattr("backend.app.api.knowledge_evaluation._redis_client", lambda: Redis())
    _topic(db_session)
    dataset = client.post(
        "/api/v1/knowledge-bases/kb-eval/evaluation-datasets/generated", headers=HEADERS,
        json={"name": "generated", "items": [{"query": "q"}]},
    ).json()
    run = client.post(
        "/api/v1/knowledge-bases/kb-eval/evaluation-runs", headers=RUN_HEADERS,
        json={"dataset_uid": dataset["dataset_uid"]},
    ).json()

    active = client.delete(f"/api/v1/knowledge-bases/kb-eval/evaluation-runs/{run['run_uid']}", headers=HEADERS)
    assert active.status_code == 409
    canceled = client.post(f"/api/v1/knowledge-bases/kb-eval/evaluation-runs/{run['run_uid']}/cancel", headers=HEADERS)
    assert canceled.status_code == 200
    still_active = client.delete(f"/api/v1/knowledge-bases/kb-eval/evaluation-runs/{run['run_uid']}", headers=HEADERS)
    assert still_active.status_code == 409
    job = db_session.query(KnowledgeJob).filter_by(resource_id=run["id"], job_type="evaluation").one()
    job.status = "canceled"
    db_session.get(EvaluationRun, run["id"]).status = "canceled"
    db_session.commit()
    deleted = client.delete(f"/api/v1/knowledge-bases/kb-eval/evaluation-runs/{run['run_uid']}", headers=HEADERS)
    assert deleted.status_code == 204


def test_evaluation_authorization_and_cancel_delete(client, db_session):
    _topic(db_session)
    denied = client.get("/api/v1/knowledge-bases/kb-eval/evaluation-runs", headers={"X-Prism-Actor": "other", "X-Prism-Tenant": "tenant"})
    assert denied.status_code == 403


def test_run_requires_idempotency_key(client, db_session):
    _topic(db_session)
    dataset = client.post(
        "/api/v1/knowledge-bases/kb-eval/evaluation-datasets/generated", headers=HEADERS,
        json={"name": "generated", "items": [{"query": "q"}]},
    ).json()
    response = client.post(
        "/api/v1/knowledge-bases/kb-eval/evaluation-runs", headers=HEADERS,
        json={"dataset_uid": dataset["dataset_uid"]},
    )
    assert response.status_code == 422


def test_evaluation_request_total_body_limit_returns_413(client):
    response = client.post(
        "/api/v1/knowledge-bases/kb-eval/evaluation-datasets/generated",
        headers={**HEADERS, "Content-Length": str(10 * 1024 * 1024 + 1)},
        content=b"{}",
    )
    assert response.status_code == 413


def test_publish_failure_is_durable_and_same_key_reuses_run(client, db_session, monkeypatch):
    _topic(db_session)
    dataset = client.post(
        "/api/v1/knowledge-bases/kb-eval/evaluation-datasets/generated", headers=HEADERS,
        json={"name": "generated", "items": [{"query": "q"}]},
    ).json()
    class FailingRedis:
        def lpush(self, _queue, _message): raise RuntimeError("down")
    monkeypatch.setattr("backend.app.api.knowledge_evaluation._redis_client", lambda: FailingRedis())
    body = {"dataset_uid": dataset["dataset_uid"], "config": {"top_k": 3}}
    first = client.post("/api/v1/knowledge-bases/kb-eval/evaluation-runs", headers=RUN_HEADERS, json=body)
    assert first.status_code == 202
    pushed = []
    class Redis:
        def lpush(self, queue, message): pushed.append((queue, message))
    monkeypatch.setattr("backend.app.api.knowledge_evaluation._redis_client", lambda: Redis())
    second = client.post("/api/v1/knowledge-bases/kb-eval/evaluation-runs", headers=RUN_HEADERS, json=body)
    assert second.status_code == 200
    assert second.json()["run_uid"] == first.json()["run_uid"]
    assert db_session.query(EvaluationRun).count() == 1
    assert db_session.query(KnowledgeJob).filter_by(job_type="evaluation").count() == 1
    assert pushed
    conflict = client.post(
        "/api/v1/knowledge-bases/kb-eval/evaluation-runs", headers=RUN_HEADERS,
        json={"dataset_uid": dataset["dataset_uid"], "config": {"top_k": 4}},
    )
    assert conflict.status_code == 409


def test_run_detail_paginates_items(client, db_session, monkeypatch):
    class Redis:
        def lpush(self, _queue, _message): pass
    monkeypatch.setattr("backend.app.api.knowledge_evaluation._redis_client", lambda: Redis())
    _topic(db_session)
    dataset = client.post(
        "/api/v1/knowledge-bases/kb-eval/evaluation-datasets/generated", headers=HEADERS,
        json={"name": "generated", "items": [{"query": f"q{i}"} for i in range(3)]},
    ).json()
    run = client.post(
        "/api/v1/knowledge-bases/kb-eval/evaluation-runs", headers=RUN_HEADERS,
        json={"dataset_uid": dataset["dataset_uid"]},
    ).json()
    first = client.get(
        f"/api/v1/knowledge-bases/kb-eval/evaluation-runs/{run['run_uid']}?limit=2", headers=HEADERS,
    ).json()
    assert len(first["items"]) == 2
    assert first["items_total"] == 3
    assert first["next_cursor"] == "1"
    second = client.get(
        f"/api/v1/knowledge-bases/kb-eval/evaluation-runs/{run['run_uid']}?limit=2&cursor={first['next_cursor']}", headers=HEADERS,
    ).json()
    assert [item["ordinal"] for item in second["items"]] == [2]
    assert second["next_cursor"] is None


def test_active_evaluation_blocks_v1_knowledge_base_delete(client, db_session, monkeypatch):
    class Redis:
        def lpush(self, _queue, _message): pass
    monkeypatch.setattr("backend.app.api.knowledge_evaluation._redis_client", lambda: Redis())
    _topic(db_session)
    dataset = client.post(
        "/api/v1/knowledge-bases/kb-eval/evaluation-datasets/generated", headers=HEADERS,
        json={"name": "generated", "items": [{"query": "q"}]},
    ).json()
    client.post(
        "/api/v1/knowledge-bases/kb-eval/evaluation-runs", headers=RUN_HEADERS,
        json={"dataset_uid": dataset["dataset_uid"]},
    )
    response = client.delete("/api/v1/knowledge-bases/kb-eval", headers=HEADERS)
    assert response.status_code == 409


def test_export_and_dataset_list_do_not_load_items_relationship(client, db_session):
    _topic(db_session)
    dataset = client.post(
        "/api/v1/knowledge-bases/kb-eval/evaluation-datasets/generated", headers=HEADERS,
        json={"name": "generated", "items": [{"query": f"q{i}"} for i in range(10_000)]},
    ).json()
    db_session.expire_all()
    row = db_session.query(EvaluationDataset).one()
    assert "items" not in row.__dict__
    listed = client.get("/api/v1/knowledge-bases/kb-eval/evaluation-datasets", headers=HEADERS)
    assert listed.json()[0]["item_count"] == 10_000
    exported = client.get(
        f"/api/v1/knowledge-bases/kb-eval/evaluation-datasets/{dataset['dataset_uid']}/export", headers=HEADERS,
    )
    assert len(exported.text.splitlines()) == 10_000
    assert "items" not in row.__dict__


def test_legacy_physical_topic_delete_requires_evaluation_cleanup(client, db_session):
    topic = KnowledgeTopic(
        kb_uid="legacy-eval-kb", tenant_id="legacy-personal", owner_user_id="default-user",
        user_id="default-user", name="Legacy evaluation",
    )
    db_session.add(topic)
    dataset = EvaluationDataset(
        tenant_id=topic.tenant_id, kb_uid=topic.kb_uid, name="gold", created_by="default-user", source="generated",
    )
    db_session.add(dataset)
    db_session.flush()
    db_session.add(EvaluationRun(
        dataset_id=dataset.id, tenant_id=topic.tenant_id, kb_uid=topic.kb_uid,
        created_by="default-user", config={}, retrieval_config={}, embedding_profile={}, graph_config={},
        status="succeeded", progress_total=0,
    ))
    db_session.commit()
    response = client.delete(f"/api/v1/knowledge/topics/{topic.id}")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "topic_has_evaluations"


def test_export_stream_uses_and_closes_its_own_batch_session():
    from types import SimpleNamespace
    from backend.app.api.knowledge_evaluation import _stream_dataset_export
    closed = []
    batches = [[SimpleNamespace(ordinal=0, query="q", gold_chunk_uids=[], gold_answer=None)], []]
    class Query:
        def filter(self, *_args): return self
        def order_by(self, *_args): return self
        def limit(self, _limit): return self
        def all(self): return batches.pop(0)
    class StreamSession:
        def query(self, _model): return Query()
        def close(self): closed.append(True)
    generator = _stream_dataset_export(StreamSession, "dataset", "tenant", "kb")
    assert next(generator).strip()
    assert closed == [True]
    generator.close()
    assert closed == [True]
