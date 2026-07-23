import io
import zipfile
import pytest

from backend.app.models import KnowledgeFile, KnowledgeItem, KnowledgeJob, KnowledgeTopic


def _headers(actor="alice", tenant="tenant-a"):
    return {"X-Prism-Actor": actor, "X-Prism-Tenant": tenant}


def _topic(db):
    topic = KnowledgeTopic(
        tenant_id="tenant-a",
        owner_user_id="alice",
        name="API KB",
        active_index_generation="index-11",
        active_graph_generation="graph-5",
    )
    db.add(topic)
    db.commit()
    return topic


def test_empty_enrichment_responses_expose_zero_input_revision(client, db_session):
    topic = _topic(db_session)

    mindmap = client.get(
        f"/api/v1/knowledge-bases/{topic.kb_uid}/mindmap",
        headers=_headers(),
    )
    questions = client.get(
        f"/api/v1/knowledge-bases/{topic.kb_uid}/sample-questions",
        headers=_headers(),
    )

    assert mindmap.status_code == 200
    assert questions.status_code == 200
    assert mindmap.json()["mindmap"]["input_revision"] == 0
    assert questions.json()["sample_questions"]["input_revision"] == 0


def test_legacy_enrichment_responses_default_missing_input_revision_to_zero(client, db_session):
    topic = _topic(db_session)
    topic.mindmap = {"status": "ready", "version": 1, "nodes": []}
    topic.sample_questions = {"status": "ready", "version": 1, "questions": []}
    db_session.commit()

    mindmap = client.get(
        f"/api/v1/knowledge-bases/{topic.kb_uid}/mindmap",
        headers=_headers(),
    ).json()["mindmap"]
    questions = client.get(
        f"/api/v1/knowledge-bases/{topic.kb_uid}/sample-questions",
        headers=_headers(),
    ).json()["sample_questions"]

    assert mindmap["input_revision"] == 0
    assert questions["input_revision"] == 0


def test_generate_questions_authorizes_persists_snapshot_and_actually_enqueues(client, db_session, monkeypatch):
    import backend.app.api.knowledge_enrichment as api

    topic = _topic(db_session)
    published = []
    monkeypatch.setattr(api, "_publish_job_id", lambda job_id: published.append(job_id))

    denied = client.post(
        f"/api/v1/knowledge-bases/{topic.kb_uid}/sample-questions/generate",
        headers=_headers(actor="mallory"),
        json={"model": "public-model", "prompt_version": "questions-v2", "idempotency_key": "request-1"},
    )
    response = client.post(
        f"/api/v1/knowledge-bases/{topic.kb_uid}/sample-questions/generate",
        headers=_headers(),
        json={"model": "public-model", "prompt_version": "questions-v2", "idempotency_key": "request-1"},
    )

    assert denied.status_code == 403
    assert response.status_code == 202
    body = response.json()
    assert body["job"]["job_type"] == "sample_questions_generation"
    assert body["job"]["status"] == "queued"
    assert published == [body["job"]["id"]]
    job = db_session.get(KnowledgeJob, body["job"]["id"])
    assert {key: job.payload[key] for key in (
        "index_generation", "graph_generation", "model", "prompt_version",
    )} == {
        "index_generation": "index-11",
        "graph_generation": "graph-5",
        "model": "public-model",
        "prompt_version": "questions-v2",
    }
    assert job.payload["expected_version"] == 0
    assert job.payload["expected_input_revision"] == 0
    assert len(job.payload["request_fingerprint"]) == 64
    assert topic.sample_questions["status"] == "generating"


def test_generation_is_idempotent_and_request_dto_forbids_unknown_fields(client, db_session, monkeypatch):
    import backend.app.api.knowledge_enrichment as api

    topic = _topic(db_session)
    monkeypatch.setattr(api, "_publish_job_id", lambda job_id: None)
    url = f"/api/v1/knowledge-bases/{topic.kb_uid}/mindmap/generate"
    request = {"model": "public-model", "prompt_version": "mindmap-v1", "idempotency_key": "same-request"}

    first = client.post(url, headers=_headers(), json=request)
    second = client.post(url, headers=_headers(), json=request)
    invalid = client.post(url, headers=_headers(), json={**request, "provider": "forbidden"})

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["job"]["id"] == second.json()["job"]["id"]
    assert invalid.status_code == 422


