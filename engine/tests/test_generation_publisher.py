from backend.app.models import KnowledgeChunk, KnowledgeFile, KnowledgeItem, KnowledgeTopic


class FakeGenerationIndex:
    def __init__(self, *, fail_write=False):
        self.fail_write = fail_write
        self.rows = []
        self.deleted_generations = []

    def write(self, rows):
        if self.fail_write:
            raise RuntimeError("index write failed")
        self.rows.extend(rows)
        return len(rows)

    def count(self, scope):
        return sum(
            row["tenant_id"] == scope.tenant_id
            and row["kb_uid"] == scope.kb_uid
            and row["generation"] == scope.generation
            for row in self.rows
        )

    def sample(self, scope, chunk_uid):
        return any(
            row["chunk_uid"] == chunk_uid
            and row["tenant_id"] == scope.tenant_id
            and row["kb_uid"] == scope.kb_uid
            and row["generation"] == scope.generation
            for row in self.rows
        )

    def delete_generation(self, scope):
        self.deleted_generations.append(scope.generation)
        self.rows = [row for row in self.rows if row["generation"] != scope.generation]


def _seed_generation(db_session, *, active="old", generation="new"):
    from backend.app.models.knowledge_types import StageStatus

    topic = KnowledgeTopic(
        tenant_id="tenant-a",
        owner_user_id="alice",
        name="KB",
        active_index_generation=active,
    )
    db_session.add(topic)
    db_session.flush()
    item = KnowledgeItem(
        tenant_id="tenant-a", kb_uid=topic.kb_uid, title="Doc", content="body"
    )
    db_session.add(item)
    db_session.flush()
    db_session.add(
        KnowledgeFile(
            tenant_id="tenant-a",
            kb_uid=topic.kb_uid,
            file_uid="file-a",
            item_id=item.id,
            original_filename="doc.pdf",
            parse_status=StageStatus.SUCCEEDED.value,
            parsed_content_version=1,
        )
    )
    db_session.add(
        KnowledgeChunk(
            tenant_id="tenant-a",
            kb_uid=topic.kb_uid,
            file_uid="file-a",
            item_id=item.id,
            generation="1",
            chunk_uid="chunk-a",
            chunk_text="retrievable text",
            chunk_type="child",
        )
    )
    db_session.commit()
    return topic


def test_failed_generation_does_not_switch_active(db_session):
    from engine.app.indexing.profiles import EmbeddingProfile
    from engine.app.indexing.publisher import GenerationPublisher

    topic = _seed_generation(db_session)
    milvus = FakeGenerationIndex()
    es = FakeGenerationIndex(fail_write=True)
    profile = EmbeddingProfile("test", "model-v1", 2, "COSINE", True)

    result = GenerationPublisher(
        db_session, milvus, es, profile, embedder=lambda texts: [[0.1, 0.2]]
    ).build(topic.kb_uid, "new", expected_old="old")

    db_session.refresh(topic)
    assert result.status == "failed"
    assert topic.active_index_generation == "old"
    assert milvus.deleted_generations == ["new"]
    assert es.deleted_generations == ["new"]


def test_valid_generation_is_conditionally_activated(db_session):
    from engine.app.indexing.profiles import EmbeddingProfile
    from engine.app.indexing.publisher import GenerationPublisher

    topic = _seed_generation(db_session)
    milvus = FakeGenerationIndex()
    es = FakeGenerationIndex()
    profile = EmbeddingProfile("test", "model-v1", 2, "COSINE", True)

    result = GenerationPublisher(
        db_session, milvus, es, profile, embedder=lambda texts: [[0.1, 0.2]]
    ).build(topic.kb_uid, "new", expected_old="old")

    db_session.refresh(topic)
    assert result.status == "succeeded"
    assert result.row_count == 1
    assert topic.active_index_generation == "new"
    assert milvus.rows[0]["embedding_model_version"] == profile.profile_id


def test_index_generation_can_differ_from_file_content_versions(db_session):
    from backend.app.models.knowledge_types import StageStatus
    from engine.app.indexing.profiles import EmbeddingProfile
    from engine.app.indexing.publisher import GenerationPublisher

    topic = KnowledgeTopic(
        tenant_id="tenant-a",
        owner_user_id="alice",
        name="KB",
        active_index_generation=None,
    )
    db_session.add(topic)
    db_session.flush()
    item_a = KnowledgeItem(tenant_id="tenant-a", kb_uid=topic.kb_uid, title="A", content="a")
    item_b = KnowledgeItem(tenant_id="tenant-a", kb_uid=topic.kb_uid, title="B", content="b")
    db_session.add_all([item_a, item_b])
    db_session.flush()
    for file_uid, item, text in [
        ("file-a", item_a, "alpha text"),
        ("file-b", item_b, "beta text"),
    ]:
        db_session.add(
            KnowledgeFile(
                tenant_id="tenant-a",
                kb_uid=topic.kb_uid,
                file_uid=file_uid,
                item_id=item.id,
                original_filename=f"{file_uid}.pdf",
                parse_status=StageStatus.SUCCEEDED.value,
                parsed_content_version=1,
            )
        )
        db_session.add(
            KnowledgeChunk(
                tenant_id="tenant-a",
                kb_uid=topic.kb_uid,
                file_uid=file_uid,
                item_id=item.id,
                generation="1",
                chunk_uid=f"chunk-{file_uid}",
                chunk_text=text,
                chunk_type="child",
            )
        )
    db_session.commit()
    milvus = FakeGenerationIndex()
    es = FakeGenerationIndex()
    profile = EmbeddingProfile("test", "model-v1", 2, "COSINE", True)

    result = GenerationPublisher(
        db_session,
        milvus,
        es,
        profile,
        embedder=lambda texts: [[0.1, 0.2] for _ in texts],
    ).build(topic.kb_uid, "kb-index-snapshot", expected_old=None)

    assert result.status == "succeeded"
    assert result.row_count == 2
    assert {row["file_uid"] for row in milvus.rows} == {"file-a", "file-b"}
    assert {row["generation"] for row in milvus.rows} == {"kb-index-snapshot"}
