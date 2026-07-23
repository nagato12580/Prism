from backend.app.models import (
    EvaluationDataset,
    EvaluationDatasetItem,
    EvaluationRun,
    EvaluationRunItem,
    KnowledgeJob,
    KnowledgeTopic,
)
from backend.app.services.knowledge_job_queue import enqueue_evaluation_job
from backend.app.services.knowledge_jobs import KnowledgeJobService
from backend.app.services.knowledge_jobs import InvalidJobTransition
from backend.app.utils.time import local_now
from engine.app.jobs import redis_queue
from engine.app.retrieval.evidence import ChannelProblem, Evidence, RetrievalResponse


class FakeRedis:
    def __init__(self):
        self.messages = []

    def lpush(self, queue, payload):
        self.messages.insert(0, (queue, payload))

    def brpop(self, queue, timeout=0):
        for index in range(len(self.messages) - 1, -1, -1):
            queued, payload = self.messages[index]
            if queued == queue:
                self.messages.pop(index)
                return queued, payload
        return None


def _make_run(db, *, config=None, golds=("c1", "c2")):
    topic = KnowledgeTopic(
        kb_uid="kb-eval", tenant_id="tenant", owner_user_id="owner", name="KB",
        active_index_generation="index-frozen", active_graph_generation="graph-frozen",
    )
    db.add(topic)
    dataset = EvaluationDataset(
        tenant_id="tenant", kb_uid="kb-eval", name="gold", created_by="owner", source="generated",
    )
    db.add(dataset)
    db.flush()
    source_items = []
    for ordinal, gold in enumerate(golds):
        source = EvaluationDatasetItem(
            dataset_id=dataset.id, tenant_id="tenant", kb_uid="kb-eval", ordinal=ordinal,
            query=f"q{ordinal}", gold_chunk_uids=[gold],
        )
        db.add(source)
        source_items.append(source)
    db.flush()
    run = EvaluationRun(
        dataset_id=dataset.id, tenant_id="tenant", kb_uid="kb-eval", created_by="owner",
        model=None, config=config or {"mode": "deep", "top_k": 7, "graph_hops": 2},
        retrieval_config={"top_k": 9}, embedding_profile={"model": "embed"}, graph_config={"mode": "fast"},
        index_generation="index-frozen", graph_generation="graph-frozen", progress_total=len(source_items),
    )
    db.add(run)
    db.flush()
    for source in source_items:
        db.add(EvaluationRunItem(
            run_id=run.id, dataset_item_id=source.id, tenant_id="tenant", kb_uid="kb-eval",
            ordinal=source.ordinal, query=source.query, gold_chunk_uids=list(source.gold_chunk_uids),
        ))
    db.commit()
    return run


def _evidence(chunk_uid, *, flags=()):
    return Evidence(
        tenant_id="tenant", kb_uid="kb-eval", file_uid="file-one", chunk_uid=chunk_uid,
        display_title="Title", excerpt="safe", rrf_score=1.0,
        index_generation="index-frozen", degradation_flags=flags,
    )


def _enqueue_pop_dispatch(db, monkeypatch, fake_retrieval):
    from engine.app.jobs import evaluation_handlers, worker

    run = db.query(EvaluationRun).one()
    redis = FakeRedis()
    job = enqueue_evaluation_job(db, redis, run.id, queue_name="evaluation")
    popped = redis_queue.pop_job(redis, "evaluation", timeout_seconds=0)
    assert popped == job.id
    monkeypatch.setattr(evaluation_handlers, "execute_retrieval", fake_retrieval)
    result = worker.dispatch_typed_job(db, popped, "worker-one")
    db.expire_all()
    return result, db.get(EvaluationRun, run.id), db.get(KnowledgeJob, job.id)