def test_terminal_idempotent_replay_preserves_snapshot_and_payload_conflict_is_409(client, db_session, monkeypatch):
    import backend.app.api.knowledge_enrichment as api

    topic = _topic(db_session)
    topic.mindmap = {"status": "ready", "version": 4, "nodes": []}
    topic.mindmap_version = 4
    db_session.commit()
    monkeypatch.setattr(api, "_publish_job_id", lambda job_id: None)
    request = {"model": "model-a", "prompt_version": "v1", "idempotency_key": "terminal-replay"}
    created = client.post(f"/api/v1/knowledge-bases/{topic.kb_uid}/mindmap/generate", headers=_headers(), json=request)
    job = db_session.get(KnowledgeJob, created.json()["job"]["id"])
    for status in ("succeeded", "failed", "canceled"):
        job.status = status
        topic.mindmap = {"status": "ready", "version": 4, "nodes": [{"id": status, "children": []}]}
        db_session.commit()
        replay = client.post(f"/api/v1/knowledge-bases/{topic.kb_uid}/mindmap/generate", headers=_headers(), json=request)
        db_session.refresh(topic)
        assert replay.status_code == 202
        assert replay.json()["job"]["status"] == status
        assert topic.mindmap["status"] == "ready"
        assert topic.mindmap["nodes"][0]["id"] == status
    conflict = client.post(
        f"/api/v1/knowledge-bases/{topic.kb_uid}/mindmap/generate",
        headers=_headers(),
        json={**request, "model": "model-b"},
    )
    assert conflict.status_code == 409


def test_enrichment_job_cancel_is_authorized_and_marks_durable_request(client, db_session, monkeypatch):
    import backend.app.api.knowledge_enrichment as api

    topic = _topic(db_session)
    monkeypatch.setattr(api, "_publish_job_id", lambda job_id: None)
    created = client.post(
        f"/api/v1/knowledge-bases/{topic.kb_uid}/mindmap/generate",
        headers=_headers(),
        json={"model": "public-model", "prompt_version": "v1", "idempotency_key": "cancel-me"},
    ).json()

    denied = client.post(
        f"/api/v1/knowledge-bases/{topic.kb_uid}/jobs/{created['job']['id']}/cancel",
        headers=_headers(actor="mallory"),
    )
    response = client.post(
        f"/api/v1/knowledge-bases/{topic.kb_uid}/jobs/{created['job']['id']}/cancel",
        headers=_headers(),
    )

    assert denied.status_code == 403
    assert response.status_code == 200
    job = db_session.get(KnowledgeJob, created["job"]["id"])
    assert job.cancel_requested_at is not None
    assert job.canceled_by == "alice"
    db_session.refresh(topic)
    assert topic.mindmap["status"] == "stale"
    assert topic.mindmap["stale_reason"] == "generation_canceled"
    assert topic.mindmap["input_revision"] == 0


def test_cancel_locks_topic_before_requesting_job_cancel(db_session, monkeypatch):
    import backend.app.api.knowledge_enrichment as api
    from backend.app.security.actor import ActorContext
    from backend.app.services.knowledge_jobs import JobCommand, KnowledgeJobService

    topic = _topic(db_session)
    topic.mindmap = {"status": "generating", "version": 0, "input_revision": 0, "nodes": []}
    db_session.commit()
    job = KnowledgeJobService(db_session).create(
        JobCommand("mindmap_generation", topic.tenant_id, topic.kb_uid, None, {}),
        "cancel-lock-order",
    )
    order = []

    def lock_topic(db, tenant_id, kb_uid):
        order.append("topic")
        return db.query(KnowledgeTopic).filter_by(
            tenant_id=tenant_id,
            kb_uid=kb_uid,
            deleted_at=None,
        ).with_for_update().one()

    def request_cancel(self, job_id, canceled_by, *, commit=True):
        order.append("job-update")
        assert commit is False
        return db_session.get(KnowledgeJob, job_id)

    def lock_job(db, job_id, tenant_id, kb_uid):
        order.append("job-read")
        return db.query(KnowledgeJob).filter_by(
            id=job_id,
            tenant_id=tenant_id,
            kb_uid=kb_uid,
        ).populate_existing().with_for_update().one_or_none()

    monkeypatch.setattr(api, "_lock_topic_for_cancel", lock_topic, raising=False)
    monkeypatch.setattr(api, "_lock_job_for_cancel", lock_job, raising=False)
    monkeypatch.setattr(KnowledgeJobService, "request_cancel", request_cancel)

    api.cancel_enrichment_job(
        topic.kb_uid,
        job.id,
        ActorContext(actor_id="alice", tenant_id="tenant-a"),
        db_session,
    )

    assert order == ["topic", "job-read", "job-update"]


