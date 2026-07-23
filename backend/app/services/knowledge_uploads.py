# backend/app/services/knowledge_uploads.py
from dataclasses import dataclass
from pathlib import Path
import json

from sqlalchemy.orm import Session

from backend.app.models import KnowledgeFile
from backend.app.models.knowledge_types import uuid4_str
from backend.app.security.actor import ActorContext
from backend.app.services.knowledge_access import KnowledgeAccessPolicy
from backend.app.services.knowledge_jobs import JobCommand, KnowledgeJobService, RedisPublisher
from backend.app.storage.files import FileStorage, LocalFileStorage
from backend.app.utils.time import local_now


@dataclass(frozen=True)
class UploadRequest:
    kb_uid: str
    filename: str
    relative_path: str
    media_type: str
    mime_type: str | None
    content: bytes
    parser_config: dict | None = None
    chunk_config: dict | None = None
    auto_index: bool = False


class DuplicateKnowledgeFile(ValueError):
    def __init__(self, file_uid: str):
        self.file_uid = file_uid
        super().__init__(f"Duplicate file: {file_uid}")


class RedisJobPublisher:
    def __init__(self, redis_url: str, queue_name: str):
        self.redis_url = redis_url
        self.queue_name = queue_name

    def publish(self, job_id: str) -> None:
        import redis
        client = redis.Redis.from_url(
            self.redis_url,
            socket_connect_timeout=0.25,
            socket_timeout=0.25,
        )
        client.lpush(self.queue_name, json.dumps({"job_id": job_id}))


class KnowledgeUploadService:
    def __init__(
        self,
        db: Session,
        storage: FileStorage,
        publisher: RedisPublisher | None = None,
    ):
        self.db = db
        self.storage = storage
        self.publisher = publisher
        self.policy = KnowledgeAccessPolicy(db)
        self.jobs = KnowledgeJobService(db)

    def register(
        self,
        actor: ActorContext,
        request: UploadRequest,
    ):
        topic = self.policy.require_manage(actor, request.kb_uid)
        file_uid = uuid4_str()
        staged = self.storage.stage(
            actor.tenant_id, topic.kb_uid, file_uid,
            request.filename, request.content,
        )
        try:
            duplicate = (
                self.db.query(KnowledgeFile)
                .filter_by(
                    tenant_id=actor.tenant_id,
                    kb_uid=topic.kb_uid,
                    content_sha256=staged.sha256,
                    deleted_at=None,
                )
                .one_or_none()
            )
            if duplicate:
                if staged.path.exists():
                    staged.path.unlink(missing_ok=True)
                raise DuplicateKnowledgeFile(duplicate.file_uid)
            storage_uri = self.storage.commit(staged)
            file_row = KnowledgeFile(
                file_uid=file_uid,
                tenant_id=actor.tenant_id,
                kb_uid=topic.kb_uid,
                original_filename=request.filename,
                relative_path=request.relative_path,
                media_type=request.media_type,
                mime_type=request.mime_type,
                storage_uri=storage_uri,
                content_sha256=staged.sha256,
                size_bytes=staged.size_bytes,
                parser_config_snapshot=request.parser_config,
                chunk_config_snapshot=request.chunk_config,
            )
            self.db.add(file_row)
            self.db.commit()
            job = self.jobs.create(
                JobCommand(
                    "parse",
                    actor.tenant_id,
                    topic.kb_uid,
                    file_uid,
                    {"auto_index": request.auto_index},
                ),
                f"{topic.kb_uid}:{file_uid}:parse:v0",
            )
            if self.publisher:
                try:
                    self.publisher.publish(job.id)
                    self.jobs.stage_enqueued(job.id)
                except Exception:
                    self.db.rollback()
            return file_row, job
        except Exception:
            if staged.path.exists():
                staged.path.unlink(missing_ok=True)
            raise


class StagingReaper:
    def __init__(self, db: Session, storage: LocalFileStorage):
        self.db = db
        self.storage = storage

    def run(self, *, max_age_hours: int = 24) -> int:
        cutoff = (local_now().timestamp() - max_age_hours * 60 * 60)
        referenced = {
            uri.removeprefix("local://")
            for (uri,) in self.db.query(KnowledgeFile.storage_uri)
            .filter(KnowledgeFile.storage_uri.is_not(None))
            .all()
            if uri.startswith("local://")
        }
        removed = 0
        if not self.storage.staging.exists():
            return removed
        for path in self.storage.staging.glob("*.part"):
            relative = path.relative_to(self.storage.root).as_posix()
            if relative in referenced or path.stat().st_mtime >= cutoff:
                continue
            path.unlink(missing_ok=True)
            removed += 1
        return removed


class StagingReaperScheduler:
    def __init__(self):
        self._scheduler = None

    def start(self) -> None:
        from apscheduler.schedulers.background import BackgroundScheduler
        from backend.app.config import settings
        if not settings.KNOWLEDGE_STAGING_REAPER_ENABLED:
            return
        self._scheduler = BackgroundScheduler()
        self._scheduler.add_job(
            _run_staging_reaper,
            trigger="interval",
            minutes=settings.KNOWLEDGE_STAGING_REAPER_INTERVAL_MINUTES,
            id="knowledge_staging_reaper",
            replace_existing=True,
        )
        self._scheduler.start()

    def shutdown(self) -> None:
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)


def _run_staging_reaper() -> int:
    from backend.app.config import settings
    from backend.app.database import SessionLocal
    db = SessionLocal()
    try:
        return StagingReaper(db, LocalFileStorage(Path(settings.KNOWLEDGE_STORAGE_ROOT))).run()
    finally:
        db.close()
