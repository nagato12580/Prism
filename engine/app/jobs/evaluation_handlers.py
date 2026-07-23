"""Durable execution of a frozen knowledge evaluation run."""
from datetime import timedelta
from inspect import signature

from backend.app.models import EvaluationRun, EvaluationRunItem
from backend.app.schemas.knowledge_evaluation import RetrievalEvaluationConfig
from backend.app.services.knowledge_jobs import InvalidJobTransition, KnowledgeJobService
from engine.app.api.retrieval import AuthorizedKnowledgeScope, RetrievalRequest, execute_retrieval
from engine.app.evaluation.metrics import retrieval_metrics
from engine.app.retrieval.execution_control import (
    RetrievalCancelled, RetrievalDeadlineExceeded, RetrievalExecutionControl,
)


class _ItemRetrievalFailure(RuntimeError):
    pass


class _LostOwnership(RuntimeError):
    pass


class _CancellationRequested(RuntimeError):
    pass


HEARTBEAT_INTERVAL_SECONDS = 5
ITEM_BATCH_SIZE = 100


def _execute_with_heartbeats(request, scope, jobs, job, worker_id, lease, timeout_seconds):
    def heartbeat():
        try:
            jobs.heartbeat(job.id, worker_id, lease)
        except InvalidJobTransition as exc:
            raise _LostOwnership from exc

    def canceled():
        jobs.db.refresh(job)
        return job.cancel_requested_at is not None

    control = RetrievalExecutionControl.with_timeout(
        timeout_seconds,
        heartbeat_callback=heartbeat,
        cancel_callback=canceled,
        heartbeat_interval_seconds=HEARTBEAT_INTERVAL_SECONDS,
    )
    try:
        if "control" in signature(execute_retrieval).parameters:
            result = execute_retrieval(request, scope, control=control)
        else:
            result = execute_retrieval(request, scope)
        control.checkpoint()
        return result
    except RetrievalCancelled as exc:
        raise _CancellationRequested from exc


def _macro_metrics(metric_sums: dict[str, float], succeeded: int, failed: int) -> dict:
    metrics = {key: value / succeeded for key, value in metric_sums.items()} if succeeded else {}
    metrics.update({"succeeded_items": succeeded, "failed_items": failed})
    return metrics


def _fail_run(db, run: EvaluationRun | None) -> None:
    if run is None:
        return
    run.status = "failed"
    run.error_message = "evaluation run failed"
    db.commit()


def handle_evaluation(job_id: str, worker_id: str, db, jobs: KnowledgeJobService) -> dict:
    lease = timedelta(seconds=120)
    job = jobs.claim(job_id, worker_id, lease)
    if job is None:
        return {"status": "skipped"}
    run = None
    try:
        jobs.start(job_id, worker_id)
        run = db.get(EvaluationRun, job.resource_id)
        if run is None:
            jobs.fail(job_id, worker_id, "EVALUATION_RUN_NOT_FOUND", "Evaluation run not found", False)
            return {"status": "failed"}
        frozen = RetrievalEvaluationConfig.model_validate(run.config or {})
        scope = AuthorizedKnowledgeScope(
            tenant_id=run.tenant_id,
            kb_uid=run.kb_uid,
            index_generation=run.index_generation,
            graph_generation=run.graph_generation,
        )
        run.status = "running"
        run.error_message = None
        db.commit()
        succeeded = failed = current = 0
        metric_sums: dict[str, float] = {}
        last_ordinal = -1
        while True:
            batch = (
                db.query(EvaluationRunItem)
                .filter(EvaluationRunItem.run_id == run.id, EvaluationRunItem.ordinal > last_ordinal)
                .order_by(EvaluationRunItem.ordinal)
                .limit(ITEM_BATCH_SIZE)
                .all()
            )
            if not batch:
                break
            for item in batch:
                current += 1
                last_ordinal = item.ordinal
                db.refresh(job)
                if job.cancel_requested_at is not None:
                    raise _CancellationRequested
                try:
                    jobs.heartbeat(job_id, worker_id, lease)
                except InvalidJobTransition as exc:
                    raise _LostOwnership from exc
                try:
                    request = RetrievalRequest(
                        query=item.query,
                        mode=frozen.mode,
                        config={"top_k": frozen.top_k, "graph_hops": frozen.graph_hops},
                    )
                    response = _execute_with_heartbeats(
                        request, scope, jobs, job, worker_id, lease, frozen.timeout_seconds,
                    )
                    if response.status == "unavailable":
                        raise _ItemRetrievalFailure("retrieval unavailable")
                    if response.status == "invalid_request":
                        raise _ItemRetrievalFailure("invalid retrieval request")
                    warning_flags = tuple(warning.code for warning in response.warnings)
                    evidence_models = tuple(
                        row.model_copy(update={
                            "degradation_flags": tuple(dict.fromkeys((*row.degradation_flags, *warning_flags)))
                        }) if response.status == "degraded" else row
                        for row in response.evidence
                    )
                    item.evidence = [row.model_dump(mode="json") for row in evidence_models]
                    item.metrics = retrieval_metrics(
                        [row.chunk_uid for row in evidence_models], set(item.gold_chunk_uids or []),
                    )
                    for key, value in item.metrics.items():
                        metric_sums[key] = metric_sums.get(key, 0.0) + float(value)
                    item.status = "succeeded"
                    item.error_message = None
                    succeeded += 1
                except (_LostOwnership, _CancellationRequested):
                    raise
                except RetrievalDeadlineExceeded:
                    raise _ItemRetrievalFailure("retrieval deadline exceeded")
                except _ItemRetrievalFailure as exc:
                    item.status = "failed"; item.error_message = str(exc); item.evidence = None; item.metrics = None; failed += 1
                except Exception:
                    item.status = "failed"; item.error_message = "evaluation item failed"; item.evidence = None; item.metrics = None; failed += 1
                run.progress_current = current
                db.commit()
                jobs.progress(job_id, worker_id, current, run.progress_total, "evaluation")
            for item in batch:
                db.expunge(item)
        run.status = "failed" if failed and not succeeded else "succeeded_with_errors" if failed else "succeeded"
        run.metrics = _macro_metrics(metric_sums, succeeded, failed)
        db.commit()
        if run.status == "failed":
            jobs.fail(
                job_id,
                worker_id,
                "EVALUATION_ALL_ITEMS_FAILED",
                "All evaluation items failed",
                False,
            )
        else:
            jobs.succeed(job_id, worker_id, {"run_status": run.status, "succeeded": succeeded, "failed": failed})
        return {"status": run.status}
    except _LostOwnership:
        db.rollback()
        return {"status": "lost_ownership"}
    except _CancellationRequested:
        db.rollback()
        run = db.get(EvaluationRun, job.resource_id)
        if run is not None:
            run.status = "canceled"
            db.commit()
        try:
            jobs.cancel(job_id, worker_id)
        except InvalidJobTransition:
            pass
        return {"status": "canceled"}
    except Exception:
        db.rollback()
        try:
            run = db.get(EvaluationRun, job.resource_id)
            _fail_run(db, run)
        except Exception:
            db.rollback()
        try:
            current_job = db.get(type(job), job_id)
            if current_job is not None and current_job.status == "running":
                jobs.fail(job_id, worker_id, "EVALUATION_RUN_FAILED", "Evaluation run failed", False)
            elif current_job is not None and current_job.status == "claimed":
                current_job.status = "failed"
                current_job.error_code = "EVALUATION_RUN_FAILED"
                current_job.error_message = "Evaluation run failed"
                current_job.retryable = False
                db.commit()
        except Exception:
            db.rollback()
        return {"status": "failed"}
