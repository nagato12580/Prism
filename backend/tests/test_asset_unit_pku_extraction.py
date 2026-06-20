import json

from backend.app.prompts.asset_parse import (
    ASSET_UNIT_PKU_RELATION_TYPES,
    ASSET_UNIT_PKU_UNIT_TYPES,
    build_asset_unit_pku_extraction_messages,
)


def test_build_asset_unit_pku_extraction_messages_include_required_schema():
    system_prompt, user_message = build_asset_unit_pku_extraction_messages(
        unit_id="unit-1",
        title="PKU 沉淀流程",
        summary="确认后的资产单元需要抽取为原子个人知识单元。",
        content="确认后的资产单元必须沉淀为 PKU，并与相关 PKU 建立关系。",
        source_asset_ids=["asset-1", "asset-2"],
    )

    request = json.loads(user_message)

    assert "JSON" in system_prompt
    assert request["source_unit"] == {
        "id": "unit-1",
        "title": "PKU 沉淀流程",
        "summary": "确认后的资产单元需要抽取为原子个人知识单元。",
        "content": "确认后的资产单元必须沉淀为 PKU，并与相关 PKU 建立关系。",
        "source_asset_ids": ["asset-1", "asset-2"],
    }
    assert request["allowed_unit_types"] == ASSET_UNIT_PKU_UNIT_TYPES
    assert request["allowed_relation_types"] == ASSET_UNIT_PKU_RELATION_TYPES
    assert request["json_shape"] == {
        "pkus": [
            {
                "local_id": "pku_1",
                "statement": "可独立复用的原子知识陈述",
                "normalized_statement": "去除语气词和上下文依赖后的规范陈述",
                "unit_type": ASSET_UNIT_PKU_UNIT_TYPES,
                "keywords": ["关键词"],
                "domains": ["领域"],
                "entities": ["实体"],
                "concepts": ["概念"],
                "confidence": 0.0,
                "evidence": "来自资产单元正文的证据摘录",
            }
        ],
        "relations": [
            {
                "source_local_id": "pku_1",
                "target_local_id": "pku_2",
                "relation_type": ASSET_UNIT_PKU_RELATION_TYPES,
                "reason": "关系判断依据",
                "confidence": 0.0,
            }
        ],
    }


def test_parse_asset_unit_pku_extraction_keeps_valid_pkus_and_relations():
    from backend.app.services.knowledge_governance import _parse_asset_unit_pku_extraction

    result = _parse_asset_unit_pku_extraction(
        {
            "pkus": [
                {
                    "local_id": "pku_1",
                    "statement": "PKU 抽取必须保留原文中的精确阈值。",
                    "unit_type": "rule",
                    "evidence_span": "保留技术术语的原文精确措辞，例如 ≥50人月。",
                    "keywords": ["PKU", "阈值"],
                    "concepts": ["PKU"],
                    "entities": [],
                    "domains": ["知识治理"],
                    "group": "抽取规则",
                    "confidence": 0.88,
                    "reason": "规则包含必须要求。",
                },
                {"local_id": "pku_bad", "statement": "非法类型会被丢弃。", "unit_type": "bad_type"},
            ],
            "relations": [
                {
                    "source_local_id": "pku_1",
                    "target_local_id": "pku_bad",
                    "relation_type": "supports",
                    "confidence": 0.7,
                    "reason": "测试关系。",
                }
            ],
        },
        llm_model="qwen-plus",
    )

    assert len(result.pkus) == 1
    assert result.pkus[0].local_id == "pku_1"
    assert result.pkus[0].unit_type == "rule"
    assert result.pkus[0].confidence == 0.88
    assert result.pkus[0].llm_model == "qwen-plus"
    assert len(result.relations) == 1
    assert result.relations[0].from_ref == "pku_1"
    assert result.relations[0].to_ref == "pku_bad"


