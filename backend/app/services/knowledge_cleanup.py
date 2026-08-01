from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from backend.app.models import KnowledgeChunk, KnowledgeFile, KnowledgeItem, KnowledgeJob
from backend.app.models.entity import EntityMention, EntityRelation
from backend.app.utils.time import local_now


CHECKPOINTS = (
    "milvus_deleted",
    "es_deleted",
    "graph_deleted",
    "storage_deleted",
    "rows_deleted",
)


@dataclass(frozen=True)
class CleanupResult:
    status: str
    checkpoint: str | None
    error: str | None = None


@dataclass(frozen=True)
class ReconciliationFinding:
    kind: str
    identity: object


@dataclass(frozen=True)
class ReconciliationResult:
    findings: tuple[ReconciliationFinding, ...]
    applied: int = 0


class KnowledgeReconciler:
    """Discover drift safely; mutation is opt-in via ``apply=True``."""

    def __init__(self, db, queue, artifact_indexes, staging, *, now=local_now):
        self.db = db
        self.queue = queue
        self.artifact_indexes = artifact_indexes
        self.staging = staging
        self.now = now

    def run(self, *, apply=False, retention_days=7):
        now = self.now()
        findings = []
        queued = self.db.query(KnowledgeJob).filter(
            KnowledgeJob.status == "queued",
            or_(KnowledgeJob.available_at.is_(None), KnowledgeJob.available_at <= now),
        ).all()
        for job in queued:
            if not self.queue.contains(job.id):
                findings.append(ReconciliationFinding("missing_queue_job", job.id))

        live_scopes = {
            (tenant_id, kb_uid, file_uid, generation)
            for tenant_id, kb_uid, file_uid, generation in self.db.query(
                KnowledgeChunk.tenant_id,
                KnowledgeChunk.kb_uid,
                KnowledgeChunk.file_uid,
                KnowledgeChunk.generation,
            ).all()
        }
        retention_before = now - timedelta(days=retention_days)
        for index in self.artifact_indexes:
            for identity in index.stale_generations(live_scopes, retention_before):
                findings.append(ReconciliationFinding("stale_generation", (index, identity)))
            for identity in index.orphan_rows(live_scopes):
                findings.append(ReconciliationFinding("orphan_external_row", (index, identity)))

        referenced = set(self.db.query(
            KnowledgeFile.tenant_id, KnowledgeFile.kb_uid, KnowledgeFile.file_uid
        ).all())
        for identity in self.staging.stale_unreferenced(
            referenced, now - timedelta(hours=24)
        ):
            findings.append(ReconciliationFinding("stale_staging", identity))

        applied = 0
        if apply:
            for finding in findings:
                if finding.kind == "missing_queue_job":
                    self.queue.publish(finding.identity)
                elif finding.kind == "stale_staging":
                    self.staging.remove_staging(finding.identity)
                else:
                    index, identity = finding.identity
                    index.remove(identity)
                applied += 1
        return ReconciliationResult(tuple(findings), applied)


class KnowledgeCleanupService:
    """Checkpointed, idempotent deletion across knowledge stores."""

    def __init__(self, db: Session, milvus, es, storage, *, graph_client=None, closers=()):
        self.db = db
        self.milvus = milvus
        self.es = es
        self.storage = storage
        self.graph_client = graph_client
        self.closers = tuple(closers)

    def close(self):
        for closer in reversed(self.closers):
            closer()

    def _job(self, job_id):
        job = self.db.get(KnowledgeJob, job_id)
        if job is None or job.job_type != "delete":
            raise ValueError("delete job not found")
        return job

    def _checkpoint(self, job, checkpoint):
        prior = dict(job.result or {})
        prior["checkpoint"] = checkpoint
        job.result = prior
        self.db.commit()

    def _delete_graph_rows(self, file_row, tenant_id, kb_uid, item_id, chunk_ids):
        if file_row.source_kind == "personal_asset_unit" and file_row.source_id:
            from backend.app.services.personal_inbox import purge_personal_asset_unit_graph_artifacts

            purge_personal_asset_unit_graph_artifacts(
                self.db,
                file_row.source_id,
                user_id=file_row.user_id or "default-user",
                graph_client=self.graph_client,
            )
        if not item_id:
            return
        self.db.query(EntityRelation).filter(
            or_(
                and_(EntityRelation.source_kind == "document_chunk", EntityRelation.source_id.in_(chunk_ids)),
                and_(EntityRelation.source_kind == "document_item", EntityRelation.source_id == item_id),
            )
        ).delete(synchronize_session=False)
        self.db.query(EntityMention).filter(
            EntityMention.item_id == item_id,
            or_(
                and_(EntityMention.source_kind == "document_chunk", EntityMention.source_id.in_(chunk_ids)),
                and_(EntityMention.source_kind == "document_item", EntityMention.source_id == item_id),
            ),
        ).delete(synchronize_session=False)
        if self.graph_client is not None:
            self.graph_client.delete_item_sources_all_generations(tenant_id, kb_uid, item_id)

    def run(self, file_uid: str, *, job_id: str) -> CleanupResult:
        job = self._job(job_id)
        completed = (job.result or {}).get("checkpoint")
        if completed == "rows_deleted":
            return CleanupResult("succeeded", completed)

        file_row = (
            self.db.query(KnowledgeFile)
            .filter_by(
                tenant_id=job.tenant_id,
                kb_uid=job.kb_uid,
                file_uid=file_uid,
            )
            .one_or_none()
        )
        if file_row is None:
            self._checkpoint(job, "rows_deleted")
            return CleanupResult("succeeded", "rows_deleted")
        if file_row.deleted_at is None:
            raise RuntimeError("file must be tombstoned before cleanup")

        start = CHECKPOINTS.index(completed) + 1 if completed in CHECKPOINTS else 0
        item_id = file_row.item_id
        chunk_ids = [
            row[0]
            for row in self.db.query(KnowledgeChunk.id)
            .filter_by(
                tenant_id=job.tenant_id,
                kb_uid=job.kb_uid,
                file_uid=file_uid,
            )
            .all()
        ]
        try:
            for checkpoint in CHECKPOINTS[start:]:
                if checkpoint == "milvus_deleted":
                    self.milvus.delete_file(job.tenant_id, job.kb_uid, file_uid)
                elif checkpoint == "es_deleted":
                    self.es.delete_file(job.tenant_id, job.kb_uid, file_uid)
                elif checkpoint == "graph_deleted":
                    # The durable delete Job + checkpoint is the recoverable
                    # intent until the later Graph Plan introduces an Outbox.
                    self._delete_graph_rows(file_row, job.tenant_id, job.kb_uid, item_id, chunk_ids)
                elif checkpoint == "storage_deleted":
                    if file_row.storage_uri:
                        self.storage.delete(file_row.storage_uri)
                elif checkpoint == "rows_deleted":
                    self.db.query(KnowledgeChunk).filter_by(
                        tenant_id=job.tenant_id,
                        kb_uid=job.kb_uid,
                        file_uid=file_uid,
                    ).delete(synchronize_session=False)
                    if item_id:
                        self.db.query(KnowledgeItem).filter_by(
                            id=item_id,
                            tenant_id=job.tenant_id,
                            kb_uid=job.kb_uid,
                        ).delete(synchronize_session=False)
                    self.db.delete(file_row)
                self._checkpoint(job, checkpoint)
            return CleanupResult("succeeded", "rows_deleted")
        except Exception as exc:
            self.db.rollback()
            self.db.refresh(job)
            return CleanupResult(
                "failed", (job.result or {}).get("checkpoint"), str(exc)
            )
