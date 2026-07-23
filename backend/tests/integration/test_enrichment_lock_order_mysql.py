from datetime import timedelta
import threading

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from backend.app.api.knowledge_enrichment import cancel_enrichment_job
from backend.app.models import KnowledgeJob, KnowledgeTopic
from backend.app.security.actor import ActorContext
from backend.app.services.knowledge_jobs import JobCommand, KnowledgeJobService
from engine.app.jobs import enrichment_handlers


pytestmark = pytest.mark.mysql


def test_worker_and_cancel_use_topic_then_job_without_deadlock(mysql_engine, monkeypatch):
    Session = sessionmaker(bind=mysql_engine, autocommit=False, autoflush=False)
    setup = Session()
    topic_id = None
    job_id = None
    try:
        topic = KnowledgeTopic(
            tenant_id="tenant-lock-order",
            owner_user_id="alice",
            user_id="alice",
            name="Lock order",
            active_index_generation="index-1",
            active_graph_generation="graph-1",
            mindmap={"status": "generating", "version": 0, "input_revision": 0, "nodes": []},
        )
        setup.add(topic)
        setup.commit()
        topic_id = topic.id
        kb_uid = topic.kb_uid
        tenant_id = topic.tenant_id
        jobs = KnowledgeJobService(setup)
        job = jobs.create(
            JobCommand(
                "mindmap_generation",
                topic.tenant_id,
                topic.kb_uid,
                None,
                {
                    "index_generation": "index-1",
                    "graph_generation": "graph-1",
                    "expected_version": 0,
                    "expected_input_revision": 0,
                },
            ),
            "mysql-enrichment-lock-order",
        )
        job_id = job.id
        jobs.claim(job.id, "worker-lock-order", timedelta(seconds=30))
        jobs.start(job.id, "worker-lock-order")

        topic_locked = threading.Event()
        cancel_updated_job = threading.Event()
        results = []
        errors = []
        original_request_cancel = KnowledgeJobService.request_cancel

        def observed_request_cancel(self, *args, **kwargs):
            result = original_request_cancel(self, *args, **kwargs)
            cancel_updated_job.set()
            return result

        monkeypatch.setattr(KnowledgeJobService, "request_cancel", observed_request_cancel)

        def worker_terminal():
            db = Session()
            try:
                db.execute(text("SET SESSION innodb_lock_wait_timeout=5"))
                locked_topic = (
                    db.query(KnowledgeTopic)
                    .filter_by(id=topic_id)
                    .with_for_update()
                    .one()
                )
                topic_locked.set()
                cancel_updated_job.wait(timeout=1.0)
                locked_topic.mindmap = {
                    **dict(locked_topic.mindmap or {}),
                    "status": "ready",
                }
                KnowledgeJobService(db).succeed(
                    job_id,
                    "worker-lock-order",
                    {"version": 1},
                    commit=False,
                )
                db.commit()
                results.append("worker-succeeded")
            except Exception as exc:
                db.rollback()
                errors.append(("worker", exc))
            finally:
                db.close()

        def request_cancel():
            db = Session()
            try:
                db.execute(text("SET SESSION innodb_lock_wait_timeout=5"))
                assert topic_locked.wait(timeout=5)
                response = cancel_enrichment_job(
                    kb_uid,
                    job_id,
                    ActorContext(actor_id="alice", tenant_id=tenant_id),
                    db,
                )
                results.append(f"cancel-{response['job']['status']}")
            except Exception as exc:
                db.rollback()
                errors.append(("cancel", exc))
            finally:
                db.close()

        worker_thread = threading.Thread(target=worker_terminal)
        cancel_thread = threading.Thread(target=request_cancel)
        worker_thread.start()
        cancel_thread.start()
        worker_thread.join(timeout=10)
        cancel_thread.join(timeout=10)

        assert not worker_thread.is_alive(), "worker did not finish within lock-order timeout"
        assert not cancel_thread.is_alive(), "cancel did not finish within lock-order timeout"
        assert errors == []
        assert "worker-succeeded" in results

        setup.rollback()  # end the pre-thread REPEATABLE READ snapshot
        setup.expire_all()
        final_job = setup.get(KnowledgeJob, job_id)
        assert final_job.status in {"succeeded", "canceled"}
    finally:
        setup.rollback()
        if job_id is not None:
            setup.query(KnowledgeJob).filter_by(id=job_id).delete(synchronize_session=False)
        if topic_id is not None:
            setup.query(KnowledgeTopic).filter_by(id=topic_id).delete(synchronize_session=False)
        setup.commit()
        setup.close()


