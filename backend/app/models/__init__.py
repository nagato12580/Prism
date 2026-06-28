# prism/backend/app/models/__init__.py
from .knowledge_item import KnowledgeTopic, KnowledgeItem, KnowledgeChunk, KnowledgeFile
from .knowledge_job import KnowledgeJob
from .chat import ChatSession, ChatMessage
from .wiki import WikiDocument, WikiConcept, WikiKnowledgePoint, WikiKnowledgeRelation, WikiImage, WikiExtractionLog
from .memory import (
    MemoryDraft,
    MemoryEntity,
    MemoryEntry,
    MemoryEvent,
    MemoryInsight,
    MemoryRelation,
    MemorySource,
    MemoryStatement,
)
from .asset import PersonalAsset, PersonalAssetItem, PersonalAssetUnit, AssetRelation, ExtensionPoint, AssetUsageEvent
from .knowledge_governance import (
    CanonicalKnowledgePoint,
    CanonicalRelation,
    PKUCanonicalLink,
    PKURelation,
    PersonalKnowledgeUnit,
)
from .entity import KnowledgeEntity, EntityAlias, EntityMention, EntityRelation

__all__ = [
    "KnowledgeTopic",
    "KnowledgeItem",
    "KnowledgeChunk",
    "KnowledgeFile",
    "KnowledgeJob",
    "ChatSession",
    "ChatMessage",
    "WikiDocument",
    "WikiConcept",
    "WikiKnowledgePoint",
    "WikiKnowledgeRelation",
    "WikiImage",
    "WikiExtractionLog",
    "MemoryDraft",
    "MemoryEntity",
    "MemoryEntry",
    "MemoryEvent",
    "MemoryInsight",
    "MemoryRelation",
    "MemorySource",
    "MemoryStatement",
    "PersonalAsset",
    "PersonalAssetItem",
    "AssetRelation",
    "ExtensionPoint",
    "AssetUsageEvent",
    "PersonalAssetUnit",
    "PersonalKnowledgeUnit",
    "CanonicalKnowledgePoint",
    "PKUCanonicalLink",
    "PKURelation",
    "CanonicalRelation",
    "KnowledgeEntity",
    "EntityAlias",
    "EntityMention",
    "EntityRelation",
]
