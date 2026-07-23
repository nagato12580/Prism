# engine/app/indexing/profiles.py
from dataclasses import dataclass


@dataclass(frozen=True)
class EmbeddingProfile:
    name: str
    dimension: int
    collection_name: str


DEFAULT_PROFILE = EmbeddingProfile("default", 1024, "prism_knowledge_dev")