def test_redis_worker_handler_writes_macro_metrics_and_frozen_task6_config(db_session, monkeypatch):
    _make_run(db_session)
    requests = []

    def retrieve(request, scope):
        requests.append((request, scope))
        if request.query == "q0":
            return RetrievalResponse(
                status="degraded",
                evidence=[_evidence("c1", flags=("BM25_UNAVAILABLE",))],
                warnings=[ChannelProblem(code="BM25_UNAVAILABLE")],
            )
        return RetrievalResponse(status="no_hits")

    result, run, job = _enqueue_pop_dispatch(db_session, monkeypatch, retrieve)

    assert result == {"status": "succeeded"}
    assert job.status == "succeeded"
    assert run.status == "succeeded"
    assert run.progress_current == 2
    assert run.metrics == {
        "recall@1": 0.5, "recall@3": 0.5, "recall@5": 0.5, "recall@10": 0.5,
        "mrr": 0.5, "ndcg": 0.5, "succeeded_items": 2, "failed_items": 0,
    }
    assert all(request.mode == "deep" for request, _scope in requests)
    assert all(request.config.top_k == 7 and request.config.graph_hops == 2 for request, _scope in requests)
    assert all(scope.index_generation == "index-frozen" and scope.graph_generation == "graph-frozen" for _request, scope in requests)
    items = db_session.query(EvaluationRunItem).order_by(EvaluationRunItem.ordinal).all()
    assert items[0].evidence[0]["degradation_flags"] == ["BM25_UNAVAILABLE"]
    assert items[1].status == "succeeded"
    assert items[1].metrics["recall@1"] == 0.0


def test_unavailable_is_item_failure_and_partial_run_succeeds_with_errors(db_session, monkeypatch):
    _make_run(db_session)

    def retrieve(request, _scope):
        if request.query == "q0":
            return RetrievalResponse(status="ok", evidence=[_evidence("c1")])
        return RetrievalResponse(
            status="unavailable",
            warnings=[ChannelProblem(code="RETRIEVAL_UNAVAILABLE", message="internal secret", retryable=True)],
        )

    result, run, job = _enqueue_pop_dispatch(db_session, monkeypatch, retrieve)

    assert result == {"status": "succeeded_with_errors"}
    assert run.status == "succeeded_with_errors"
    assert job.status == "succeeded"
    assert run.metrics["recall@1"] == 1.0
    assert run.metrics["failed_items"] == 1
    failed = db_session.query(EvaluationRunItem).filter_by(status="failed").one()
    assert failed.error_message == "retrieval unavailable"
    assert "secret" not in failed.error_message


def test_invalid_request_all_failed_marks_run_and_job_failed(db_session, monkeypatch):
    _make_run(db_session, golds=("c1",))

    result, run, job = _enqueue_pop_dispatch(
        db_session,
        monkeypatch,
        lambda _request, _scope: RetrievalResponse(status="invalid_request"),
    )

    assert result == {"status": "failed"}
    assert run.status == "failed"
    assert run.metrics == {"succeeded_items": 0, "failed_items": 1}
    assert job.status == "failed"
    assert job.error_code == "EVALUATION_ALL_ITEMS_FAILED"


def test_cancel_requested_stops_before_first_item_and_cancels_job(db_session, monkeypatch):
    run = _make_run(db_session)
    redis = FakeRedis()
    job = enqueue_evaluation_job(db_session, redis, run.id, queue_name="evaluation")
    KnowledgeJobService(db_session).request_cancel(job.id, "owner")
    called = []
    from engine.app.jobs import evaluation_handlers, worker
    monkeypatch.setattr(evaluation_handlers, "execute_retrieval", lambda *_args: called.append(True))

    result = worker.dispatch_typed_job(db_session, redis_queue.pop_job(redis, "evaluation", 0), "worker-one")
    db_session.expire_all()

    assert result == {"status": "canceled"}
    assert called == []
    assert db_session.get(EvaluationRun, run.id).status == "canceled"
    assert db_session.get(KnowledgeJob, job.id).status == "canceled"
    assert db_session.query(EvaluationRunItem).filter_by(status="queued").count() == 2


def test_scope_initialization_failure_never_leaves_run_or_job_running(db_session, monkeypatch):
    run = _make_run(db_session, golds=("c1",))
    redis = FakeRedis()
    job = enqueue_evaluation_job(db_session, redis, run.id, queue_name="evaluation")
    from engine.app.jobs import evaluation_handlers, worker
    monkeypatch.setattr(
        evaluation_handlers,
        "AuthorizedKnowledgeScope",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("scope secret")),
    )

    result = worker.dispatch_typed_job(db_session, redis_queue.pop_job(redis, "evaluation", 0), "worker-one")
    db_session.expire_all()

    assert result == {"status": "failed"}
    assert db_session.get(EvaluationRun, run.id).status == "failed"
    assert db_session.get(EvaluationRun, run.id).error_message == "evaluation run failed"
    stored_job = db_session.get(KnowledgeJob, job.id)
    assert stored_job.status == "failed"
    assert stored_job.error_code == "EVALUATION_RUN_FAILED"
    assert "secret" not in (stored_job.error_message or "")