def test_parse_asset_unit_pku_extraction_accepts_concept_style_llm_output():
    from backend.app.services.knowledge_governance import _parse_asset_unit_pku_extraction

    result = _parse_asset_unit_pku_extraction(
        {
            "concepts": [
                {
                    "name": "PKU 抽取流程",
                    "type": "method",
                    "description": "PKU 抽取流程先从资产单元中提取细粒度知识点，再识别知识点之间的前置关系。",
                    "aliases": ["个人知识单元抽取"],
                    "category": "知识治理",
                    "tags": ["PKU", "抽取"],
                    "group": "PKU 沉淀",
                    "confidence": 0.9,
                },
                {
                    "name": "PKU 关系约束",
                    "type": "constraint",
                    "description": "PKU 关系只能引用本次抽取结果中的知识点，不能指向不存在的节点。",
                    "category": "知识治理",
                    "tags": ["PKU", "关系"],
                    "confidence": 0.86,
                },
            ],
            "relations": [
                {
                    "from": "PKU 抽取流程",
                    "to": "PKU 关系约束",
                    "type": "prerequisite_of",
                    "confidence": 0.78,
                }
            ],
        },
        llm_model="qwen-plus",
    )

    assert len(result.pkus) == 2
    assert result.pkus[0].local_id == "PKU 抽取流程"
    assert result.pkus[0].statement == "PKU 抽取流程先从资产单元中提取细粒度知识点，再识别知识点之间的前置关系。"
    assert result.pkus[0].unit_type == "method"
    assert result.pkus[0].concepts == ["个人知识单元抽取"]
    assert result.pkus[0].domains == ["知识治理"]
    assert result.pkus[0].keywords == ["PKU", "抽取"]
    assert len(result.relations) == 1
    assert result.relations[0].from_ref == "PKU 抽取流程"
    assert result.relations[0].to_ref == "PKU 关系约束"
    assert result.relations[0].relation_type == "prerequisite_of"


