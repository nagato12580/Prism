import os
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "sqlite:///./_stage_a_test.db"

from engine.app.extraction.prompts import parse_stage_a_json, parse_stage_a_relations, STAGE_A_EXTRACTION_PROMPT


def test_parse_stage_a_json_clean_array():
    raw = '[{"entity_type":"concept","surface":"混合检索","tier":"INFERRED","score":0.85,"evidence":"..."}]'
    result = parse_stage_a_json(raw)
    assert len(result) == 1
    assert result[0]["entity_type"] == "concept"
    assert result[0]["surface"] == "混合检索"
    assert result[0]["score"] == 0.85


def test_parse_stage_a_json_strips_fences_and_prose():
    raw = '好的，结果如下：\n```json\n[{"entity_type":"person","surface":"张三","tier":"EXTRACTED","score":1.0,"evidence":""}]\n```\n以上。'
    result = parse_stage_a_json(raw)
    assert len(result) == 1
    assert result[0]["surface"] == "张三"


def test_parse_stage_a_json_empty_returns_empty():
    assert parse_stage_a_json("") == []
    assert parse_stage_a_json("no json here") == []


def test_parse_stage_a_json_rejects_score_out_of_range():
    raw = '[{"entity_type":"concept","surface":"x","tier":"EXTRACTED","score":0.5,"evidence":""}]'
    result = parse_stage_a_json(raw)
    # EXTRACTED must be 1.0; invalid tier/score combos are dropped
    assert result == []


def test_prompt_contains_required_fields():
    for token in ["entity_type", "surface", "tier", "score", "evidence", "EXTRACTED", "INFERRED", "AMBIGUOUS"]:
        assert token in STAGE_A_EXTRACTION_PROMPT


from unittest.mock import patch

from backend.app.services.entity_extraction import EntityCandidate
from engine.app.extraction.stage_a import extract_entities_for_chunk


_FAKE_LLM_OUTPUT = (
    '{"entities": ['
    '{"entity_type":"concept","surface":"混合检索","tier":"INFERRED","score":0.85,"evidence":"结合向量与关键词"},'
    '{"entity_type":"method","surface":"RRF融合","tier":"EXTRACTED","score":1.0,"evidence":"RRF"}'
    ']}'
)


@patch("engine.app.extraction.stage_a.chat")
def test_extract_entities_for_chunk_returns_candidates(mock_chat):
    mock_chat.return_value = _FAKE_LLM_OUTPUT
    candidates = extract_entities_for_chunk("some chunk text", chunk_id="c1")
    assert len(candidates) == 2
    assert all(c.kind == "entity" for c in candidates)
    types = {c.entity_type for c in candidates}
    assert types == {"concept", "method"}
    concept = next(c for c in candidates if c.entity_type == "concept")
    assert concept.surface_text == "混合检索"
    assert concept.confidence == 0.85
    assert concept.extraction_method.startswith("llm_stage_a:INFERRED")


@patch("engine.app.extraction.stage_a.chat")
def test_extract_entities_for_chunk_llm_failure_preserves_deterministic_candidates(mock_chat):
    mock_chat.side_effect = RuntimeError("llm down")

    candidates = extract_entities_for_chunk("# MiniMind-O\n- Search Flow", chunk_id="c1")

    surfaces = {candidate.surface_text for candidate in candidates if candidate.kind == "entity"}
    methods = {candidate.extraction_method for candidate in candidates if candidate.kind == "entity"}

    assert surfaces == {"MiniMind-O", "Search Flow"}
    assert methods == {"deterministic_heading", "deterministic_list_item"}


from engine.app.extraction.stage_a import extract_stage_a_parallel


@patch("engine.app.extraction.stage_a.extract_entities_for_chunk")
def test_extract_stage_a_parallel_collects_all_chunks(mock_extract):
    mock_extract.side_effect = lambda text, chunk_id: [EntityCandidate(kind="entity", entity_type="concept", surface_text=chunk_id, confidence=1.0)]
    chunks = [(f"chunk-{i}", f"text {i}") for i in range(5)]
    result = extract_stage_a_parallel(chunks, max_workers=3)
    assert set(result.keys()) == {f"chunk-{i}" for i in range(5)}
    assert mock_extract.call_count == 5


@patch("engine.app.extraction.stage_a.extract_entities_for_chunk")
def test_extract_stage_a_parallel_isolates_chunk_failure(mock_extract):
    def fake(text, chunk_id):
        if chunk_id == "bad":
            raise RuntimeError("boom")
        return [EntityCandidate(kind="entity", entity_type="concept", surface_text=chunk_id, confidence=1.0)]
    mock_extract.side_effect = fake
    result = extract_stage_a_parallel([("bad", "x"), ("good", "y")], max_workers=2)
    assert result["good"] and result["good"][0].surface_text == "good"
    assert result.get("bad", []) == []  # failed chunk does not crash the batch


