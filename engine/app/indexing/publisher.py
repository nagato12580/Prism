# engine/app/indexing/publisher.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from sqlalchemy.orm import Session
from backend.app.models import KnowledgeTopic, KnowledgeFile


def activate_generation(db: Session, kb_uid: str, generation: str):
    topic = db.query(KnowledgeTopic).filter_by(kb_uid=kb_uid, deleted_at=None).one_or_none()
    if topic is None:
        raise ValueError(f"Topic {kb_uid} not found")
    topic.active_index_generation = generation
    db.commit()
    db.refresh(topic)
    return topic


def mark_index_complete(db: Session, file_uid: str):
    file_row = (
        db.query(KnowledgeFile)
        .filter_by(file_uid=file_uid, deleted_at=None)
        .one_or_none()
    )
    if file_row is None:
        raise ValueError(f"File {file_uid} not found")
    from backend.app.models.knowledge_types import StageStatus
    file_row.index_status = StageStatus.SUCCEEDED.value
    file_row.active_index_generation = "0"
    db.commit()
    return file_row
