# backend/app/services/knowledge_access.py
from sqlalchemy.orm import Session

from backend.app.models import KnowledgeTopic
from backend.app.security.actor import ActorContext


class KnowledgeNotFound(LookupError):
    def __init__(self, kb_uid: str):
        self.kb_uid = kb_uid
        super().__init__(f"Knowledge base {kb_uid} not found")


class KnowledgeAccessDenied(PermissionError):
    def __init__(self, kb_uid: str):
        self.kb_uid = kb_uid
        super().__init__(f"Access denied to knowledge base {kb_uid}")


class KnowledgeAccessPolicy:
    def __init__(self, db: Session):
        self.db = db

    def require_read(self, actor: ActorContext, kb_uid: str) -> KnowledgeTopic:
        topic = (
            self.db.query(KnowledgeTopic)
            .filter_by(kb_uid=kb_uid, deleted_at=None)
            .one_or_none()
        )
        if topic is None:
            raise KnowledgeNotFound(kb_uid)
        if topic.tenant_id != actor.tenant_id or topic.owner_user_id != actor.actor_id:
            raise KnowledgeAccessDenied(kb_uid)
        return topic

    require_manage = require_read
