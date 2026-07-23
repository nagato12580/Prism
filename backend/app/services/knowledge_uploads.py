# backend/app/services/knowledge_uploads.py
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from sqlalchemy.orm import Session

from backend.app.models import KnowledgeFile, KnowledgeTopic
from backend.app.models.knowledge_types import uuid4_str
from backend.app.security.actor import ActorContext
from backend.app.services.knowledge_access import KnowledgeAccessPolicy
from backend.app.services.knowledge_jobs import JobCommand, KnowledgeJobService
from backend.app.storage.files import FileStorage


@dataclass(frozen=True)
class UploadRequest:
    kb_uid: str
    filename: str
    relative_path: str
    media_type: str
    content: bytes
    parser_config: dict | None = None
    chunk_config: dict | None = None
    auto_index: bool = False


class DuplicateKnowledgeFile(ValueError):
    def __init__(self, file_uid: str):
        self.file_uid = file_uid
        super().__init__(f"Duplicate file: {file_uid}")


class KnowledgeUploadService:
    def __init__(self, db: Session, storage: FileStorage):
        self.db = db
        self.storage = storage
        self.policy = KnowledgeAccessPolicy(db)
        self.jobs = KnowledgeJobService(db)

    def register(
        self,
        actor: ActorContext,
        request: UploadRequest,
    ) -> tuple[KnowledgeFile, KnowledgeTopic]:
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
                storage_uri=storage_uri,
                content_sha256=staged.sha256,
                size_bytes=staged.size_bytes,
                parser_config_snapshot=request.parser_config,
                chunk_config_snapshot=request.chunk_config,
            )
            self.db.add(file_row)
            self.db.commit()
            return file_row, topic
        except Exception:
            if staged.path.exists():
                staged.path.unlink(missing_ok=True)
            raise
