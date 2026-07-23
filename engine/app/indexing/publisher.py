# engine/app/indexing/publisher.py
from dataclasses import dataclass
from sqlalchemy.orm import Session

from backend.app.models import KnowledgeChunk, KnowledgeFile, KnowledgeTopic
from backend.app.utils.time import local_now
from engine.app.indexing.profiles import EmbeddingProfile
from engine.app.ingestion.vectorizer import embed_texts
from engine.app.knowledge.enrichment import mark_topic_enrichment_stale


@dataclass(frozen=True)
class GenerationScope:
    tenant_id: str
    kb_uid: str
    generation: str


@dataclass(frozen=True)
class IndexBuildResult:
    status: str
    row_count: int = 0
    error: str | None = None


class GenerationPublisher:
    """Build and atomically activate a scoped side generation."""

    def __init__(
        self,
        db: Session,
        milvus,
        es,
        profile: EmbeddingProfile,
        *,
        embedder=embed_texts,
    ):
        self.db = db
        self.milvus = milvus
        self.es = es
        self.profile = profile
        self.embedder = embedder

    def build(self, kb_uid: str, generation: str, *, expected_old: str | None):
        topic = (
            self.db.query(KnowledgeTopic)
            .filter_by(kb_uid=kb_uid, deleted_at=None)
            .one_or_none()
        )
        if topic is None:
            raise ValueError(f"Topic {kb_uid} not found")
        scope = GenerationScope(topic.tenant_id, topic.kb_uid, generation)
        try:
            chunks = (
                self.db.query(KnowledgeChunk)
                .filter_by(
                    tenant_id=topic.tenant_id,
                    kb_uid=topic.kb_uid,
                    generation=generation,
                    chunk_type="child",
                )
                .order_by(KnowledgeChunk.file_uid, KnowledgeChunk.chunk_uid)
                .all()
            )
            if not chunks:
                raise RuntimeError("generation has no child chunks")
            vectors = self.embedder([chunk.chunk_text for chunk in chunks])
            if len(vectors) != len(chunks):
                raise RuntimeError("embedding count mismatch")
            if any(len(vector) != self.profile.dimension for vector in vectors):
                raise RuntimeError("embedding dimension mismatch")

            parent_ids = {chunk.parent_id for chunk in chunks if chunk.parent_id}
            parents = {
                parent.id: parent
                for parent in self.db.query(KnowledgeChunk)
                .filter(KnowledgeChunk.id.in_(parent_ids))
                .all()
            } if parent_ids else {}

            rows = [
                {
                    "tenant_id": chunk.tenant_id,
                    "kb_uid": chunk.kb_uid,
                    "file_uid": chunk.file_uid,
                    "item_id": chunk.item_id,
                    "chunk_uid": chunk.chunk_uid,
                    "source_type": chunk.item.source_type if chunk.item else "document",
                    "generation": generation,
                    "embedding_model_version": self.profile.profile_id,
                    "content": chunk.chunk_text,
                    "parent_text": (
                        parents[chunk.parent_id].chunk_text
                        if chunk.parent_id in parents else None
                    ),
                    "title": chunk.item.title if chunk.item else None,
                    "page_start": chunk.page_number,
                    "page_end": chunk.page_number,
                    "indexed_at": local_now().isoformat(),
                    "embedding": vector,
                }
                for chunk, vector in zip(chunks, vectors, strict=True)
            ]
            self.milvus.write(rows)
            self.es.write(rows)
            for index in (self.milvus, self.es):
                if index.count(scope) != len(rows):
                    raise RuntimeError("generation row count validation failed")
                if not index.sample(scope, chunks[0].chunk_uid):
                    raise RuntimeError("generation sample validation failed")

            updated = (
                self.db.query(KnowledgeTopic)
                .filter(
                    KnowledgeTopic.id == topic.id,
                    KnowledgeTopic.active_index_generation == expected_old,
                )
                .update(
                    {KnowledgeTopic.active_index_generation: generation},
                    synchronize_session=False,
                )
            )
            if updated != 1:
                raise RuntimeError("active generation changed concurrently")
            self.db.refresh(topic)
            mark_topic_enrichment_stale(topic, reason="active_index_generation_changed")
            self.db.commit()
            return IndexBuildResult("succeeded", len(rows))
        except Exception as exc:
            self.db.rollback()
            for index in (self.milvus, self.es):
                try:
                    index.delete_generation(scope)
                except Exception:
                    pass
            return IndexBuildResult("failed", error=str(exc))


def activate_generation(
    db: Session,
    kb_uid: str,
    generation: str,
    *,
    expected_old: str | None,
):
    topic = (
        db.query(KnowledgeTopic)
        .filter_by(
            kb_uid=kb_uid,
            active_index_generation=expected_old,
            deleted_at=None,
        )
        .with_for_update()
        .one_or_none()
    )
    if topic is None:
        raise RuntimeError("active generation changed concurrently")
    topic.active_index_generation = generation
    mark_topic_enrichment_stale(topic, reason="active_index_generation_changed")
    db.commit()
    db.refresh(topic)
    return topic


def mark_index_complete(db: Session, file_uid: str, generation: str):
    file_row = (
        db.query(KnowledgeFile)
        .filter_by(file_uid=file_uid, deleted_at=None)
        .one_or_none()
    )
    if file_row is None:
        raise ValueError(f"File {file_uid} not found")
    from backend.app.models.knowledge_types import StageStatus
    file_row.index_status = StageStatus.SUCCEEDED.value
    file_row.active_index_generation = generation
    db.commit()
    return file_row
