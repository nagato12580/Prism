from backend.app.models.memory import MemoryEntity, MemoryRelation
from backend.app.services import memory_entity


def _fake_llm(items):
    def _call(content):
        return items
    return _call


def test_extract_links_entities_and_relations(db_session, monkeypatch):
    entities_data = [
        {"name": "Prism", "type": "project", "description": "个人知识助手"},
        {"name": "Milvus", "type": "technology", "description": "向量数据库"},
    ]
    monkeypatch.setattr(memory_entity, "_call_entity_llm", _fake_llm(entities_data))

    linked = memory_entity.extract_and_link_entities(
        db_session, content="Prism 用 Milvus 做向量检索", source_id="s1", statement_id="s1"
    )

    assert len(linked) == 2
    names = {e.name for e in linked}
    assert names == {"Prism", "Milvus"}
    for e in linked:
        assert e.status == "confirmed"
        assert e.mention_count == 1
        assert "s1" in (e.source_ids or [])

    relations = db_session.query(MemoryRelation).all()
    assert len(relations) == 1
    assert relations[0].predicate == "related_to"
    assert relations[0].statement_id == "s1"


def test_extract_upserts_existing_entity_increments_mention(db_session, monkeypatch):
    existing = MemoryEntity(
        id="e-prism",
        user_id="default-user",
        name="Prism",
        entity_type="project",
        description="",
        mention_count=1,
        status="confirmed",
        source_ids=["s0"],
    )
    db_session.add(existing)
    db_session.commit()

    monkeypatch.setattr(memory_entity, "_call_entity_llm", _fake_llm([
        {"name": "Prism", "type": "project", "description": "知识助手"},
    ]))

    linked = memory_entity.extract_and_link_entities(
        db_session, content="Prism 又提到", source_id="s2"
    )

    assert len(linked) == 1
    db_session.refresh(existing)
    assert existing.mention_count == 2
    assert "s2" in (existing.source_ids or [])
    assert existing.description == "知识助手"


def test_extract_returns_empty_when_no_entities(db_session, monkeypatch):
    monkeypatch.setattr(memory_entity, "_call_entity_llm", _fake_llm([]))
    assert memory_entity.extract_and_link_entities(db_session, content="x", source_id="s") == []


def test_extract_returns_empty_on_llm_exception(db_session, monkeypatch):
    def boom(content):
        raise RuntimeError("llm down")
    monkeypatch.setattr(memory_entity, "_call_entity_llm", boom)
    assert memory_entity.extract_and_link_entities(db_session, content="x", source_id="s") == []


def test_extract_skips_overly_generic_names(db_session, monkeypatch):
    monkeypatch.setattr(memory_entity, "_call_entity_llm", _fake_llm([
        {"name": "", "type": "topic", "description": ""},
        {"name": "   ", "type": "topic", "description": ""},
    ]))
    assert memory_entity.extract_and_link_entities(db_session, content="x", source_id="s") == []


def test_extract_dedupes_relations_on_repeat(db_session, monkeypatch):
    monkeypatch.setattr(memory_entity, "_call_entity_llm", _fake_llm([
        {"name": "A", "type": "topic", "description": ""},
        {"name": "B", "type": "topic", "description": ""},
    ]))
    memory_entity.extract_and_link_entities(db_session, content="A and B", source_id="s1")
    memory_entity.extract_and_link_entities(db_session, content="A and B again", source_id="s2")

    relations = db_session.query(MemoryRelation).filter(MemoryRelation.predicate == "related_to").all()
    assert len(relations) == 1
