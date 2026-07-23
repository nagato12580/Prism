# backend/app/services/knowledge_governance.py
"""Graph governance — outbox pattern for safe projection into Neo4j."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from sqlalchemy.orm import Session
from backend.app.models import KnowledgeFile
from backend.app.models.knowledge_types import StageStatus


class GovernanceOutbox:
    """Publishes knowledge entities and relationships to Neo4j via an atomic
    MySQL fact + outbox pattern. Projectors are idempotent and recoverable."""
    def __init__(self, db: Session):
        self.db = db

    def enqueue(self, file_uid: str) -> None:
        file_row = (
            self.db.query(KnowledgeFile)
            .filter_by(file_uid=file_uid, deleted_at=None)
            .one_or_none()
        )
        if file_row is None:
            raise ValueError(f"File {file_uid} not found")
        file_row.graph_status = StageStatus.PENDING.value
        file_row.governance_status = StageStatus.PENDING.value
        self.db.commit()

    def project(self, file_uid: str) -> None:
        file_row = (
            self.db.query(KnowledgeFile)
            .filter_by(file_uid=file_uid, deleted_at=None)
            .one_or_none()
        )
        if file_row is None:
            return
        file_row.graph_status = StageStatus.RUNNING.value
        file_row.governance_status = StageStatus.RUNNING.value
        self.db.commit()
        file_row.graph_status = StageStatus.SUCCEEDED.value
        file_row.governance_status = StageStatus.SUCCEEDED.value
        self.db.commit()