def test_cancel_committed_after_worker_preread_wins_terminal_race(mysql_engine, monkeypatch):
    Session = sessionmaker(bind=mysql_engine, autocommit=False, autoflush=False)
    setup = Session()
    topic_id = None
    job_id = None
    try:
        topic = KnowledgeTopic(
            tenant_id="tenant-cancel-wins",
            owner_user_id="alice",
            user_id="alice",
            name="Cancel wins",
            active_index_generation="index-1",
            active_graph_generation="graph-1",
            mindmap={"status": "generating", "version": 0, "input_revision": 0, "nodes": []},
        )
        setup.add(topic)
        setup.commit()
        topic_id = topic.id
        kb_uid = topic.kb_uid
        tenant_id = topic.tenant_id
        job = KnowledgeJobService(setup).create(
            JobCommand(
                "mindmap_generation",
                tenant_id,
                kb_uid,
                None,
                {
                    "index_generation": "index-1",
                    "graph_generation": "graph-1",
                    "model": "m",
                    "prompt_version": "v1",
                    "expected_version": 0,
                    "expected_input_revision": 0,
                },
            ),
            "mysql-cancel-wins-after-preread",
        )
        job_id = job.id

        before_worker_topic_lock = threading.Event()
        cancel_committed = threading.Event()
        results = []
        errors = []
        original_locked_topic = enrichment_handlers._locked_topic

        def pause_after_worker_preread(*args, **kwargs):
            before_worker_topic_lock.set()
            assert cancel_committed.wait(timeout=5)
            return original_locked_topic(*args, **kwargs)

        monkeypatch.setattr(enrichment_handlers, "_locked_topic", pause_after_worker_preread)
        monkeypatch.setattr(
            enrichment_handlers,
            "call_llm",
            lambda *args, **kwargs: {"nodes": [{"id": "old-output", "title": "Wrong", "children": []}]},
        )

        def run_worker():
            db = Session()
            try:
                db.execute(text("SET SESSION innodb_lock_wait_timeout=5"))
                result = enrichment_handlers.handle_enrichment(
                    job_id,
                    "worker-cancel-wins",
                    db,
                    KnowledgeJobService(db),
                )
                results.append(("worker", result))
            except Exception as exc:
                db.rollback()
                errors.append(("worker", exc))
            finally:
                db.close()

        def run_cancel():
            db = Session()
            try:
                db.execute(text("SET SESSION innodb_lock_wait_timeout=5"))
                assert before_worker_topic_lock.wait(timeout=5)
                response = cancel_enrichment_job(
                    kb_uid,
                    job_id,
                    ActorContext(actor_id="alice", tenant_id=tenant_id),
                    db,
                )
                results.append(("cancel", response))
                cancel_committed.set()
            except Exception as exc:
                db.rollback()
                errors.append(("cancel", exc))
                cancel_committed.set()
            finally:
                db.close()

        worker_thread = threading.Thread(target=run_worker)
        cancel_thread = threading.Thread(target=run_cancel)
        worker_thread.start()
        cancel_thread.start()
        worker_thread.join(timeout=10)
        cancel_thread.join(timeout=10)

        assert not worker_thread.is_alive(), "worker did not finish cancel-wins race"
        assert not cancel_thread.is_alive(), "cancel did not finish cancel-wins race"
        assert errors == []
        assert ("worker", {"status": "canceled"}) in results

        setup.rollback()
        setup.expire_all()
        final_job = setup.get(KnowledgeJob, job_id)
        final_topic = setup.get(KnowledgeTopic, topic_id)
        assert final_job.status == "canceled"
        assert final_topic.mindmap["status"] == "stale"
        assert final_topic.mindmap["nodes"] != [{"id": "old-output", "title": "Wrong", "children": []}]
    finally:
        setup.rollback()
        if job_id is not None:
            setup.query(KnowledgeJob).filter_by(id=job_id).delete(synchronize_session=False)
        if topic_id is not None:
            setup.query(KnowledgeTopic).filter_by(id=topic_id).delete(synchronize_session=False)
        setup.commit()
        setup.close()