@pytest.mark.parametrize("terminal_status", ["succeeded", "failed", "canceled"])
def test_cancel_terminal_race_is_idempotent_after_current_job_read(
    db_session, monkeypatch, terminal_status
):
    from types import SimpleNamespace
    import backend.app.api.knowledge_enrichment as api
    from backend.app.security.actor import ActorContext
    from backend.app.services.knowledge_jobs import JobCommand, KnowledgeJobService

    topic = _topic(db_session)
    job = KnowledgeJobService(db_session).create(
        JobCommand("mindmap_generation", topic.tenant_id, topic.kb_uid, None, {}),
        f"terminal-race-{terminal_status}",
    )
    current = SimpleNamespace(
        id=job.id,
        job_type=job.job_type,
        status=terminal_status,
        stage=job.stage or "",
    )
    order = []

    monkeypatch.setattr(
        api,
        "_lock_topic_for_cancel",
        lambda db, tenant_id, kb_uid: order.append("topic") or topic,
    )
    monkeypatch.setattr(
        api,
        "_lock_job_for_cancel",
        lambda db, job_id, tenant_id, kb_uid: order.append("job-read") or current,
        raising=False,
    )
    monkeypatch.setattr(
        KnowledgeJobService,
        "request_cancel",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("terminal job must not be updated")),
    )

    response = api.cancel_enrichment_job(
        topic.kb_uid,
        job.id,
        ActorContext(actor_id="alice", tenant_id="tenant-a"),
        db_session,
    )

    assert order == ["topic", "job-read"]
    assert response["job"]["status"] == terminal_status


def test_mindmap_diff_delete_is_synchronous_but_added_files_enqueue(client, db_session, monkeypatch):
    import backend.app.api.knowledge_enrichment as api

    topic = _topic(db_session)
    topic.mindmap = {
        "status": "ready",
        "version": 1,
        "nodes": [{"id": "file-a", "file_uid": "file-a", "title": "A", "children": []}],
    }
    topic.mindmap_version = 1
    db_session.commit()
    published = []
    monkeypatch.setattr(api, "_publish_job_id", lambda job_id: published.append(job_id))

    deleted = client.patch(
        f"/api/v1/knowledge-bases/{topic.kb_uid}/mindmap",
        headers=_headers(),
        json={"added": [], "deleted": ["file-a"], "renamed": []},
    )
    added = client.patch(
        f"/api/v1/knowledge-bases/{topic.kb_uid}/mindmap",
        headers=_headers(),
        json={"added": ["file-b"], "deleted": [], "renamed": []},
    )

    assert deleted.status_code == 200
    assert deleted.json()["mindmap"]["nodes"] == []
    assert published == [added.json()["job"]["id"]]
    assert added.status_code == 202


def test_mindmap_diff_uses_expected_version_and_simple_add_needs_no_job(client, db_session, monkeypatch):
    import backend.app.api.knowledge_enrichment as api

    topic = _topic(db_session)
    topic.mindmap = {"status": "ready", "version": 2, "input_revision": 7, "nodes": []}
    topic.mindmap_version = 2
    db_session.commit()
    published = []
    monkeypatch.setattr(api, "_publish_job_id", lambda job_id: published.append(job_id))
    url = f"/api/v1/knowledge-bases/{topic.kb_uid}/mindmap"

    stale = client.patch(url, headers={**_headers(), "If-Match": "1"}, json={"expected_version": 1, "added": [], "deleted": [], "renamed": []})
    simple = client.patch(
        url,
        headers={**_headers(), "If-Match": "2"},
        json={
            "expected_version": 2,
            "added": [{"file_uid": "file-new", "title": "New", "parent_id": None, "relative_path": "guide/new.md"}],
            "deleted": [],
            "renamed": [],
        },
    )

    assert stale.status_code == 409
    assert simple.status_code == 200
    assert simple.json()["job"] is None
    assert simple.json()["mindmap"]["nodes"][0]["file_uid"] == "file-new"
    assert simple.json()["mindmap"]["input_revision"] == 7
    assert published == []


