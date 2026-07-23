from dataclasses import dataclass
from hashlib import sha256


@dataclass(frozen=True)
class EmbeddingProfile:
    provider: str
    model: str
    dimension: int
    metric: str
    normalize: bool

    @property
    def profile_id(self) -> str:
        raw = (
            f"{self.provider}|{self.model}|{self.dimension}|"
            f"{self.metric}|{int(self.normalize)}"
        )
        return sha256(raw.encode()).hexdigest()[:16]

    @property
    def document_collection(self) -> str:
        return f"prism_kb_{self.profile_id}"

    @property
    def graph_collection(self) -> str:
        return f"prism_graph_{self.profile_id}"

    @property
    def collection_name(self) -> str:
        """Compatibility alias for the document collection."""
        return self.document_collection


DEFAULT_PROFILE = EmbeddingProfile(
    "jina", "jina-embeddings-v3", 1024, "COSINE", True
)
