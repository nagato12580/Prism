"""Engine-side service authorization primitives."""

from .knowledge_scope import (
    AuthorizedKnowledgeScope,
    ExpiredKnowledgeScope,
    InvalidKnowledgeScope,
    verify_scope,
)

__all__ = [
    "AuthorizedKnowledgeScope",
    "ExpiredKnowledgeScope",
    "InvalidKnowledgeScope",
    "verify_scope",
]