from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database import Base
from backend.app.models import EntityMention, KnowledgeChunk, KnowledgeEntity, KnowledgeItem
from backend.app.services.graph_projection import project_item_entities


class FakeGraph:
    def __init__(self):
        self.upserted_sources = []
        self.upserted_entities = []
        self.relations = []

    def delete_item_sources(self, item_id):
        pass

    def upsert_source(self, data):
        self.upserted_sources.append(data)

    def upsert_entity(self, data):
        self.upserted_entities.append(data)

    def relate(self, start_label, start_id, rel_type, end_label, end_id, props=None):
        self.relations.append((start_label, start_id, rel_type, end_label, end_id))


def _sqlite_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def test_project_item_entities_upserts_source_entity_and_mentioned_in():
    db = _sqlite_session()
    try:
        db.add(KnowledgeItem(id="i1", user_id="default-user", title="doc"))
        db.add(
            KnowledgeChunk(
                id="c1",
                item_id="i1",
                chunk_text="x",
                chunk_index=0,
                chunk_type="child",
            )
        )
        db.add(
            KnowledgeEntity(
                id="e1",
                user_id="default-user",
                entity_type="concept",
                canonical_name="混合检索",
                normalized_key="x",
                status="active",
            )
        )
        db.add(
            EntityMention(
                id="m1",
                entity_id="e1",
                source_kind="document_chunk",
                source_id="c1",
                item_id="i1",
                chunk_id="c1",
                surface_text="混合检索",
                normalized_key="x",
                confidence=0.85,
                extraction_method="llm_stage_a:INFERRED",
            )
        )
        db.commit()

        fake = FakeGraph()
        edges = project_item_entities(db, fake, item_id="i1", user_id="default-user")

        assert any(s["item_id"] == "i1" for s in fake.upserted_sources)
        assert any(e["id"] == "e1" for e in fake.upserted_entities)
        assert ("Entity", "e1", "MENTIONED_IN", "Source", "document_chunk:c1") in fake.relations
        assert edges == 1
    finally:
        db.close()


class FakeGraphWithDelete:
    def __init__(self):
        self.upserted_sources = []
        self.upserted_entities = []
        self.relations = []
        self.deleted_item_ids = []

    def delete_item_sources(self, item_id):
        self.deleted_item_ids.append(item_id)

    def upsert_source(self, data):
        self.upserted_sources.append(data)

    def upsert_entity(self, data):
        self.upserted_entities.append(data)

    def relate(self, start_label, start_id, rel_type, end_label, end_id, props=None):
        self.relations.append((start_label, start_id, rel_type, end_label, end_id))


def test_project_item_entities_deletes_old_sources_before_projecting():
    from backend.app.database import Base, engine as _engine
    from backend.app.models import KnowledgeItem, KnowledgeChunk, KnowledgeEntity, EntityMention
    from sqlalchemy.orm import sessionmaker
    Base.metadata.create_all(_engine)
    db = sessionmaker(bind=_engine)()
    try:
        # clean any previous test data with the same keys
        db.query(EntityMention).delete()
        db.query(KnowledgeEntity).delete()
        db.query(KnowledgeChunk).delete()
        db.query(KnowledgeItem).delete()
        db.commit()
        db.add(KnowledgeItem(id="i1", user_id="default-user", title="doc"))
        db.add(KnowledgeChunk(id="c1", item_id="i1", chunk_text="x", chunk_index=0, chunk_type="child"))
        ent = KnowledgeEntity(id="e1", user_id="default-user", entity_type="concept", canonical_name="K", normalized_key="k", status="active")
        db.add(ent); db.flush()
        db.add(EntityMention(id="m1", entity_id="e1", source_kind="document_chunk", source_id="c1", item_id="i1", chunk_id="c1", surface_text="K", normalized_key="k", confidence=0.85, extraction_method="llm_stage_a:INFERRED"))
        db.commit()

        fake = FakeGraphWithDelete()
        project_item_entities(db, fake, item_id="i1", user_id="default-user")

        # cleanup MUST run first, scoped to this item_id
        assert fake.deleted_item_ids == ["i1"]
        # and then re-projected
        assert any(e["id"] == "e1" for e in fake.upserted_entities)
    finally:
        db.close()


def test_parse_stage_a_relations_clean():
    raw = '{"entities":[],"relations":[{"subject":"混合检索","predicate":"uses","object":"RRF融合","tier":"INFERRED","score":0.85}]}'
    rels = parse_stage_a_relations(raw)
    assert len(rels) == 1
    assert rels[0]["subject"] == "混合检索"
    assert rels[0]["predicate"] == "uses"
    assert rels[0]["object"] == "RRF融合"
    assert rels[0]["score"] == 0.85