def test_extract_asset_unit_pkus_uses_main_llm(monkeypatch):
    from backend.app.models import PersonalAssetUnit
    from backend.app.services import knowledge_governance as kg

    captured = {}

    class FakeMessage:
        content = (
            '{"pkus":[{"local_id":"pku_1","statement":"资产单元确认后使用主 LLM 抽取 PKU。",'
            '"unit_type":"method","evidence_span":"使用主 LLM 抽取多条 PKU。","confidence":0.9}],'
            '"relations":[]}'
        )

    class FakeChoice:
        message = FakeMessage()

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return type("Response", (), {"choices": [FakeChoice()]})()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr(kg.settings, "LLM_API_BASE", "http://llm.local/v1")
    monkeypatch.setattr(kg.settings, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(kg.settings, "LLM_MODEL", "qwen-plus")
    monkeypatch.setattr(kg, "OpenAI", lambda base_url, api_key: FakeClient())

    unit = PersonalAssetUnit(
        id="unit-1",
        title="PKU 沉淀",
        summary="确认后使用主 LLM 抽取 PKU。",
        content="使用主 LLM 抽取多条 PKU。",
        category="知识治理",
        tags=["PKU"],
        source_asset_ids=["asset-1"],
    )

    result = kg._extract_asset_unit_pkus_with_llm(unit)

    assert captured["model"] == "qwen-plus"
    assert result.llm_model == "qwen-plus"
    assert result.pkus[0].unit_type == "method"


def _confirmed_personal_asset_unit(**overrides):
    from backend.app.models import PersonalAssetUnit

    values = {
        "title": "PKU 沉淀流程",
        "content": "确认后的资产单元需要沉淀为多条可治理的个人知识单元。",
        "summary": "资产单元确认后沉淀 PKU。",
        "category": "知识治理",
        "tags": ["PKU", "治理"],
        "source_asset_ids": ["asset-1", "asset-2"],
        "confidence": {"overall": 0.9},
        "status": "confirmed",
        "user_id": "default-user",
    }
    values.update(overrides)
    return PersonalAssetUnit(**values)


def test_asset_unit_settlement_persists_multiple_llm_pkus(db_session, monkeypatch):
    from backend.app.models import PersonalKnowledgeUnit
    from backend.app.services import knowledge_governance as kg

    unit = _confirmed_personal_asset_unit()
    db_session.add(unit)
    db_session.flush()

    monkeypatch.setattr(
        kg,
        "_extract_asset_unit_pkus_with_llm",
        lambda unit: kg.AssetUnitPKUExtraction(
            pkus=[
                kg.ExtractedPKU(
                    local_id="pku_1",
                    statement="确认后的资产单元应该沉淀为原子 PKU。",
                    unit_type="method",
                    evidence_span="确认后的资产单元需要沉淀为多条可治理的个人知识单元。",
                    keywords=["PKU"],
                    concepts=["资产单元"],
                    entities=[],
                    domains=["知识治理"],
                    group="沉淀流程",
                    confidence=0.91,
                    reason="流程型陈述",
                    llm_model="qwen-plus",
                ),
                kg.ExtractedPKU(
                    local_id="pku_2",
                    statement="每条 PKU 必须保留原文证据。",
                    unit_type="rule",
                    evidence_span="多条可治理的个人知识单元",
                    keywords=["证据"],
                    concepts=["PKU"],
                    entities=[],
                    domains=["知识治理"],
                    group="沉淀规则",
                    confidence=0.88,
                    reason="规则型陈述",
                    llm_model="qwen-plus",
                ),
            ],
            relations=[],
            llm_model="qwen-plus",
        ),
    )

    result = kg.settle_personal_asset_unit_to_governance(db_session, unit)
    db_session.commit()

    assert result.pku_count == 2
    pkus = db_session.query(PersonalKnowledgeUnit).filter_by(source_kind="personal_asset_unit").all()
    assert len(pkus) == 2
    assert {pku.unit_type for pku in pkus} == {"method", "rule"}
    assert {pku.llm_model for pku in pkus} == {"qwen-plus"}


def test_asset_unit_settlement_falls_back_to_summary_when_llm_empty(db_session, monkeypatch):
    from backend.app.models import PersonalKnowledgeUnit
    from backend.app.services import knowledge_governance as kg

    unit = _confirmed_personal_asset_unit(
        summary="资产单元确认后生成一条摘要 PKU。",
        content="原始内容用于 fallback PKU 的证据片段。",
    )
    db_session.add(unit)
    db_session.flush()

    monkeypatch.setattr(
        kg,
        "_extract_asset_unit_pkus_with_llm",
        lambda unit: kg.AssetUnitPKUExtraction(pkus=[], relations=[], llm_model="qwen-plus"),
    )

    result = kg.settle_personal_asset_unit_to_governance(db_session, unit)
    db_session.commit()

    assert result.pku_count == 1
    pku = db_session.query(PersonalKnowledgeUnit).filter_by(source_kind="personal_asset_unit").one()
    assert pku.statement == unit.summary
    assert pku.evidence_span == unit.content
    assert pku.llm_model == ""


def test_asset_unit_settlement_persists_llm_pku_relations(db_session, monkeypatch):
    from backend.app.models import PKURelation
    from backend.app.services import knowledge_governance as kg

    unit = _confirmed_personal_asset_unit()
    db_session.add(unit)
    db_session.flush()

    monkeypatch.setattr(
        kg,
        "_extract_asset_unit_pkus_with_llm",
        lambda unit: kg.AssetUnitPKUExtraction(
            pkus=[
                kg.ExtractedPKU(
                    local_id="pku_1",
                    statement="先确认资产单元。",
                    unit_type="method",
                    evidence_span="确认后的资产单元",
                    keywords=["确认"],
                    concepts=["资产单元"],
                    entities=[],
                    domains=["知识治理"],
                    group="沉淀流程",
                    confidence=0.9,
                    reason="前置步骤",
                    llm_model="qwen-plus",
                ),
                kg.ExtractedPKU(
                    local_id="pku_2",
                    statement="再沉淀个人知识单元。",
                    unit_type="method",
                    evidence_span="沉淀为多条可治理的个人知识单元",
                    keywords=["沉淀"],
                    concepts=["个人知识单元"],
                    entities=[],
                    domains=["知识治理"],
                    group="沉淀流程",
                    confidence=0.89,
                    reason="后续步骤",
                    llm_model="qwen-plus",
                ),
            ],
            relations=[
                kg.ExtractedPKURelation(
                    from_ref="pku_1",
                    to_ref="pku_2",
                    relation_type="prerequisite_of",
                    confidence=0.86,
                    reason="确认是沉淀的前置条件",
                )
            ],
            llm_model="qwen-plus",
        ),
    )

    kg.settle_personal_asset_unit_to_governance(db_session, unit)
    db_session.commit()

    relation = db_session.query(PKURelation).one()
    assert relation.source_kind == "personal_asset_unit"
    assert relation.source_id == unit.id
    assert relation.llm_model == "qwen-plus"


def test_asset_unit_settlement_reuses_ckp_when_vector_similarity_is_high(db_session, monkeypatch):
    from backend.app.models import CanonicalKnowledgePoint, PKUCanonicalLink
    from backend.app.services import knowledge_governance as kg

    first_unit = _confirmed_personal_asset_unit(title="Metadata filters", summary="Metadata filters constrain retrieval.")
    second_unit = _confirmed_personal_asset_unit(
        title="Retrieval filtering",
        summary="Filtering retrieval by metadata narrows the candidate result set.",
    )
    db_session.add_all([first_unit, second_unit])
    db_session.flush()

    statements = {
        first_unit.id: "Metadata filters restrict retrieval results by project or source.",
        second_unit.id: "Filtering search results with metadata narrows retrieval by project and source.",
    }

    monkeypatch.setattr(
        kg,
        "_extract_asset_unit_pkus_with_llm",
        lambda unit: kg.AssetUnitPKUExtraction(
            pkus=[
                kg.ExtractedPKU(
                    local_id=f"pku_{unit.id}",
                    statement=statements[unit.id],
                    unit_type="method",
                    evidence_span=unit.summary or "",
                    keywords=["metadata", "retrieval", "project"],
                    concepts=["metadata filter"],
                    entities=[],
                    domains=["RAG"],
                    group="retrieval",
                    confidence=0.9,
                    reason="test",
                    llm_model="qwen-plus",
                )
            ],
            relations=[],
            llm_model="qwen-plus",
        ),
    )
    monkeypatch.setattr(kg, "upsert_ckp_vector", lambda ckp: f"ckp:{ckp.id}")

    kg.settle_personal_asset_unit_to_governance(db_session, first_unit)
    db_session.flush()
    existing_ckp = db_session.query(CanonicalKnowledgePoint).one()

    def fake_search_ckp_vectors(*, text, user_id, canonical_type="", top_k=8):
        return [{"ckp_id": existing_ckp.id, "score": 0.83}]

    monkeypatch.setattr(kg, "search_ckp_vectors", fake_search_ckp_vectors)

    kg.settle_personal_asset_unit_to_governance(db_session, second_unit)
    db_session.commit()

    assert db_session.query(CanonicalKnowledgePoint).count() == 1
    assert db_session.query(PKUCanonicalLink).count() == 2


def test_asset_unit_settlement_uses_llm_for_mid_vector_similarity(db_session, monkeypatch):
    from backend.app.models import CanonicalKnowledgePoint, PKUCanonicalLink
    from backend.app.services import knowledge_governance as kg

    first_unit = _confirmed_personal_asset_unit(title="Hybrid retrieval", summary="Hybrid retrieval combines signals.")
    second_unit = _confirmed_personal_asset_unit(
        title="Combined retrieval",
        summary="Combined retrieval uses keyword and vector evidence together.",
    )
    db_session.add_all([first_unit, second_unit])
    db_session.flush()

    monkeypatch.setattr(
        kg,
        "_extract_asset_unit_pkus_with_llm",
        lambda unit: kg.AssetUnitPKUExtraction(
            pkus=[
                kg.ExtractedPKU(
                    local_id=f"pku_{unit.id}",
                    statement=unit.summary or "",
                    unit_type="method",
                    evidence_span=unit.summary or "",
                    keywords=["retrieval", "hybrid"],
                    concepts=["retrieval"],
                    entities=[],
                    domains=["RAG"],
                    group="retrieval",
                    confidence=0.9,
                    reason="test",
                    llm_model="qwen-plus",
                )
            ],
            relations=[],
            llm_model="qwen-plus",
        ),
    )
    monkeypatch.setattr(kg, "upsert_ckp_vector", lambda ckp: f"ckp:{ckp.id}")

    kg.settle_personal_asset_unit_to_governance(db_session, first_unit)
    db_session.flush()
    existing_ckp = db_session.query(CanonicalKnowledgePoint).one()

    monkeypatch.setattr(
        kg,
        "search_ckp_vectors",
        lambda **kwargs: [{"ckp_id": existing_ckp.id, "score": 0.75}],
    )
    monkeypatch.setattr(
        kg,
        "_llm_ckp_same_as_decision",
        lambda statement, candidate, score: kg.CKPSemanticMatchDecision(
            same=True,
            confidence=0.86,
            reason="same retrieval method",
            llm_model="qwen-plus",
        ),
    )

    kg.settle_personal_asset_unit_to_governance(db_session, second_unit)
    db_session.commit()

    assert db_session.query(CanonicalKnowledgePoint).count() == 1
    assert db_session.query(PKUCanonicalLink).count() == 2


def test_asset_unit_settlement_creates_new_ckp_when_vector_similarity_is_low(db_session, monkeypatch):
    from backend.app.models import CanonicalKnowledgePoint
    from backend.app.services import knowledge_governance as kg

    first_unit = _confirmed_personal_asset_unit(title="Retrieval", summary="Metadata filters narrow retrieval.")
    second_unit = _confirmed_personal_asset_unit(title="Scheduling", summary="Calendar batching reduces context switches.")
    db_session.add_all([first_unit, second_unit])
    db_session.flush()

    monkeypatch.setattr(
        kg,
        "_extract_asset_unit_pkus_with_llm",
        lambda unit: kg.AssetUnitPKUExtraction(
            pkus=[
                kg.ExtractedPKU(
                    local_id=f"pku_{unit.id}",
                    statement=unit.summary or "",
                    unit_type="method",
                    evidence_span=unit.summary or "",
                    keywords=[unit.title],
                    concepts=[],
                    entities=[],
                    domains=[],
                    group="",
                    confidence=0.9,
                    reason="test",
                    llm_model="qwen-plus",
                )
            ],
            relations=[],
            llm_model="qwen-plus",
        ),
    )
    monkeypatch.setattr(kg, "upsert_ckp_vector", lambda ckp: f"ckp:{ckp.id}")

    kg.settle_personal_asset_unit_to_governance(db_session, first_unit)
    db_session.flush()
    existing_ckp = db_session.query(CanonicalKnowledgePoint).one()
    monkeypatch.setattr(
        kg,
        "search_ckp_vectors",
        lambda **kwargs: [{"ckp_id": existing_ckp.id, "score": 0.69}],
    )

    kg.settle_personal_asset_unit_to_governance(db_session, second_unit)
    db_session.commit()

    assert db_session.query(CanonicalKnowledgePoint).count() == 2


def test_find_existing_ckp_reuses_high_vector_similarity_without_keyword_overlap(db_session, monkeypatch):
    from backend.app.models import CanonicalKnowledgePoint
    from backend.app.services import knowledge_governance as kg

    ckp = CanonicalKnowledgePoint(
        user_id="default-user",
        canonical_type="method",
        title="Existing semantic candidate",
        canonical_statement="A stable knowledge point stored with different surface wording.",
        keywords=["alpha-only"],
        confidence=0.9,
    )
    db_session.add(ckp)
    db_session.commit()

    monkeypatch.setattr(
        kg,
        "search_ckp_vectors",
        lambda **kwargs: [{"ckp_id": ckp.id, "score": 0.81}],
    )

    result = kg._find_existing_ckp(
        db_session,
        user_id="default-user",
        statement="Different words that only the vector index says are equivalent.",
        keywords=["beta-only"],
        canonical_type="method",
    )

    assert result.id == ckp.id


def test_find_existing_ckp_uses_llm_for_mid_vector_similarity(db_session, monkeypatch):
    from backend.app.models import CanonicalKnowledgePoint
    from backend.app.services import knowledge_governance as kg

    ckp = CanonicalKnowledgePoint(
        user_id="default-user",
        canonical_type="method",
        title="Mid score semantic candidate",
        canonical_statement="A candidate that needs LLM confirmation.",
        keywords=["alpha-only"],
        confidence=0.9,
    )
    db_session.add(ckp)
    db_session.commit()

    monkeypatch.setattr(kg, "search_ckp_vectors", lambda **kwargs: [{"ckp_id": ckp.id, "score": 0.75}])
    monkeypatch.setattr(
        kg,
        "_llm_ckp_same_as_decision",
        lambda statement, candidate, score: kg.CKPSemanticMatchDecision(
            same=True,
            confidence=0.85,
            reason="same",
            llm_model="qwen-plus",
        ),
    )

    result = kg._find_existing_ckp(
        db_session,
        user_id="default-user",
        statement="A differently worded but equivalent candidate.",
        keywords=["beta-only"],
        canonical_type="method",
    )

    assert result.id == ckp.id


def test_find_existing_ckp_rejects_low_vector_similarity(db_session, monkeypatch):
    from backend.app.models import CanonicalKnowledgePoint
    from backend.app.services import knowledge_governance as kg

    ckp = CanonicalKnowledgePoint(
        user_id="default-user",
        canonical_type="method",
        title="Low score candidate",
        canonical_statement="A candidate below the semantic merge threshold.",
        keywords=["alpha-only"],
        confidence=0.9,
    )
    db_session.add(ckp)
    db_session.commit()

    monkeypatch.setattr(kg, "search_ckp_vectors", lambda **kwargs: [{"ckp_id": ckp.id, "score": 0.69}])

    result = kg._find_existing_ckp(
        db_session,
        user_id="default-user",
        statement="A different statement below threshold.",
        keywords=["beta-only"],
        canonical_type="method",
    )

    assert result is None


def test_find_existing_ckp_degrades_when_vector_search_fails(db_session, monkeypatch):
    from backend.app.models import CanonicalKnowledgePoint
    from backend.app.services import knowledge_governance as kg

    db_session.add(
        CanonicalKnowledgePoint(
            user_id="default-user",
            canonical_type="method",
            title="Existing candidate",
            canonical_statement="Existing candidate statement.",
            keywords=["alpha-only"],
            confidence=0.9,
        )
    )
    db_session.commit()

    def fail_search(**kwargs):
        raise RuntimeError("vector store unavailable")

    monkeypatch.setattr(kg, "search_ckp_vectors", fail_search)

    result = kg._find_existing_ckp(
        db_session,
        user_id="default-user",
        statement="No lexical match and vector search fails.",
        keywords=["beta-only"],
        canonical_type="method",
    )

    assert result is None


def test_asset_unit_settlement_does_not_call_ollama_type_classifier(db_session, monkeypatch):
    from backend.app.models import PersonalKnowledgeUnit
    from backend.app.services import knowledge_governance as kg

    unit = _confirmed_personal_asset_unit(
        summary="LLM 为空时用摘要生成 fallback PKU。",
        content="fallback 证据来自原始正文。",
    )
    db_session.add(unit)
    db_session.flush()

    monkeypatch.setattr(
        kg,
        "_extract_asset_unit_pkus_with_llm",
        lambda unit: kg.AssetUnitPKUExtraction(pkus=[], relations=[], llm_model="qwen-plus"),
    )
    monkeypatch.setattr(
        kg,
        "_ollama_pku_type_decision",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("Ollama type classifier should not be called")),
    )

    result = kg.settle_personal_asset_unit_to_governance(db_session, unit)
    db_session.commit()

    assert result.pku_count == 1
    assert db_session.query(PersonalKnowledgeUnit).filter_by(source_kind="personal_asset_unit").count() == 1