def test_run_lookup_initialization_failure_never_leaves_job_running(db_session, monkeypatch):
    run = _make_run(db_session, golds=("c1",))
    redis = FakeRedis()
    job = enqueue_evaluation_job(db_session, redis, run.id, queue_name="evaluation")
    from engine.app.jobs import worker
    original_get = db_session.get
    failed_once = False

    def flaky_get(model, identity, *args, **kwargs):
        nonlocal failed_once
        if model is EvaluationRun and not failed_once:
            failed_once = True
            raise RuntimeError("initialization secret")
        return original_get(model, identity, *args, **kwargs)

    monkeypatch.setattr(db_session, "get", flaky_get)

    result = worker.dispatch_typed_job(db_session, redis_queue.pop_job(redis, "evaluation", 0), "worker-one")
    db_session.expire_all()

    assert result == {"status": "failed"}
    assert original_get(EvaluationRun, run.id).status == "failed"
    stored_job = original_get(KnowledgeJob, job.id)
    assert stored_job.status == "failed"
    assert stored_job.error_code == "EVALUATION_RUN_FAILED"


def test_long_retrieval_heartbeats_lease(db_session, monkeypatch):
    import time
    from engine.app.jobs import evaluation_handlers
    run = _make_run(db_session, golds=("c1",))
    redis = FakeRedis()
    job = enqueue_evaluation_job(db_session, redis, run.id, queue_name="evaluation")
    jobs = KnowledgeJobService(db_session)
    heartbeats = []
    original = jobs.heartbeat
    def heartbeat(*args, **kwargs):
        heartbeats.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(jobs, "heartbeat", heartbeat)
    monkeypatch.setattr(evaluation_handlers, "HEARTBEAT_INTERVAL_SECONDS", 0.02)
    def retrieve(_request, _scope, control):
        for _ in range(4):
            time.sleep(0.025)
            control.checkpoint()
        return RetrievalResponse(status="ok", evidence=[_evidence("c1")])
    monkeypatch.setattr(evaluation_handlers, "execute_retrieval", retrieve)
    result = evaluation_handlers.handle_evaluation(job.id, "worker-one", db_session, jobs)
    assert result == {"status": "succeeded"}
    assert len(heartbeats) >= 2


def test_lost_heartbeat_ownership_stops_without_terminal_write(db_session, monkeypatch):
    import time
    from engine.app.jobs import evaluation_handlers
    run = _make_run(db_session, golds=("c1",))
    redis = FakeRedis()
    job = enqueue_evaluation_job(db_session, redis, run.id, queue_name="evaluation")
    jobs = KnowledgeJobService(db_session)
    def lose(*_args, **_kwargs):
        stored = db_session.get(KnowledgeJob, job.id)
        stored.lease_owner = "other-worker"
        db_session.commit()
        raise InvalidJobTransition("lost")
    monkeypatch.setattr(jobs, "heartbeat", lose)
    monkeypatch.setattr(evaluation_handlers, "HEARTBEAT_INTERVAL_SECONDS", 0.01)
    def retrieve(_request, _scope, control):
        time.sleep(0.02)
        control.checkpoint()
        return RetrievalResponse(status="ok", evidence=[_evidence("c1")])
    monkeypatch.setattr(evaluation_handlers, "execute_retrieval", retrieve)
    result = evaluation_handlers.handle_evaluation(job.id, "worker-one", db_session, jobs)
    db_session.expire_all()
    assert result == {"status": "lost_ownership"}
    assert db_session.get(EvaluationRun, run.id).status == "running"
    assert db_session.query(EvaluationRunItem).one().status == "queued"
    assert db_session.get(KnowledgeJob, job.id).status == "running"


def test_expired_evaluation_job_is_requeued_and_republished(db_session, monkeypatch):
    from datetime import timedelta
    from engine.app.jobs import worker
    run = _make_run(db_session, golds=("c1",))
    redis = FakeRedis()
    job = enqueue_evaluation_job(db_session, redis, run.id, queue_name="evaluation")
    jobs = KnowledgeJobService(db_session)
    jobs.claim(job.id, "dead-worker", timedelta(seconds=30))
    jobs.start(job.id, "dead-worker")
    stored = db_session.get(KnowledgeJob, job.id)
    stored.lease_expires_at = local_now() - timedelta(seconds=1)
    db_session.commit()
    published = []
    monkeypatch.setattr(worker, "_Session", lambda: db_session)
    monkeypatch.setattr(worker, "_publish_job_and_mark_enqueued", lambda db, row: published.append(row.id))
    assert worker.recover_expired_evaluation_jobs() == 1
    db_session.expire_all()
    recovered = db_session.get(KnowledgeJob, job.id)
    assert recovered.status == "queued"
    assert recovered.stage == "recovered"
    assert recovered.lease_owner is None
    assert recovered.lease_expires_at is None
    assert published == [job.id]


