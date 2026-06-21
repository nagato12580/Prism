import json
import logging
from types import SimpleNamespace

from backend.app.prompts.asset_parse import (
    ASSET_UNIT_PKU_RELATION_TYPES,
    ASSET_UNIT_PKU_UNIT_TYPES,
    build_knowledge_synthesis_messages,
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


def test_build_ckp_topic_extraction_messages_group_pkus_into_topics():
    from backend.app.prompts.asset_parse import build_ckp_topic_extraction_messages

    system_prompt, user_message = build_ckp_topic_extraction_messages(
        source_kind="knowledge_item",
        source_id="item-1",
        title="LLM fine-tuning guide",
        summary="LoRA, SFT data, and evaluation practices.",
        category="AI",
        tags=["fine-tuning", "LoRA"],
        pkus=[
            {
                "ref": "pku_1",
                "statement": "LoRA reduces trainable parameters with low-rank matrices.",
                "unit_type": "method",
                "keywords": ["LoRA", "fine-tuning"],
                "concepts": ["parameter efficient tuning"],
                "entities": [],
                "domains": ["AI"],
                "evidence_span": "LoRA uses low-rank matrices.",
            },
            {
                "ref": "pku_2",
                "statement": "Fine-tuning evaluation should use a held-out validation set.",
                "unit_type": "rule",
                "keywords": ["evaluation", "fine-tuning"],
                "concepts": ["validation"],
                "entities": [],
                "domains": ["AI"],
                "evidence_span": "Use held-out validation data.",
            },
        ],
    )

    request = json.loads(user_message)

    assert "JSON" in system_prompt
    assert request["source"]["kind"] == "knowledge_item"
    assert request["source"]["id"] == "item-1"
    assert request["source"]["title"] == "LLM fine-tuning guide"
    assert request["pkus"][0]["ref"] == "pku_1"
    assert request["json_shape"]["topics"][0]["title"] == "Topic noun phrase"
    assert request["json_shape"]["topics"][0]["member_pku_refs"] == ["pku_1", "pku_2"]
    assert any("topic" in rule.lower() for rule in request["rules"])


def test_parse_ckp_topic_extraction_keeps_valid_topics():
    from backend.app.services import knowledge_governance as kg

    result = kg._parse_ckp_topic_extraction(
        {
            "topics": [
                {
                    "local_id": "topic_1",
                    "title": "LLM fine-tuning",
                    "description": "Methods and rules for adapting large language models.",
                    "keywords": ["fine-tuning", "LoRA"],
                    "concepts": ["SFT"],
                    "domains": ["AI"],
                    "entities": [],
                    "member_pku_refs": ["pku_1", "pku_2"],
                    "confidence": 0.88,
                    "reason": "Both PKUs discuss fine-tuning.",
                },
                {
                    "local_id": "bad",
                    "title": "",
                    "member_pku_refs": ["pku_3"],
                },
            ]
        },
        llm_model="qwen-plus",
    )

    assert len(result.topics) == 1
    assert result.topics[0].local_id == "topic_1"
    assert result.topics[0].title == "LLM fine-tuning"
    assert result.topics[0].member_pku_refs == ["pku_1", "pku_2"]
    assert result.topics[0].llm_model == "qwen-plus"


def test_build_ckp_parent_topic_assignment_messages_groups_child_topics():
    from backend.app.prompts.asset_parse import build_ckp_parent_topic_assignment_messages

    system_prompt, user_message = build_ckp_parent_topic_assignment_messages(
        source_kind="knowledge_item",
        source_id="item-1",
        title="LLM fine-tuning guide",
        summary="LoRA, data preparation, and evaluation practices.",
        category="AI",
        tags=["fine-tuning", "LoRA"],
        child_topics=[
            {
                "ref": "child_1",
                "title": "LoRA fine-tuning methods",
                "description": "Parameter-efficient methods for adapting LLMs.",
                "keywords": ["LoRA", "fine-tuning"],
                "concepts": ["parameter efficient tuning"],
                "domains": ["AI"],
                "entities": [],
                "member_pku_statements": ["LoRA reduces trainable parameters."],
            }
        ],
    )

    request = json.loads(user_message)
    assert "JSON" in system_prompt
    assert request["source"]["id"] == "item-1"
    assert request["child_topics"][0]["ref"] == "child_1"
    assert request["json_shape"]["parent_topics"][0]["title"] == "Broad topic noun phrase"
    assert request["json_shape"]["parent_topics"][0]["member_child_refs"] == ["child_1", "child_2"]
    assert any("parent" in rule.lower() for rule in request["rules"])


def test_parse_ckp_parent_topic_assignment_keeps_valid_parent_topics():
    from backend.app.services import knowledge_governance as kg

    result = kg._parse_ckp_parent_topic_assignment(
        {
            "parent_topics": [
                {
                    "local_id": "parent_1",
                    "title": "LLM fine-tuning",
                    "description": "Methods, rules, and evaluation knowledge for adapting LLMs.",
                    "keywords": ["fine-tuning", "LoRA"],
                    "concepts": ["SFT"],
                    "domains": ["AI"],
                    "entities": [],
                    "member_child_refs": ["child_1", "child_2"],
                    "confidence": 0.9,
                    "reason": "Both child topics discuss fine-tuning.",
                },
                {"local_id": "bad", "title": "", "member_child_refs": ["child_3"]},
            ]
        },
        llm_model="qwen-plus",
    )

    assert len(result.parent_topics) == 1
    assert result.parent_topics[0].local_id == "parent_1"
    assert result.parent_topics[0].title == "LLM fine-tuning"
    assert result.parent_topics[0].member_child_refs == ["child_1", "child_2"]
    assert result.parent_topics[0].llm_model == "qwen-plus"


def test_extract_ckp_topics_uses_main_llm(monkeypatch):
    from backend.app.services import knowledge_governance as kg

    captured = {}

    class FakeMessage:
        content = (
            '{"topics":[{"local_id":"topic_1","title":"LLM fine-tuning",'
            '"description":"Fine-tuning methods and rules.",'
            '"keywords":["fine-tuning"],"member_pku_refs":["pku_1"],'
            '"confidence":0.9,"reason":"shared topic"}]}'
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

    result = kg._extract_ckp_topics_with_llm(
        source_kind="knowledge_item",
        source_id="item-1",
        title="LLM guide",
        summary="Fine-tuning guide.",
        category="AI",
        tags=["fine-tuning"],
        pkus=[
            {
                "ref": "pku_1",
                "statement": "LoRA reduces trainable parameters.",
                "unit_type": "method",
                "keywords": ["LoRA"],
            }
        ],
    )

    assert captured["model"] == "qwen-plus"
    assert result.llm_model == "qwen-plus"
    assert result.topics[0].title == "LLM fine-tuning"


def test_build_knowledge_synthesis_messages_accept_legacy_asset_body():
    _system_prompt, user_message = build_knowledge_synthesis_messages(
        assets=[
            SimpleNamespace(
                id="asset-1",
                title="Metadata filter note",
                asset_kind="claim",
                summary="Metadata filters help retrieval.",
                body="Body text from the committed PersonalAssetItem shape.",
                category="RAG",
                tags=["metadata"],
                source_platform="manual",
            )
        ],
    )

    request = json.loads(user_message)

    assert request["assets"][0]["body"] == "Body text from the committed PersonalAssetItem shape."


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


def test_parse_asset_unit_pku_extraction_logs_rejection_diagnostics(caplog):
    from backend.app.services.knowledge_governance import _parse_asset_unit_pku_extraction

    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        result = _parse_asset_unit_pku_extraction(
            {
                "knowledge_units": [
                    {
                        "id": "ku_1",
                        "content": "DeepSeek may return a non-standard PKU container.",
                        "kind": "principle",
                    }
                ],
                "pkus": [
                    {"local_id": "missing_statement", "unit_type": "rule"},
                    {"local_id": "bad_type", "statement": "A fact-like item.", "unit_type": "principle"},
                    "not-a-dict",
                ],
            },
            llm_model="deepseek-v4-flash",
        )

    assert result.pkus == []
    record = next(record for record in caplog.records if "asset unit PKU parse produced no PKUs" in record.message)
    assert record.llm_model == "deepseek-v4-flash"
    assert record.top_level_keys == ["knowledge_units", "pkus"]
    assert record.raw_pku_count == 3
    assert record.parsed_pku_count == 0
    assert record.rejected_count == 3
    assert record.reject_reasons == ["missing_statement", "invalid_unit_type", "non_object_item"]
    assert record.sample_unit_types == ["rule", "principle"]


def test_parse_asset_unit_pku_extraction_accepts_unit_type_lists():
    from backend.app.services.knowledge_governance import _parse_asset_unit_pku_extraction

    result = _parse_asset_unit_pku_extraction(
        {
            "pkus": [
                {
                    "local_id": "pku_1",
                    "statement": "Fine-tuning means adapting a pretrained model to a target task.",
                    "unit_type": ["definition", "concept"],
                },
                {
                    "local_id": "pku_2",
                    "statement": "Fine-tuning can use LoRA adapters and validation monitoring.",
                    "unit_type": ["method", "observation"],
                },
                {
                    "local_id": "pku_3",
                    "statement": "Evaluation should use held-out data.",
                    "unit_type": ["unknown_type", "rule"],
                },
            ]
        },
        llm_model="deepseek-v4-flash",
    )

    assert [pku.local_id for pku in result.pkus] == ["pku_1", "pku_2", "pku_3"]
    assert [pku.unit_type for pku in result.pkus] == ["definition", "method", "rule"]


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


def test_extract_asset_unit_pkus_logs_llm_diagnostics_on_success(monkeypatch, caplog):
    from backend.app.models import PersonalAssetUnit
    from backend.app.services import knowledge_governance as kg

    class FakeMessage:
        content = (
            '{"pkus":[{"local_id":"pku_1","statement":"PKU extraction diagnostics record parsed counts.",'
            '"unit_type":"observation","evidence_span":"diagnostics record parsed counts","confidence":0.9}],'
            '"relations":[]}'
        )

    class FakeChoice:
        message = FakeMessage()

    class FakeCompletions:
        def create(self, **kwargs):
            return type("Response", (), {"choices": [FakeChoice()]})()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr(kg.settings, "LLM_API_BASE", "http://llm.local/v1")
    monkeypatch.setattr(kg.settings, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(kg.settings, "LLM_MODEL", "qwen-plus")
    monkeypatch.setattr(kg, "OpenAI", lambda base_url, api_key: FakeClient())

    unit = PersonalAssetUnit(id="unit-1", title="PKU diagnostics", content="diagnostics record parsed counts")

    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        result = kg._extract_asset_unit_pkus_with_llm(unit)

    assert len(result.pkus) == 1
    record = next(record for record in caplog.records if "asset unit PKU LLM extraction completed" in record.message)
    assert record.elapsed_ms >= 0
    assert record.model == "qwen-plus"
    assert record.json_empty is False
    assert record.pku_count == 1


def test_extract_asset_unit_pkus_logs_empty_json_and_zero_pku_count(monkeypatch, caplog):
    from backend.app.models import PersonalAssetUnit
    from backend.app.services import knowledge_governance as kg

    class FakeMessage:
        content = "{}"

    class FakeChoice:
        message = FakeMessage()

    class FakeCompletions:
        def create(self, **kwargs):
            return type("Response", (), {"choices": [FakeChoice()]})()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr(kg.settings, "LLM_API_BASE", "http://llm.local/v1")
    monkeypatch.setattr(kg.settings, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(kg.settings, "LLM_MODEL", "qwen-plus")
    monkeypatch.setattr(kg, "OpenAI", lambda base_url, api_key: FakeClient())

    unit = PersonalAssetUnit(id="unit-1", title="PKU diagnostics", content="empty extraction")

    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        result = kg._extract_asset_unit_pkus_with_llm(unit)

    assert result.pkus == []
    record = next(record for record in caplog.records if "asset unit PKU LLM extraction completed" in record.message)
    assert record.elapsed_ms >= 0
    assert record.model == "qwen-plus"
    assert record.json_empty is True
    assert record.pku_count == 0


def test_extract_asset_unit_pkus_logs_exception_diagnostics(monkeypatch, caplog):
    from backend.app.models import PersonalAssetUnit
    from backend.app.services import knowledge_governance as kg

    class FakeCompletions:
        def create(self, **kwargs):
            raise TimeoutError("llm request timed out")

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr(kg.settings, "LLM_API_BASE", "http://llm.local/v1")
    monkeypatch.setattr(kg.settings, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(kg.settings, "LLM_MODEL", "qwen-plus")
    monkeypatch.setattr(kg, "OpenAI", lambda base_url, api_key: FakeClient())

    unit = PersonalAssetUnit(id="unit-1", title="PKU diagnostics", content="timeout case")

    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        result = kg._extract_asset_unit_pkus_with_llm(unit)

    assert result.pkus == []
    record = next(record for record in caplog.records if "asset unit PKU LLM extraction failed" in record.message)
    assert record.elapsed_ms >= 0
    assert record.model == "qwen-plus"
    assert record.exception_type == "TimeoutError"
    assert record.exception_message == "llm request timed out"
    assert "test-key" not in record.getMessage()


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


def _single_topic_ckp_by_level(db_session, level):
    from backend.app.models import CanonicalKnowledgePoint

    matches = [
        ckp
        for ckp in (
            db_session.query(CanonicalKnowledgePoint)
            .filter(CanonicalKnowledgePoint.canonical_type == "topic")
            .all()
        )
        if (ckp.extra_meta or {}).get("topic_level") == level
    ]
    assert len(matches) == 1
    return matches[0]


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


def test_asset_unit_settlement_falls_back_to_summary_when_llm_empty(db_session, monkeypatch, caplog):
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

    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        result = kg.settle_personal_asset_unit_to_governance(db_session, unit)
        db_session.commit()

    assert result.pku_count == 1
    pku = db_session.query(PersonalKnowledgeUnit).filter_by(source_kind="personal_asset_unit").one()
    assert pku.statement == unit.summary
    assert pku.evidence_span == unit.content
    assert pku.llm_model == ""
    record = next(record for record in caplog.records if "asset unit PKU fallback activated" in record.message)
    assert record.unit_id == unit.id
    assert record.llm_model == "qwen-plus"
    assert record.llm_pku_count == 0
    assert record.fallback_created is True


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


def test_asset_unit_settlement_groups_pkus_under_topic_ckp_with_about_links(db_session, monkeypatch):
    from backend.app.models import CanonicalKnowledgePoint, CanonicalRelation, PKUCanonicalLink
    from backend.app.services import knowledge_governance as kg

    unit = _confirmed_personal_asset_unit(
        title="LLM fine-tuning note",
        summary="LoRA and evaluation practices.",
        category="AI",
        tags=["fine-tuning"],
    )
    db_session.add(unit)
    db_session.flush()
    monkeypatch.setattr(
        kg,
        "_extract_asset_unit_pkus_with_llm",
        lambda unit: kg.AssetUnitPKUExtraction(
            pkus=[
                kg.ExtractedPKU(
                    local_id="pku_1",
                    statement="LoRA reduces trainable parameters.",
                    unit_type="method",
                    evidence_span="LoRA reduces trainable parameters.",
                    keywords=["LoRA", "fine-tuning"],
                    concepts=["LoRA"],
                    entities=[],
                    domains=["AI"],
                    group="fine-tuning",
                    confidence=0.91,
                    reason="method",
                    llm_model="qwen-plus",
                ),
                kg.ExtractedPKU(
                    local_id="pku_2",
                    statement="Fine-tuning evaluation should use validation data.",
                    unit_type="rule",
                    evidence_span="Evaluation should use validation data.",
                    keywords=["evaluation", "fine-tuning"],
                    concepts=["validation"],
                    entities=[],
                    domains=["AI"],
                    group="fine-tuning",
                    confidence=0.87,
                    reason="rule",
                    llm_model="qwen-plus",
                ),
            ],
            relations=[],
            llm_model="qwen-plus",
        ),
    )
    monkeypatch.setattr(
        kg,
        "_extract_ckp_topics_with_llm",
        lambda **kwargs: kg.CKPTopicExtraction(
            topics=[
                kg.ExtractedCKPTopic(
                    local_id="topic_1",
                    title="LLM fine-tuning",
                    description="Methods and rules for adapting large language models.",
                    keywords=["fine-tuning"],
                    concepts=["LoRA", "validation"],
                    entities=[],
                    domains=["AI"],
                    member_pku_refs=["pku_1", "pku_2"],
                    confidence=0.9,
                    reason="same local topic",
                    llm_model="qwen-plus",
                )
            ],
            llm_model="qwen-plus",
        ),
    )
    monkeypatch.setattr(
        kg,
        "_extract_ckp_parent_topics_with_llm",
        lambda **kwargs: kg.CKPParentTopicAssignment(
            parent_topics=[
                kg.ExtractedCKPParentTopic(
                    local_id="parent_1",
                    title="LLM fine-tuning note",
                    description="Broader parent topic for the local fine-tuning topic.",
                    keywords=["fine-tuning"],
                    concepts=["LoRA", "validation"],
                    entities=[],
                    domains=["AI"],
                    member_child_refs=["topic_1"],
                    confidence=0.88,
                    reason="groups the local topic under the source note",
                    llm_model="qwen-plus",
                )
            ],
            llm_model="qwen-plus",
        ),
    )
    monkeypatch.setattr(kg, "search_ckp_vectors", lambda **kwargs: [])
    monkeypatch.setattr(kg, "upsert_ckp_vector", lambda ckp: f"ckp:{ckp.id}")

    result = kg.settle_personal_asset_unit_to_governance(db_session, unit)
    db_session.commit()

    assert result.pku_count == 2
    assert result.canonical_count == 2
    assert result.link_count == 3
    child_ckp = _single_topic_ckp_by_level(db_session, "child")
    parent_ckp = _single_topic_ckp_by_level(db_session, "parent")
    assert child_ckp.title == "LLM fine-tuning"
    assert child_ckp.canonical_statement != "LoRA reduces trainable parameters."
    assert parent_ckp.title == "LLM fine-tuning note"
    pku_links = db_session.query(PKUCanonicalLink).all()
    assert len(pku_links) == 2
    assert {link.relation_type for link in pku_links} == {"about"}
    assert {link.role for link in pku_links} == {"topic_member"}
    assert {link.canonical_id for link in pku_links} == {child_ckp.id}
    hierarchy = db_session.query(CanonicalRelation).one()
    assert hierarchy.source_canonical_id == child_ckp.id
    assert hierarchy.target_canonical_id == parent_ckp.id
    assert hierarchy.relation_type == "subtopic_of"


def test_asset_unit_settlement_sends_one_topic_ref_per_extracted_pku(db_session, monkeypatch):
    from backend.app.services import knowledge_governance as kg

    unit = _confirmed_personal_asset_unit(
        title="LLM fine-tuning duplicate refs",
        summary="LoRA and evaluation practices.",
        category="AI",
        tags=["fine-tuning"],
    )
    db_session.add(unit)
    db_session.flush()
    monkeypatch.setattr(
        kg,
        "_extract_asset_unit_pkus_with_llm",
        lambda unit: kg.AssetUnitPKUExtraction(
            pkus=[
                kg.ExtractedPKU(
                    local_id="pku_1",
                    statement="LoRA reduces trainable parameters.",
                    unit_type="method",
                    evidence_span="LoRA reduces trainable parameters.",
                    keywords=["LoRA", "fine-tuning"],
                    concepts=["LoRA"],
                    entities=[],
                    domains=["AI"],
                    group="fine-tuning",
                    confidence=0.91,
                    reason="method",
                    llm_model="qwen-plus",
                ),
                kg.ExtractedPKU(
                    local_id="pku_2",
                    statement="Fine-tuning evaluation should use validation data.",
                    unit_type="rule",
                    evidence_span="Evaluation should use validation data.",
                    keywords=["evaluation", "fine-tuning"],
                    concepts=["validation"],
                    entities=[],
                    domains=["AI"],
                    group="fine-tuning",
                    confidence=0.87,
                    reason="rule",
                    llm_model="qwen-plus",
                ),
            ],
            relations=[],
            llm_model="qwen-plus",
        ),
    )
    captured_refs = []

    def fake_extract_topics(**kwargs):
        captured_refs.extend(pku["ref"] for pku in kwargs["pkus"])
        return kg.CKPTopicExtraction(topics=[], llm_model="qwen-plus")

    monkeypatch.setattr(kg, "_extract_ckp_topics_with_llm", fake_extract_topics)
    monkeypatch.setattr(kg, "search_ckp_vectors", lambda **kwargs: [])
    monkeypatch.setattr(kg, "upsert_ckp_vector", lambda ckp: f"ckp:{ckp.id}")

    kg.settle_personal_asset_unit_to_governance(db_session, unit)

    assert len(captured_refs) == len(set(captured_refs)) == 2


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
    monkeypatch.setattr(
        kg,
        "_extract_ckp_parent_topics_with_llm",
        lambda **kwargs: kg.CKPParentTopicAssignment([], llm_model="qwen-plus"),
    )

    kg.settle_personal_asset_unit_to_governance(db_session, first_unit)
    db_session.flush()
    existing_ckp = _single_topic_ckp_by_level(db_session, "child")

    def fake_search_ckp_vectors(*, text, user_id, canonical_type="", top_k=8):
        return [{"ckp_id": existing_ckp.id, "score": 0.83}]

    monkeypatch.setattr(kg, "search_ckp_vectors", fake_search_ckp_vectors)

    kg.settle_personal_asset_unit_to_governance(db_session, second_unit)
    db_session.commit()

    assert db_session.query(CanonicalKnowledgePoint).count() == 2
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
    monkeypatch.setattr(
        kg,
        "_extract_ckp_parent_topics_with_llm",
        lambda **kwargs: kg.CKPParentTopicAssignment([], llm_model="qwen-plus"),
    )

    kg.settle_personal_asset_unit_to_governance(db_session, first_unit)
    db_session.flush()
    existing_ckp = _single_topic_ckp_by_level(db_session, "child")

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

    assert db_session.query(CanonicalKnowledgePoint).count() == 2
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
    monkeypatch.setattr(
        kg,
        "_extract_ckp_parent_topics_with_llm",
        lambda **kwargs: kg.CKPParentTopicAssignment([], llm_model="qwen-plus"),
    )

    kg.settle_personal_asset_unit_to_governance(db_session, first_unit)
    db_session.flush()
    existing_ckp = _single_topic_ckp_by_level(db_session, "child")
    monkeypatch.setattr(
        kg,
        "search_ckp_vectors",
        lambda **kwargs: [{"ckp_id": existing_ckp.id, "score": 0.69}],
    )

    kg.settle_personal_asset_unit_to_governance(db_session, second_unit)
    db_session.commit()

    ckps = db_session.query(CanonicalKnowledgePoint).all()
    assert len(ckps) == 3
    assert sum(1 for ckp in ckps if (ckp.extra_meta or {}).get("topic_level") == "child") == 2
    assert sum(1 for ckp in ckps if (ckp.extra_meta or {}).get("topic_level") == "parent") == 1


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


def test_find_existing_ckp_rejects_vector_hit_with_different_canonical_type(db_session, monkeypatch):
    from backend.app.models import CanonicalKnowledgePoint
    from backend.app.services import knowledge_governance as kg

    ckp = CanonicalKnowledgePoint(
        user_id="default-user",
        canonical_type="topic",
        title="Wrong type semantic candidate",
        canonical_statement="A topic candidate that must not satisfy a method lookup.",
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

    assert result is None


def test_find_existing_ckp_ignores_malformed_vector_score(db_session, monkeypatch):
    from backend.app.models import CanonicalKnowledgePoint
    from backend.app.services import knowledge_governance as kg

    ckp = CanonicalKnowledgePoint(
        user_id="default-user",
        canonical_type="method",
        title="Unrelated existing candidate",
        canonical_statement="A stored method with no lexical overlap.",
        keywords=["alpha"],
        confidence=0.9,
    )
    db_session.add(ckp)
    db_session.commit()

    monkeypatch.setattr(
        kg,
        "search_ckp_vectors",
        lambda **kwargs: [{"ckp_id": ckp.id, "score": "not-a-number"}],
    )

    result = kg._find_existing_ckp(
        db_session,
        user_id="default-user",
        statement="No lexical match text",
        keywords=["beta-only"],
        canonical_type="method",
    )

    assert result is None


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


def test_create_or_get_topic_ckp_creates_topic_hub_not_pku_copy(db_session, monkeypatch):
    from backend.app.models import PersonalKnowledgeUnit
    from backend.app.services import knowledge_governance as kg

    pku = PersonalKnowledgeUnit(
        user_id="default-user",
        source_kind="personal_asset_unit",
        source_id="unit-1",
        unit_type="method",
        statement="LoRA reduces trainable parameters with low-rank matrices.",
        normalized_statement="LoRA reduces trainable parameters with low-rank matrices.",
        normalized_statement_hash="topic-create-pku",
        keywords=["LoRA"],
        status="active",
    )
    db_session.add(pku)
    db_session.flush()
    monkeypatch.setattr(kg, "search_ckp_vectors", lambda **kwargs: [])
    monkeypatch.setattr(kg, "upsert_ckp_vector", lambda ckp: f"ckp:{ckp.id}")

    topic = kg.ExtractedCKPTopic(
        local_id="topic_1",
        title="LLM fine-tuning",
        description="Methods and rules for adapting large language models.",
        keywords=["fine-tuning", "LoRA"],
        concepts=["SFT"],
        entities=[],
        domains=["AI"],
        member_pku_refs=["pku_1"],
        confidence=0.89,
        reason="shared fine-tuning topic",
        llm_model="qwen-plus",
    )

    ckp = kg._create_or_get_topic_ckp(
        db_session,
        user_id="default-user",
        topic=topic,
        source_kind="personal_asset_unit",
        source_id="unit-1",
        source_title="Fine-tuning note",
    )

    assert ckp.canonical_type == "topic"
    assert ckp.title == "LLM fine-tuning"
    assert ckp.canonical_statement == "Methods and rules for adapting large language models."
    assert ckp.canonical_statement != pku.normalized_statement
    assert ckp.extra_meta["created_from"] == "personal_asset_unit"
    assert ckp.extra_meta["topic_reason"] == "shared fine-tuning topic"


def test_find_existing_topic_ckp_reuses_high_vector_similarity(db_session, monkeypatch):
    from backend.app.models import CanonicalKnowledgePoint
    from backend.app.services import knowledge_governance as kg

    existing = CanonicalKnowledgePoint(
        user_id="default-user",
        canonical_type="topic",
        title="Existing topic vector candidate",
        canonical_statement="A stored topic with unrelated lexical wording.",
        keywords=["alpha-only"],
        confidence=0.9,
        status="draft",
    )
    db_session.add(existing)
    db_session.commit()
    search_calls = []

    def fake_search_ckp_vectors(*, text, user_id, canonical_type="", top_k=8):
        search_calls.append(
            {
                "text": text,
                "user_id": user_id,
                "canonical_type": canonical_type,
                "top_k": top_k,
            }
        )
        return [{"ckp_id": existing.id, "score": 0.84}]

    monkeypatch.setattr(kg, "search_ckp_vectors", fake_search_ckp_vectors)

    topic = kg.ExtractedCKPTopic(
        local_id="topic_1",
        title="Large language model fine-tuning",
        description="LoRA and SFT practices.",
        keywords=["fine-tuning", "LoRA"],
        concepts=[],
        entities=[],
        domains=["AI"],
        member_pku_refs=["pku_1"],
        confidence=0.86,
        reason="same topic",
    )

    result = kg._find_existing_topic_ckp(db_session, user_id="default-user", topic=topic)

    assert result.id == existing.id
    assert search_calls
    assert search_calls[0]["canonical_type"] == "topic"


def test_find_existing_topic_ckp_ignores_malformed_vector_score(db_session, monkeypatch):
    from backend.app.models import CanonicalKnowledgePoint
    from backend.app.services import knowledge_governance as kg

    existing = CanonicalKnowledgePoint(
        user_id="default-user",
        canonical_type="topic",
        title="Malformed score topic candidate",
        canonical_statement="A stored topic with unrelated lexical wording.",
        keywords=["alpha-only"],
        confidence=0.9,
        status="draft",
    )
    db_session.add(existing)
    db_session.commit()

    monkeypatch.setattr(
        kg,
        "search_ckp_vectors",
        lambda **kwargs: [{"ckp_id": existing.id, "score": "not-a-number"}],
    )

    topic = kg.ExtractedCKPTopic(
        local_id="topic_1",
        title="Large language model fine-tuning",
        description="LoRA and SFT practices.",
        keywords=["fine-tuning", "LoRA"],
        concepts=[],
        entities=[],
        domains=["AI"],
        member_pku_refs=["pku_1"],
        confidence=0.86,
        reason="same topic",
    )

    result = kg._find_existing_topic_ckp(db_session, user_id="default-user", topic=topic)

    assert result is None


def test_create_or_get_topic_link_uses_about_relation(db_session):
    from backend.app.models import CanonicalKnowledgePoint, PKUCanonicalLink, PersonalKnowledgeUnit
    from backend.app.services import knowledge_governance as kg

    pku = PersonalKnowledgeUnit(
        user_id="default-user",
        source_kind="personal_asset_unit",
        source_id="unit-1",
        unit_type="method",
        statement="LoRA reduces trainable parameters.",
        normalized_statement="LoRA reduces trainable parameters.",
        normalized_statement_hash="topic-about-pku",
        status="active",
    )
    ckp = CanonicalKnowledgePoint(
        user_id="default-user",
        canonical_type="topic",
        title="LLM fine-tuning",
        canonical_statement="Fine-tuning topic hub.",
    )
    db_session.add_all([pku, ckp])
    db_session.flush()

    link = kg._create_or_get_generic_link(
        db_session,
        user_id="default-user",
        pku=pku,
        ckp=ckp,
        relation_type="about",
        role="topic_member",
        reason="PKU belongs to the topic.",
    )

    assert link.relation_type == "about"
    assert link.role == "topic_member"
    assert db_session.query(PKUCanonicalLink).count() == 1


def test_settle_local_pku_topics_links_members_to_fewer_topic_ckps(db_session, monkeypatch):
    from backend.app.models import CanonicalRelation, PKUCanonicalLink, PersonalKnowledgeUnit
    from backend.app.services import knowledge_governance as kg

    first = PersonalKnowledgeUnit(
        user_id="default-user",
        source_kind="personal_asset_unit",
        source_id="unit-1",
        unit_type="method",
        statement="LoRA reduces trainable parameters.",
        normalized_statement="LoRA reduces trainable parameters.",
        normalized_statement_hash="local-topic-pku-1",
        keywords=["LoRA", "fine-tuning"],
        concepts=["LoRA"],
        domains=["AI"],
        status="active",
        confidence=0.91,
    )
    second = PersonalKnowledgeUnit(
        user_id="default-user",
        source_kind="personal_asset_unit",
        source_id="unit-1",
        unit_type="rule",
        statement="Fine-tuning evaluation should use validation data.",
        normalized_statement="Fine-tuning evaluation should use validation data.",
        normalized_statement_hash="local-topic-pku-2",
        keywords=["evaluation", "fine-tuning"],
        concepts=["validation"],
        domains=["AI"],
        status="active",
        confidence=0.87,
    )
    db_session.add_all([first, second])
    db_session.flush()

    monkeypatch.setattr(kg, "search_ckp_vectors", lambda **kwargs: [])
    monkeypatch.setattr(kg, "upsert_ckp_vector", lambda ckp: f"ckp:{ckp.id}")
    monkeypatch.setattr(
        kg,
        "_extract_ckp_topics_with_llm",
        lambda **kwargs: kg.CKPTopicExtraction(
            topics=[
                kg.ExtractedCKPTopic(
                    local_id="topic_1",
                    title="LLM fine-tuning",
                    description="Methods and rules for adapting large language models.",
                    keywords=["fine-tuning"],
                    concepts=["LoRA", "validation"],
                    entities=[],
                    domains=["AI"],
                    member_pku_refs=["pku_1", "pku_2"],
                    confidence=0.9,
                    reason="same local source topic",
                    llm_model="qwen-plus",
                )
            ],
            llm_model="qwen-plus",
        ),
    )
    monkeypatch.setattr(
        kg,
        "_extract_ckp_parent_topics_with_llm",
        lambda **kwargs: kg.CKPParentTopicAssignment(
            parent_topics=[
                kg.ExtractedCKPParentTopic(
                    local_id="parent_1",
                    title="Fine-tuning note",
                    description="Broader parent topic for the source note.",
                    keywords=["fine-tuning"],
                    concepts=["LoRA", "validation"],
                    entities=[],
                    domains=["AI"],
                    member_child_refs=["topic_1"],
                    confidence=0.88,
                    reason="groups local topic under source note",
                    llm_model="qwen-plus",
                )
            ],
            llm_model="qwen-plus",
        ),
    )

    result = kg._settle_local_pku_topics(
        db_session,
        user_id="default-user",
        source_kind="personal_asset_unit",
        source_id="unit-1",
        source_title="Fine-tuning note",
        source_summary="LoRA and evaluation.",
        source_category="AI",
        source_tags=["fine-tuning"],
        pku_refs=[
            ("pku_1", first),
            ("pku_2", second),
        ],
        role="topic_member",
        reason="Local topic settlement.",
    )

    assert result == (2, 3)
    child_ckp = _single_topic_ckp_by_level(db_session, "child")
    parent_ckp = _single_topic_ckp_by_level(db_session, "parent")
    assert child_ckp.title == "LLM fine-tuning"
    assert parent_ckp.title == "Fine-tuning note"
    links = db_session.query(PKUCanonicalLink).order_by(PKUCanonicalLink.pku_id.asc()).all()
    assert len(links) == 2
    assert {link.relation_type for link in links} == {"about"}
    assert {link.canonical_id for link in links} == {child_ckp.id}
    hierarchy = db_session.query(CanonicalRelation).one()
    assert hierarchy.source_canonical_id == child_ckp.id
    assert hierarchy.target_canonical_id == parent_ckp.id
    assert hierarchy.relation_type == "subtopic_of"


def test_settle_local_pku_topics_uses_fallback_when_llm_refs_are_all_missing(db_session, monkeypatch):
    from backend.app.models import CanonicalRelation, PKUCanonicalLink, PersonalKnowledgeUnit
    from backend.app.services import knowledge_governance as kg

    first = PersonalKnowledgeUnit(
        user_id="default-user",
        source_kind="personal_asset_unit",
        source_id="unit-1",
        unit_type="method",
        statement="LoRA reduces trainable parameters.",
        normalized_statement="LoRA reduces trainable parameters.",
        normalized_statement_hash="missing-ref-topic-pku-1",
        keywords=["LoRA", "fine-tuning"],
        concepts=["LoRA"],
        domains=["AI"],
        status="active",
        confidence=0.91,
    )
    second = PersonalKnowledgeUnit(
        user_id="default-user",
        source_kind="personal_asset_unit",
        source_id="unit-1",
        unit_type="rule",
        statement="Evaluation should use validation data.",
        normalized_statement="Evaluation should use validation data.",
        normalized_statement_hash="missing-ref-topic-pku-2",
        keywords=["evaluation"],
        concepts=["validation"],
        domains=["AI"],
        status="active",
        confidence=0.87,
    )
    db_session.add_all([first, second])
    db_session.flush()

    monkeypatch.setattr(kg, "search_ckp_vectors", lambda **kwargs: [])
    monkeypatch.setattr(kg, "upsert_ckp_vector", lambda ckp: f"ckp:{ckp.id}")
    monkeypatch.setattr(
        kg,
        "_extract_ckp_topics_with_llm",
        lambda **kwargs: kg.CKPTopicExtraction(
            topics=[
                kg.ExtractedCKPTopic(
                    local_id="topic_1",
                    title="Hallucinated topic",
                    description="A topic whose PKU references are not in the local source.",
                    keywords=["hallucinated"],
                    concepts=[],
                    entities=[],
                    domains=[],
                    member_pku_refs=["missing_ref"],
                    confidence=0.7,
                    reason="references a missing PKU",
                    llm_model="qwen-plus",
                )
            ],
            llm_model="qwen-plus",
        ),
    )
    monkeypatch.setattr(
        kg,
        "_extract_ckp_parent_topics_with_llm",
        lambda **kwargs: kg.CKPParentTopicAssignment(
            parent_topics=[
                kg.ExtractedCKPParentTopic(
                    local_id="parent_1",
                    title="General: Fine-tuning note",
                    description="Broader fallback parent topic for the source note.",
                    keywords=["fine-tuning"],
                    concepts=[],
                    entities=[],
                    domains=["AI"],
                    member_child_refs=["fallback_topic"],
                    confidence=0.7,
                    reason="groups fallback local topic under source note",
                    llm_model="qwen-plus",
                )
            ],
            llm_model="qwen-plus",
        ),
    )

    result = kg._settle_local_pku_topics(
        db_session,
        user_id="default-user",
        source_kind="personal_asset_unit",
        source_id="unit-1",
        source_title="Fine-tuning note",
        source_summary="LoRA and evaluation.",
        source_category="AI",
        source_tags=["fine-tuning"],
        pku_refs=[
            ("pku_1", first),
            ("pku_2", second),
        ],
        role="topic_member",
        reason="Local topic settlement.",
    )

    assert result == (2, 3)
    child_ckp = _single_topic_ckp_by_level(db_session, "child")
    parent_ckp = _single_topic_ckp_by_level(db_session, "parent")
    assert child_ckp.title == "Fine-tuning note"
    assert child_ckp.title != "Hallucinated topic"
    assert parent_ckp.title == "General: Fine-tuning note"
    links = db_session.query(PKUCanonicalLink).order_by(PKUCanonicalLink.pku_id.asc()).all()
    assert len(links) == 2
    assert {link.relation_type for link in links} == {"about"}
    assert {link.canonical_id for link in links} == {child_ckp.id}
    hierarchy = db_session.query(CanonicalRelation).one()
    assert hierarchy.source_canonical_id == child_ckp.id
    assert hierarchy.target_canonical_id == parent_ckp.id
    assert hierarchy.relation_type == "subtopic_of"


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