@pytest.mark.parametrize(
    ("job_type", "reason", "stale_kwargs"),
    [
        ("sample_questions_generation", "file_added", {}),
        ("sample_questions_generation", "file_content_changed", {}),
        ("sample_questions_generation", "file_deleted", {"deleted_file_uids": ["file-a"]}),
        (
            "sample_questions_generation",
            "file_renamed",
            {"renamed": [{"file_uid": "file-a", "title": "Renamed"}]},
        ),
        ("mindmap_generation", "file_added", {}),
        ("mindmap_generation", "file_content_changed", {}),
    ],
)
def test_generation_discards_output_when_file_input_changes_during_llm(
    db_session, monkeypatch, job_type, reason, stale_kwargs
):
    from backend.app.services.knowledge_jobs import JobCommand, KnowledgeJobService
    from engine.app.jobs import enrichment_handlers
    from engine.app.knowledge.enrichment import mark_enrichment_stale

    topic = _topic(db_session)
    topic.mindmap = {
        "status": "generating",
        "version": 2,
        "input_revision": 10,
        "nodes": [{"id": "file-a", "file_uid": "file-a", "title": "A", "children": []}],
    }
    topic.mindmap_version = 2
    topic.sample_questions = {
        "status": "generating",
        "version": 4,
        "input_revision": 20,
        "questions": ["Previous?"],
    }
    topic.sample_questions_version = 4
    db_session.commit()
    expected_version = 2 if job_type == "mindmap_generation" else 4
    expected_input_revision = 10 if job_type == "mindmap_generation" else 20
    job = KnowledgeJobService(db_session).create(
        JobCommand(job_type, topic.tenant_id, topic.kb_uid, None, {
            "index_generation": "index-11",
            "graph_generation": "graph-5",
            "model": "public-model",
            "prompt_version": "v1",
            "expected_version": expected_version,
            "expected_input_revision": expected_input_revision,
        }),
        f"input-revision-{job_type}-{reason}",
    )

    def change_input_during_llm(*args, **kwargs):
        mark_enrichment_stale(db_session, topic.kb_uid, reason=reason, **stale_kwargs)
        if job_type == "mindmap_generation":
            return {"nodes": [{"id": "old-output", "title": "Old", "children": []}]}
        return {"questions": ["Old output?"]}

    monkeypatch.setattr(enrichment_handlers, "call_llm", change_input_during_llm)
    result = enrichment_handlers.handle_enrichment(
        job.id,
        "worker-input-revision",
        db_session,
        KnowledgeJobService(db_session),
    )
    db_session.expire_all()
    loaded = db_session.get(KnowledgeTopic, topic.id)
    snapshot = loaded.mindmap if job_type == "mindmap_generation" else loaded.sample_questions

    assert result == {"status": "completed", "enrichment_status": "stale", "discarded": True}
    assert snapshot["status"] == "stale"
    assert snapshot["input_revision"] == expected_input_revision + 1
    if job_type == "mindmap_generation":
        assert snapshot["nodes"][0]["id"] != "old-output"
    else:
        assert snapshot["questions"] != ["Old output?"]


def test_worker_dispatches_question_generation_and_preserves_generation_snapshot(db_session, monkeypatch):
    from backend.app.services.knowledge_jobs import JobCommand, KnowledgeJobService
    from engine.app.jobs import enrichment_handlers
    from engine.app.jobs import worker

    topic = _topic(db_session)
    item = KnowledgeItem(tenant_id=topic.tenant_id, kb_uid=topic.kb_uid, title="Doc", normalized_markdown="# Doc")
    db_session.add(item)
    db_session.flush()
    db_session.add(
        KnowledgeFile(
            tenant_id=topic.tenant_id,
            kb_uid=topic.kb_uid,
            topic_id=topic.id,
            item_id=item.id,
            file_uid="file-public",
            original_filename="doc.md",
            media_type="document",
        )
    )
    db_session.commit()
    job = KnowledgeJobService(db_session).create(
        JobCommand(
            "sample_questions_generation",
            topic.tenant_id,
            topic.kb_uid,
            None,
            {
                "index_generation": "index-11",
                "graph_generation": "graph-5",
                "model": "public-model",
                "prompt_version": "questions-v2",
            },
        ),
        "question-handler-test",
    )
    monkeypatch.setattr(
        enrichment_handlers,
        "call_llm",
        lambda kind, payload, **kwargs: {"questions": ["What is documented?"]},
    )

    result = worker.dispatch_typed_job(db_session, job.id, "worker-questions")
    db_session.refresh(topic)

    assert result["status"] == "completed"
    assert topic.sample_questions["questions"] == ["What is documented?"]
    assert topic.sample_questions["index_generation"] == "index-11"
    assert topic.sample_questions["graph_generation"] == "graph-5"
    assert db_session.get(KnowledgeJob, job.id).status == "succeeded"


def test_generation_cas_discards_output_after_deterministic_diff(db_session, monkeypatch):
    from backend.app.services.knowledge_jobs import JobCommand, KnowledgeJobService
    from engine.app.jobs import enrichment_handlers, worker

    topic = _topic(db_session)
    topic.mindmap = {"status": "generating", "version": 2, "nodes": [{"id": "keep", "children": []}]}
    topic.mindmap_version = 2
    db_session.commit()
    job = KnowledgeJobService(db_session).create(
        JobCommand("mindmap_generation", topic.tenant_id, topic.kb_uid, None, {
            "index_generation": "index-11", "graph_generation": "graph-5",
            "model": "public-model", "prompt_version": "v1", "expected_version": 2,
        }),
        "cas-conflict",
    )

    def concurrent_diff(*args, **kwargs):
        topic.mindmap = {"status": "ready", "version": 3, "nodes": [{"id": "renamed", "title": "Renamed", "children": []}]}
        topic.mindmap_version = 3
        db_session.commit()
        return {"nodes": [{"id": "llm-output", "title": "Wrong", "children": []}]}

    monkeypatch.setattr(enrichment_handlers, "call_llm", concurrent_diff)
    result = worker.dispatch_typed_job(db_session, job.id, "worker-cas")
    db_session.expire_all()
    loaded = db_session.get(KnowledgeTopic, topic.id)

    assert result["enrichment_status"] == "stale"
    assert loaded.mindmap_version == 3
    assert loaded.mindmap["nodes"][0]["id"] == "renamed"
    assert loaded.mindmap["status"] == "stale"