def test_parse_stage_a_relations_rejects_bad_score():
    raw = '{"entities":[],"relations":[{"subject":"a","predicate":"related_to","object":"b","tier":"EXTRACTED","score":0.5}]}'
    assert parse_stage_a_relations(raw) == []


@patch("engine.app.extraction.stage_a.chat")
def test_extract_entities_for_chunk_returns_relation_candidates(mock_chat):
    mock_chat.return_value = (
        '{"entities":['
        '{"entity_type":"concept","surface":"混合检索","tier":"EXTRACTED","score":1.0,"evidence":""}'
        '],"relations":['
        '{"subject":"混合检索","predicate":"uses","object":"RRF融合","tier":"INFERRED","score":0.85}'
        ']}'
    )
    from engine.app.extraction.stage_a import extract_entities_for_chunk
    cands = extract_entities_for_chunk("text", chunk_id="c1")
    rels = [c for c in cands if c.kind == "relation"]
    assert len(rels) == 1
    r = rels[0]
    assert r.subject_surface == "混合检索"
    assert r.predicate == "uses"
    assert r.object_surface == "RRF融合"
    assert r.confidence == 0.85
    assert r.extraction_method.startswith("llm_stage_a:INFERRED")


@patch("engine.app.extraction.stage_a.chat")
def test_extract_entities_for_chunk_merges_deterministic_and_llm_candidates(mock_chat):
    mock_chat.return_value = (
        '{"entities":['
        '{"entity_type":"concept","surface":"Search Flow","tier":"INFERRED","score":0.85,"evidence":"Search Flow"}'
        '],"relations":['
        '{"subject":"Search Flow","predicate":"uses","object":"RRF","tier":"INFERRED","score":0.85}'
        ']}'
    )

    cands = extract_entities_for_chunk("# MiniMind-O\n- Search Flow", chunk_id="c1")

    entities = [c for c in cands if c.kind == "entity"]
    relations = [c for c in cands if c.kind == "relation"]
    search_flow_methods = [
        c.extraction_method for c in entities if c.surface_text == "Search Flow"
    ]

    assert len(entities) == 3
    assert len(relations) == 1
    assert any(
        c.surface_text == "MiniMind-O" and c.extraction_method == "deterministic_heading"
        for c in entities
    )
    assert "deterministic_list_item" in search_flow_methods
    assert any(c.extraction_method.startswith("llm_stage_a:INFERRED") for c in entities)


@patch("engine.app.extraction.stage_a.chat")
def test_extract_entities_for_chunk_extracts_deterministic_candidates_beyond_llm_truncation(mock_chat):
    mock_chat.return_value = '{"entities":[],"relations":[]}'

    long_text = ("A" * 4000) + "\n# Tail Heading\n- Tail Item"
    cands = extract_entities_for_chunk(long_text, chunk_id="c1")

    surfaces = {candidate.surface_text for candidate in cands if candidate.kind == "entity"}

    assert "Tail Heading" in surfaces
    assert "Tail Item" in surfaces


def test_project_item_entities_projects_relation_as_related_to():
    from backend.app.database import Base, engine as _engine
    from backend.app.models import KnowledgeItem, KnowledgeChunk, KnowledgeEntity, EntityMention, EntityRelation
    from sqlalchemy.orm import sessionmaker
    Base.metadata.create_all(_engine)
    db = sessionmaker(bind=_engine)()
    try:
        db.query(EntityRelation).delete()
        db.query(EntityMention).delete()
        db.query(KnowledgeEntity).delete()
        db.query(KnowledgeChunk).delete()
        db.query(KnowledgeItem).delete()
        db.commit()
        db.add(KnowledgeItem(id="i1", user_id="default-user", title="doc"))
        db.add(KnowledgeChunk(id="c1", item_id="i1", chunk_text="x", chunk_index=0, chunk_type="child"))
        e1 = KnowledgeEntity(id="e1", user_id="default-user", entity_type="concept", canonical_name="混合检索", normalized_key="a", status="active")
        e2 = KnowledgeEntity(id="e2", user_id="default-user", entity_type="method", canonical_name="RRF融合", normalized_key="b", status="active")
        db.add_all([e1, e2]); db.flush()
        db.add(EntityMention(id="m1", entity_id="e1", source_kind="document_chunk", source_id="c1", item_id="i1", chunk_id="c1", surface_text="混合检索", normalized_key="a", confidence=1.0, extraction_method="llm_stage_a:EXTRACTED"))
        db.add(EntityRelation(id="r1", subject_entity_id="e1", predicate="uses", object_entity_id="e2", relation_key="rk1", source_kind="document_chunk", source_id="c1", confidence=0.85, extraction_method="llm_stage_a:INFERRED"))
        db.commit()
        fake = FakeGraphWithDelete()
        project_item_entities(db, fake, item_id="i1", user_id="default-user")
        assert ("Entity", "e1", "RELATED_TO", "Entity", "e2") in fake.relations
    finally:
        db.close()