def test_expired_claimed_cancel_requested_job_finishes_canceled_without_publish(db_session, monkeypatch):
    from datetime import timedelta
    from engine.app.jobs import worker
    run = _make_run(db_session, golds=("c1",))
    redis = FakeRedis()
    job = enqueue_evaluation_job(db_session, redis, run.id, queue_name="evaluation")
    job_id = job.id
    run_id = run.id
    jobs = KnowledgeJobService(db_session)
    jobs.claim(job.id, "dead-worker", timedelta(seconds=30))
    stored = db_session.get(KnowledgeJob, job.id)
    stored.cancel_requested_at = local_now()
    stored.lease_expires_at = local_now() - timedelta(seconds=1)
    db_session.commit()
    published = []
    monkeypatch.setattr(worker, "_Session", lambda: db_session)
    monkeypatch.setattr(worker, "_publish_job_and_mark_enqueued", lambda _db, row: published.append(row.id))
    assert worker.recover_expired_evaluation_jobs() == 0
    db_session.expire_all()
    assert db_session.get(KnowledgeJob, job_id).status == "canceled"
    assert db_session.get(EvaluationRun, run_id).status == "canceled"
    assert published == []


def test_handler_uses_limited_keyset_batches(db_session, monkeypatch):
    from sqlalchemy.orm import Query
    from engine.app.jobs import evaluation_handlers
    run = _make_run(db_session, golds=tuple(f"c{i}" for i in range(205)))
    redis = FakeRedis()
    job = enqueue_evaluation_job(db_session, redis, run.id, queue_name="evaluation")
    monkeypatch.setattr(
        evaluation_handlers, "execute_retrieval",
        lambda request, _scope: RetrievalResponse(status="no_hits"),
    )
    original_all = Query.all
    def guarded_all(query):
        descriptions = {item.get("entity") for item in query.column_descriptions}
        if EvaluationRunItem in descriptions and query._limit_clause is None:
            raise AssertionError("evaluation items must never be loaded without a batch limit")
        return original_all(query)
    monkeypatch.setattr(Query, "all", guarded_all)
    result = evaluation_handlers.handle_evaluation(job.id, "worker-one", db_session, KnowledgeJobService(db_session))
    assert result == {"status": "succeeded"}
    assert db_session.get(EvaluationRun, run.id).progress_current == 205
    assert db_session.get(EvaluationRun, run.id).metrics["recall@1"] == 0.0


def test_blocking_client_deadline_stops_run_without_background_thread_or_next_item(db_session, monkeypatch):
    import threading
    import time
    from engine.app.jobs import evaluation_handlers
    from engine.app.retrieval.execution_control import RetrievalExecutionControl
    run = _make_run(db_session, config={"timeout_seconds": 30}, golds=("c1", "c2"))
    redis = FakeRedis()
    job = enqueue_evaluation_job(db_session, redis, run.id, queue_name="evaluation")
    calls = []
    original = RetrievalExecutionControl.with_timeout
    monkeypatch.setattr(
        RetrievalExecutionControl, "with_timeout",
        classmethod(lambda cls, _timeout, **kwargs: original(0.01, **kwargs)),
    )
    def blocking_retrieval(request, _scope, control):
        calls.append(request.query)
        timeout = control.remaining_timeout(1)
        time.sleep(timeout + 0.01)  # fake external client honors the supplied hard timeout
        control.checkpoint()
    monkeypatch.setattr(evaluation_handlers, "execute_retrieval", blocking_retrieval)
    result = evaluation_handlers.handle_evaluation(job.id, "worker-one", db_session, KnowledgeJobService(db_session))
    assert result == {"status": "failed"}
    assert calls == ["q0"]
    assert not any(thread.name.startswith("evaluation-retrieval") for thread in threading.enumerate())
    assert db_session.get(KnowledgeJob, job.id).status == "failed"
