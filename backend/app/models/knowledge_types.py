import enum
import uuid


def uuid4_str() -> str:
    return str(uuid.uuid4())


class ResourceStatus(str, enum.Enum):
    ACTIVE = "active"
    DELETING = "deleting"


class StageStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    STALE = "stale"
    SKIPPED = "skipped"


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class TeamRole(str, enum.Enum):
    ADMIN = "admin"
    MEMBER = "member"


class KnowledgeGovernanceStatus(str, enum.Enum):
    PERSONAL = "personal"
    PENDING_TRANSFER = "pending_transfer"
    MANAGED = "managed"


class KnowledgeBaseRole(str, enum.Enum):
    VIEWER = "viewer"
    CONTRIBUTOR = "contributor"
    EDITOR = "editor"
    MANAGER = "manager"