def test_retryable_generation_failure_requeues_republishes_and_later_succeeds(db_session, monkeypatch):
    from backend.app.services.knowledge_jobs import JobCommand, KnowledgeJobService
    from engine.app.jobs import enrichment_handlers

    topic = _topic(db_session)
    topic.sample_questions = {"status": "generating", "version": 0, "questions": []}
    db_session.commit()
    job = KnowledgeJobService(db_session).create(
        JobCommand("sample_questions_generation", topic.tenant_id, topic.kb_uid, None, {
            "index_generation": "index-11", "graph_generation": "graph-5", "model": "m", "prompt_version": "v1", "expected_version": 0,
        }), "retry-enrichment",
    )
    calls = []
    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise TimeoutError("temporary")
        return {"questions": ["Recovered?"]}
    published = []
    monkeypatch.setattr(enrichment_handlers, "call_llm", flaky)

    first = enrichment_handlers.handle_enrichment(job.id, "worker-1", db_session, KnowledgeJobService(db_session), publisher=published.append)
    db_session.expire_all()
    assert first["status"] == "retrying"
    assert db_session.get(KnowledgeJob, job.id).status == "queued"
    assert db_session.get(KnowledgeTopic, topic.id).sample_questions["status"] == "generating"
    assert published == [job.id]
    second = enrichment_handlers.handle_enrichment(job.id, "worker-2", db_session, KnowledgeJobService(db_session), publisher=published.append)
    assert second["status"] == "completed"
    assert db_session.get(KnowledgeTopic, topic.id).sample_questions["questions"] == ["Recovered?"]


def test_retry_commit_survives_publish_failure_for_periodic_reconcile(db_session, monkeypatch):
    from backend.app.services.knowledge_jobs import JobCommand, KnowledgeJobService
    from engine.app.jobs import enrichment_handlers

    topic = _topic(db_session)
    topic.sample_questions = {"status": "generating", "version": 0, "input_revision": 2, "questions": []}
    db_session.commit()
    jobs = KnowledgeJobService(db_session)
    job = jobs.create(
        JobCommand("sample_questions_generation", topic.tenant_id, topic.kb_uid, None, {
            "index_generation": "index-11",
            "graph_generation": "graph-5",
            "model": "m",
            "prompt_version": "v1",
            "expected_version": 0,
            "expected_input_revision": 2,
        }),
        "retry-publish-reconcile",
    )
    monkeypatch.setattr(
        enrichment_handlers,
        "call_llm",
        lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("temporary")),
    )

    result = enrichment_handlers.handle_enrichment(
        job.id,
        "worker-retry-publish",
        db_session,
        jobs,
        publisher=lambda job_id: (_ for _ in ()).throw(ConnectionError("redis down")),
    )
    db_session.expire_all()

    assert result == {"status": "retrying"}
    assert db_session.get(KnowledgeJob, job.id).status == "queued"
    assert db_session.get(KnowledgeJob, job.id).stage == "retry"
    assert db_session.get(KnowledgeTopic, topic.id).sample_questions["status"] == "generating"


def test_snapshot_and_job_success_rollback_together_on_final_commit_crash(db_session, monkeypatch):
    from backend.app.services.knowledge_jobs import JobCommand, KnowledgeJobService
    from engine.app.jobs import enrichment_handlers

    topic = _topic(db_session)
    topic.sample_questions = {
        "status": "generating",
        "version": 0,
        "input_revision": 3,
        "questions": [],
    }
    db_session.commit()
    jobs = KnowledgeJobService(db_session)
    job = jobs.create(
        JobCommand("sample_questions_generation", topic.tenant_id, topic.kb_uid, None, {
            "index_generation": "index-11",
            "graph_generation": "graph-5",
            "model": "m",
            "prompt_version": "v1",
            "expected_version": 0,
            "expected_input_revision": 3,
        }),
        "snapshot-terminal-atomic",
    )
    monkeypatch.setattr(
        enrichment_handlers,
        "call_llm",
        lambda *args, **kwargs: {"questions": ["Atomic?"]},
    )
    original_succeed = jobs.succeed
    original_commit = db_session.commit
    state = {"armed": False, "crashed": False}

    def succeed_without_commit(*args, **kwargs):
        assert kwargs.get("commit") is False
        result = original_succeed(*args, **kwargs)
        if not state["crashed"]:
            state["armed"] = True
        return result

    def fail_final_commit_once():
        if state["armed"] and not state["crashed"]:
            state["crashed"] = True
            state["armed"] = False
            raise RuntimeError("commit crash")
        return original_commit()

    monkeypatch.setattr(jobs, "succeed", succeed_without_commit)
    monkeypatch.setattr(db_session, "commit", fail_final_commit_once)

    first = enrichment_handlers.handle_enrichment(
        job.id, "worker-1", db_session, jobs, publisher=lambda job_id: None
    )
    db_session.expire_all()
    after_crash_job = db_session.get(KnowledgeJob, job.id)
    after_crash_topic = db_session.get(KnowledgeTopic, topic.id)

    assert first["status"] == "retrying"
    assert after_crash_job.status == "queued"
    assert after_crash_topic.sample_questions["status"] == "generating"
    assert after_crash_topic.sample_questions["questions"] == []

    second = enrichment_handlers.handle_enrichment(job.id, "worker-2", db_session, jobs)
    db_session.expire_all()

    assert second["status"] == "completed"
    assert db_session.get(KnowledgeJob, job.id).status == "succeeded"
    assert db_session.get(KnowledgeTopic, topic.id).sample_questions["questions"] == ["Atomic?"]


def test_worker_current_locks_job_after_topic_and_cancel_wins(db_session, monkeypatch):
    from types import SimpleNamespace
    from backend.app.services.knowledge_jobs import JobCommand, KnowledgeJobService
    from backend.app.utils.time import local_now
    from engine.app.jobs import enrichment_handlers

    topic = _topic(db_session)
    topic.mindmap = {"status": "generating", "version": 0, "input_revision": 0, "nodes": []}
    db_session.commit()
    jobs = KnowledgeJobService(db_session)
    job = jobs.create(
        JobCommand("mindmap_generation", topic.tenant_id, topic.kb_uid, None, {
            "index_generation": "index-11",
            "graph_generation": "graph-5",
            "model": "m",
            "prompt_version": "v1",
            "expected_version": 0,
            "expected_input_revision": 0,
        }),
        "worker-current-cancel-wins",
    )
    monkeypatch.setattr(
        enrichment_handlers,
        "call_llm",
        lambda *args, **kwargs: {"nodes": [{"id": "old-output", "title": "Wrong", "children": []}]},
    )
    order = []
    original_topic_lock = enrichment_handlers._locked_topic

    def lock_topic(*args, **kwargs):
        order.append("topic")
        return original_topic_lock(*args, **kwargs)

    def lock_current_job(db, job_id, tenant_id, kb_uid):
        order.append("job")
        return SimpleNamespace(
            id=job_id,
            tenant_id=tenant_id,
            kb_uid=kb_uid,
            job_type="mindmap_generation",
            cancel_requested_at=local_now(),
        )

    monkeypatch.setattr(enrichment_handlers, "_locked_topic", lock_topic)
    monkeypatch.setattr(
        enrichment_handlers,
        "_locked_job_after_topic",
        lock_current_job,
        raising=False,
    )

    result = enrichment_handlers.handle_enrichment(
        job.id,
        "worker-current-cancel",
        db_session,
        jobs,
    )
    db_session.expire_all()

    assert order[-2:] == ["topic", "job"]
    assert result == {"status": "canceled"}
    assert db_session.get(KnowledgeJob, job.id).status == "canceled"
    assert db_session.get(KnowledgeTopic, topic.id).mindmap["status"] == "stale"


@pytest.mark.parametrize("change", ["delete", "rename"])
def test_cancel_after_llm_merges_latest_file_change_snapshot(tmp_path, monkeypatch, change):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from backend.app.database import Base
    from backend.app.services.knowledge_jobs import JobCommand, KnowledgeJobService
    from engine.app.jobs import enrichment_handlers
    from engine.app.knowledge.enrichment import mark_enrichment_stale

    engine = create_engine(f"sqlite:///{tmp_path / f'cancel-{change}.db'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    worker_db = Session()
    concurrent_db = Session()
    try:
        topic = KnowledgeTopic(
            tenant_id="tenant-a",
            owner_user_id="alice",
            name="Cancel merge",
            active_index_generation="index-11",
            active_graph_generation="graph-5",
            mindmap={
                "status": "generating",
                "version": 2,
                "input_revision": 5,
                "nodes": [{"id": "file-a", "file_uid": "file-a", "title": "Old", "children": []}],
            },
            mindmap_version=2,
        )
        worker_db.add(topic)
        worker_db.commit()
        jobs = KnowledgeJobService(worker_db)
        job = jobs.create(
            JobCommand("mindmap_generation", topic.tenant_id, topic.kb_uid, None, {
                "index_generation": "index-11",
                "graph_generation": "graph-5",
                "model": "m",
                "prompt_version": "v1",
                "expected_version": 2,
                "expected_input_revision": 5,
            }),
            f"cancel-latest-{change}",
        )

        def change_and_cancel(*args, **kwargs):
            stale_kwargs = (
                {"deleted_file_uids": ["file-a"]}
                if change == "delete"
                else {"renamed": [{"file_uid": "file-a", "title": "Renamed"}]}
            )
            mark_enrichment_stale(
                concurrent_db,
                topic.kb_uid,
                reason=f"file_{change}d",
                **stale_kwargs,
            )
            KnowledgeJobService(concurrent_db).request_cancel(job.id, "alice")
            return {"nodes": [{"id": "old-output", "title": "Wrong", "children": []}]}

        monkeypatch.setattr(enrichment_handlers, "call_llm", change_and_cancel)
        result = enrichment_handlers.handle_enrichment(job.id, "worker-cancel", worker_db, jobs)
        worker_db.expire_all()
        loaded = worker_db.get(KnowledgeTopic, topic.id)

        assert result == {"status": "canceled"}
        assert worker_db.get(KnowledgeJob, job.id).status == "canceled"
        assert loaded.mindmap["status"] == "stale"
        assert loaded.mindmap["input_revision"] == 6
        if change == "delete":
            assert loaded.mindmap["nodes"] == []
        else:
            assert loaded.mindmap["nodes"][0]["title"] == "Renamed"
    finally:
        worker_db.close()
        concurrent_db.close()
        engine.dispose()


def test_file_delete_hook_marks_questions_stale_and_removes_mindmap_leaf(client, db_session, monkeypatch):
    import backend.app.api.knowledge_files as files_api

    topic = _topic(db_session)
    topic.mindmap = {
        "status": "ready",
        "version": 1,
        "nodes": [{"id": "file-delete", "file_uid": "file-delete", "title": "Delete", "children": []}],
    }
    topic.mindmap_version = 1
    topic.sample_questions = {"status": "ready", "version": 1, "questions": ["Old question?"]}
    topic.sample_questions_version = 1
    db_session.add(
        KnowledgeFile(
            tenant_id=topic.tenant_id,
            kb_uid=topic.kb_uid,
            topic_id=topic.id,
            file_uid="file-delete",
            original_filename="delete.md",
            media_type="document",
        )
    )
    db_session.commit()
    monkeypatch.setattr(files_api, "_publish_job", lambda db, job: None)

    response = client.delete(
        f"/api/v1/knowledge-bases/{topic.kb_uid}/files/file-delete",
        headers=_headers(),
    )
    db_session.refresh(topic)

    assert response.status_code == 202
    assert topic.sample_questions["status"] == "stale"
    assert topic.mindmap["nodes"] == []
    assert topic.mindmap["updated_without_model"] is True


def test_file_metadata_patch_sanitizes_paths_and_deterministically_renames_mindmap(client, db_session):
    topic = _topic(db_session)
    topic.mindmap = {
        "status": "ready", "version": 1,
        "nodes": [{"id": "file-rename", "file_uid": "file-rename", "title": "Old", "children": []}],
    }
    topic.mindmap_version = 1
    db_session.add(KnowledgeFile(
        tenant_id=topic.tenant_id, kb_uid=topic.kb_uid, topic_id=topic.id,
        file_uid="file-rename", original_filename="old.md", title="Old", relative_path="old.md", media_type="document",
    ))
    db_session.commit()

    response = client.patch(
        f"/api/v1/knowledge-bases/{topic.kb_uid}/files/file-rename",
        headers=_headers(),
        json={"title": "C:\\private\\Renamed.md", "relative_path": "/private/renamed.md"},
    )
    db_session.refresh(topic)

    assert response.status_code == 200
    assert response.json()["original_filename"] == "Renamed.md"
    assert response.json()["relative_path"] == "renamed.md"
    assert topic.mindmap["nodes"][0]["title"] == "Renamed.md"
    assert topic.mindmap["nodes"][0]["relative_path"] == "renamed.md"


def test_expired_canceled_enrichment_lease_does_not_leave_generating_status(db_session, monkeypatch):
    from datetime import timedelta
    from backend.app.services.knowledge_jobs import JobCommand, KnowledgeJobService
    from backend.app.utils.time import local_now
    from engine.app.jobs import worker

    topic = _topic(db_session)
    topic_id = topic.id
    topic.mindmap = {"status": "generating", "nodes": []}
    db_session.commit()
    jobs = KnowledgeJobService(db_session)
    job = jobs.create(
        JobCommand("mindmap_generation", topic.tenant_id, topic.kb_uid, None, {}),
        "expired-canceled-enrichment",
    )
    job_id = job.id
    jobs.claim(job.id, "dead-worker", timedelta(seconds=30))
    stored = db_session.get(KnowledgeJob, job.id)
    stored.cancel_requested_at = local_now()
    stored.lease_expires_at = local_now() - timedelta(seconds=1)
    db_session.commit()
    monkeypatch.setattr(worker, "_Session", lambda: db_session)
    monkeypatch.setattr(worker, "_publish_job_and_mark_enqueued", lambda db, row: None)

    assert worker.recover_expired_evaluation_jobs() == 0
    topic = db_session.get(KnowledgeTopic, topic_id)

    assert db_session.get(KnowledgeJob, job_id).status == "canceled"
    assert topic.mindmap["status"] == "stale"
    assert topic.mindmap["stale_reason"] == "generation_canceled"


def test_enrichment_reaper_locks_topic_before_expired_job(db_session, monkeypatch):
    from datetime import timedelta
    from backend.app.services.knowledge_jobs import JobCommand, KnowledgeJobService
    from backend.app.utils.time import local_now
    from engine.app.jobs import worker

    topic = _topic(db_session)
    topic.mindmap = {"status": "generating", "input_revision": 1, "nodes": []}
    db_session.commit()
    jobs = KnowledgeJobService(db_session)
    job = jobs.create(
        JobCommand("mindmap_generation", topic.tenant_id, topic.kb_uid, None, {}),
        "reaper-lock-order",
    )
    jobs.claim(job.id, "dead-worker", timedelta(seconds=30))
    stored = db_session.get(KnowledgeJob, job.id)
    stored.cancel_requested_at = local_now()
    stored.lease_expires_at = local_now() - timedelta(seconds=1)
    db_session.commit()
    order = []

    def lock_topic(db, candidate):
        order.append("topic")
        return db.query(KnowledgeTopic).filter_by(
            tenant_id=candidate.tenant_id,
            kb_uid=candidate.kb_uid,
        ).with_for_update().one_or_none()

    def lock_job(db, job_id, now):
        order.append("job")
        return db.query(KnowledgeJob).filter_by(id=job_id).with_for_update().one_or_none()

    monkeypatch.setattr(worker, "_Session", lambda: db_session)
    monkeypatch.setattr(worker, "_lock_reaper_topic", lock_topic, raising=False)
    monkeypatch.setattr(worker, "_lock_expired_job", lock_job, raising=False)
    monkeypatch.setattr(worker, "_publish_job_and_mark_enqueued", lambda db, row: None)

    worker._recover_expired_evaluation_jobs()

    assert order[:2] == ["topic", "job"]


def test_export_api_is_authorized_zip_and_does_not_expose_internal_paths(client, db_session):
    topic = _topic(db_session)
    item = KnowledgeItem(
        tenant_id=topic.tenant_id,
        kb_uid=topic.kb_uid,
        title="Doc",
        normalized_markdown="# Public document",
        source_ref="C:\\private\\source.md",
    )
    db_session.add(item)
    db_session.flush()
    db_session.add(
        KnowledgeFile(
            tenant_id=topic.tenant_id,
            kb_uid=topic.kb_uid,
            topic_id=topic.id,
            item_id=item.id,
            file_uid="file-public",
            original_filename="doc.md",
            storage_uri="file:///C:/private/object",
            file_path="C:\\private\\object",
            media_type="document",
        )
    )
    db_session.commit()

    denied = client.get(f"/api/v1/knowledge-bases/{topic.kb_uid}/export", headers=_headers(actor="mallory"))
    response = client.get(f"/api/v1/knowledge-bases/{topic.kb_uid}/export", headers=_headers())

    assert denied.status_code == 403
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        for name in archive.namelist():
            assert not name.startswith(("/", "\\"))
            assert ".." not in name.split("/")
        exported = b"\n".join(archive.read(name) for name in archive.namelist()).decode("utf-8")
    assert "C:\\private" not in exported
    assert "storage_uri" not in exported


def test_export_stream_closes_spool_after_response(client, db_session, monkeypatch):
    import tempfile
    import backend.app.api.knowledge_enrichment as api

    topic = _topic(db_session)
    spool = tempfile.SpooledTemporaryFile(max_size=32, mode="w+b")
    with zipfile.ZipFile(spool, "w") as archive:
        archive.writestr("manifest.json", "{}")
    spool.seek(0)
    closed = []
    original_close = spool.close
    class Tracking:
        def read(self, size=-1):
            return spool.read(size)
        def seek(self, *args):
            return spool.seek(*args)
        def close(self):
            closed.append(True)
            original_close()
    monkeypatch.setattr(api, "build_knowledge_export", lambda db, row: Tracking())

    response = client.get(f"/api/v1/knowledge-bases/{topic.kb_uid}/export", headers=_headers())

    assert response.status_code == 200
    assert closed == [True]
