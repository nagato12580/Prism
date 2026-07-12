# prism/backend/app/prompts/asset_parse.py
"""
Prompt templates for asset parsing and knowledge synthesis.

Convention:
- UPPER_SNAKE_CASE constants for system prompts / static text
- build_*() functions for constructing dynamic user messages
- JSON_SHAPE_* constants for expected output schemas
"""
import json
from typing import Any


# ---------------------------------------------------------------------------
# Asset Parse (single raw material -> draft)
# ---------------------------------------------------------------------------

ASSET_PARSE_SYSTEM_PROMPT = "你是 Prism 的 AI 知识资产解析器。输出严格 JSON，不要 Markdown。"

ASSET_PARSE_TASK = "把用户的任意材料解析成可编辑知识资产草稿。只返回 JSON。"

ASSET_PARSE_RULES = [
    "如果来源无法确定，source confidence 要低。",
    "suggested_relations 只能基于输入内容提出候选，不要编造 target_asset_id。",
    "扩展点是值得继续研究的问题或知识点。",
]

JSON_SHAPE_ASSET_PARSE: dict[str, Any] = {
    "title": "短标题，不超过40字",
    "asset_kind": "开放字符串，例如 knowledge/opinion/resource/task/idea",
    "source": {"type": "来源类型", "platform": "来源平台", "url": "来源链接"},
    "summary": "总结用户内容的主要信息点，一两句话",
    "extracts": [{"type": "claim/knowledge/action/question/summary",
                  "content": "提取内容",
                  "confidence": 0.0}],
    "tags": ["2-6个标签"],
    "category": "主题分类",
    "rewritten_content": "由原始content整理的更适合知识库的内容",
    "suggested_relations": [
        {
            "target_asset_id": "",
            "relation_type": "similar_to/supports/contradicts/extends/mentions",
            "reason": "",
            "confidence": 0.0,
        }
    ],
    "suggested_extensions": [
        {"title": "值得拓展的知识点", "reason": "为什么值得拓展", "confidence": 0.0}
    ],
    "confidence": {
        "overall": 0.0,
        "classification": 0.0,
        "source": 0.0,
        "extraction": 0.0,
        "relation": 0.0,
        "extension": 0.0,
    },
    "rationale": "为什么这样解析",
}


def build_asset_parse_request(
    *,
    content: str,
    title: str = "",
    source_type: str = "manual",
    source_platform: str = "",
    source_url: str = "",
    max_content_length: int = 6000,
    user_preferences: str = "",
) -> str:
    """Build the user message JSON for asset parsing."""
    request = {
        "task": ASSET_PARSE_TASK,
        "source": {
            "title": title,
            "content": content[:max_content_length],
            "source_type": source_type,
            "source_platform": source_platform,
            "source_url": source_url,
        },
        "json_shape": JSON_SHAPE_ASSET_PARSE,
        "rules": ASSET_PARSE_RULES,
    }
    if user_preferences:
        request["user_preferences"] = user_preferences
    return json.dumps(request, ensure_ascii=False)


def build_asset_parse_messages(
    *,
    content: str,
    title: str = "",
    source_type: str = "manual",
    source_platform: str = "",
    source_url: str = "",
    max_content_length: int = 6000,
    user_preferences: str = "",
) -> tuple[str, str]:
    """Build the system and user messages for asset parsing."""
    return (
        ASSET_PARSE_SYSTEM_PROMPT,
        build_asset_parse_request(
            content=content,
            title=title,
            source_type=source_type,
            source_platform=source_platform,
            source_url=source_url,
            max_content_length=max_content_length,
            user_preferences=user_preferences,
        ),
    )


# ---------------------------------------------------------------------------
# Knowledge Synthesis (multiple confirmed assets -> knowledge unit draft)
# ---------------------------------------------------------------------------

KNOWLEDGE_SYNTHESIS_SYSTEM_PROMPT = "你是 Prism 的知识沉淀编辑器。输出严格 JSON，不要 Markdown 包裹。"

KNOWLEDGE_SYNTHESIS_TASK = "把一组已确认的个人知识资产汇编成一篇稳定知识库草稿。只返回 JSON。"

KNOWLEDGE_SYNTHESIS_RULES = [
    "不要把碎片逐条堆砌，应该归纳成稳定知识。",
    "不要编造资产中没有的信息。",
    "如果存在冲突观点，要在正文中标注冲突或适用边界。",
    "这是草稿，用户确认后才进入正式知识库。",
]

JSON_SHAPE_KNOWLEDGE_SYNTHESIS: dict[str, Any] = {
    "title": "知识草稿标题",
    "summary": "一句话摘要",
    "content": "Markdown 正文，结构化组织多个资产中的稳定知识",
    "category": "主题分类",
    "tags": ["标签"],
    "outline": [{"title": "章节标题", "asset_ids": ["来源资产 id"]}],
    "confidence": {"overall": 0.0, "synthesis": 0.0},
    "rationale": "为什么这样汇编",
}


def build_knowledge_synthesis_request(
    *,
    assets: list[Any],
    title: str = "",
    instruction: str = "",
    max_assets: int = 30,
    max_body_length: int = 1600,
) -> str:
    """Build the user message JSON for knowledge synthesis."""
    request = {
        "task": KNOWLEDGE_SYNTHESIS_TASK,
        "instruction": instruction,
        "preferred_title": title,
        "assets": [
            {
                "id": asset.id,
                "title": asset.title,
                "asset_kind": asset.asset_kind,
                "summary": asset.summary,
                "body": (getattr(asset, "rewritten_content", "") or asset.body or "")[:max_body_length],
                "category": asset.category,
                "tags": asset.tags or [],
                "source_platform": asset.source_platform,
            }
            for asset in assets[:max_assets]
        ],
        "json_shape": JSON_SHAPE_KNOWLEDGE_SYNTHESIS,
        "rules": KNOWLEDGE_SYNTHESIS_RULES,
    }
    return json.dumps(request, ensure_ascii=False)


def build_knowledge_synthesis_messages(
    *,
    assets: list[Any],
    title: str = "",
    instruction: str = "",
    max_assets: int = 30,
    max_body_length: int = 1600,
) -> tuple[str, str]:
    """Build the system and user messages for knowledge synthesis."""
    return (
        KNOWLEDGE_SYNTHESIS_SYSTEM_PROMPT,
        build_knowledge_synthesis_request(
            assets=assets,
            title=title,
            instruction=instruction,
            max_assets=max_assets,
            max_body_length=max_body_length,
        ),
    )


# ---------------------------------------------------------------------------
# Asset Unit PKU Extraction (confirmed personal asset unit -> atomic PKUs)
# ---------------------------------------------------------------------------

ASSET_UNIT_PKU_EXTRACTION_SYSTEM_PROMPT = "你是 Prism 的个人知识单元（PKU）抽取器。输出严格 JSON，不要 Markdown 包裹。"

ASSET_UNIT_PKU_EXTRACTION_TASK = "从已确认的个人资产单元中抽取可独立复用的原子个人知识单元，并识别单元之间的局部关系。只返回 JSON。"

ASSET_UNIT_PKU_UNIT_TYPES = [
    "concept",
    "definition",
    "claim",
    "method",
    "rule",
    "observation",
    "experiment_result",
    "decision",
    "problem",
    "question",
    "pattern",
    "constraint",
]

ASSET_UNIT_PKU_RELATION_TYPES = [
    "supports",
    "contradicts",
    "prerequisite_of",
    "derived_from",
    "refines",
    "causes",
    "enables",
    "constrains",
    "part_of",
    "same_topic",
]

ASSET_UNIT_PKU_EXTRACTION_RULES = [
    "每个 PKU 必须是一个可独立复用、语义完整的原子知识陈述。",
    "不要抽取纯标题、目录、寒暄、空泛总结或无法从正文支持的内容。",
    "unit_type 只能使用 allowed_unit_types 中的值。",
    "relation_type 只能使用 allowed_relation_types 中的值。",
    "relations 只允许引用本次输出 pkus 中的 local_id；没有明确关系时返回空数组。",
    "confidence 使用 0 到 1 的数字，表示抽取或关系判断的可信度。",
]

JSON_SHAPE_ASSET_UNIT_PKU_EXTRACTION: dict[str, Any] = {
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


def build_asset_unit_pku_extraction_request(
    *,
    unit_id: str,
    title: str,
    summary: str = "",
    content: str = "",
    source_asset_ids: list[str] | None = None,
    max_content_length: int = 6000,
) -> str:
    """Build the user message JSON for asset unit PKU extraction."""
    request = {
        "task": ASSET_UNIT_PKU_EXTRACTION_TASK,
        "source_unit": {
            "id": unit_id,
            "title": title,
            "summary": summary,
            "content": content[:max_content_length],
            "source_asset_ids": source_asset_ids or [],
        },
        "allowed_unit_types": ASSET_UNIT_PKU_UNIT_TYPES,
        "allowed_relation_types": ASSET_UNIT_PKU_RELATION_TYPES,
        "json_shape": JSON_SHAPE_ASSET_UNIT_PKU_EXTRACTION,
        "rules": ASSET_UNIT_PKU_EXTRACTION_RULES,
    }
    return json.dumps(request, ensure_ascii=False)


def build_asset_unit_pku_extraction_messages(
    *,
    unit_id: str,
    title: str,
    summary: str = "",
    content: str = "",
    source_asset_ids: list[str] | None = None,
    max_content_length: int = 6000,
) -> tuple[str, str]:
    """Build the system and user messages for asset unit PKU extraction."""
    return (
        ASSET_UNIT_PKU_EXTRACTION_SYSTEM_PROMPT,
        build_asset_unit_pku_extraction_request(
            unit_id=unit_id,
            title=title,
            summary=summary,
            content=content,
            source_asset_ids=source_asset_ids,
            max_content_length=max_content_length,
        ),
    )


# ---------------------------------------------------------------------------
# Document Chunk PKU Extraction (anchor parent chunk -> atomic PKUs)
# ---------------------------------------------------------------------------

DOCUMENT_CHUNK_PKU_EXTRACTION_SYSTEM_PROMPT = (
    "你是 Prism 的文档个人知识单元（PKU）抽取器。"
    "只返回严格 JSON，不要输出 Markdown。"
    "JSON key 和枚举值保持英文；statement、normalized_statement、reason、keywords、domains、entities、concepts 等自然语言字段默认使用中文。"
)

DOCUMENT_CHUNK_PKU_EXTRACTION_TASK = (
    "从 anchor document chunk 中抽取可复用的原子 PKU。"
    "previous 和 next chunk 只能用于理解术语、指代和上下文，不得作为证据来源。"
)

DOCUMENT_CHUNK_PKU_EXTRACTION_RULES = [
    "每个 PKU 必须是原子化、可复用、语义完整，并且能被 anchor chunk 支持的知识陈述。",
    "自然语言字段默认用中文表达；如果包含专有名词、模型名、算法名、代码/API 名称，可以保留原文术语。",
    "JSON key 保持英文；unit_type 必须使用 allowed_unit_types 中的英文枚举值。",
    "relation_type 必须使用 allowed_relation_types 中的英文枚举值。",
    "evidence 字段必须摘录或紧密贴合 anchor chunk 的原文证据，不翻译、不改写、不从 context chunk 中取证。",
    "previous 和 next chunk 只能作为语义上下文；不要创建证据只存在于上下文 chunk 的 PKU。",
    "不要把纯标题、目录、空泛摘要或没有证据支持的推断抽取为 PKU。",
    "relations 只能引用本次响应中的 local_id；没有明确关系时返回空数组。",
    "当 anchor chunk 没有可复用知识时，返回空 pkus 数组。",
]

JSON_SHAPE_DOCUMENT_CHUNK_PKU_EXTRACTION: dict[str, Any] = {
    "pkus": [
        {
            "local_id": "pku_1",
            "statement": "用中文表达的原子知识陈述",
            "normalized_statement": "用中文表达的规范化知识陈述",
            "unit_type": ASSET_UNIT_PKU_UNIT_TYPES,
            "keywords": ["中文关键词"],
            "domains": ["中文领域"],
            "entities": ["中文实体或保留原文专名"],
            "concepts": ["中文概念或保留原文术语"],
            "confidence": 0.0,
            "evidence": "来自 anchor chunk 的原文证据摘录，不翻译",
            "reason": "用中文简述抽取依据",
        }
    ],
    "relations": [
        {
            "source_local_id": "pku_1",
            "target_local_id": "pku_2",
            "relation_type": ASSET_UNIT_PKU_RELATION_TYPES,
            "reason": "用中文简述关系判断依据",
            "confidence": 0.0,
        }
    ],
}


def _chunk_payload(chunk: dict[str, Any] | None, max_text_length: int) -> dict[str, Any] | None:
    if not chunk:
        return None
    return {
        "id": str(chunk.get("id") or ""),
        "index": chunk.get("index"),
        "text": str(chunk.get("text") or "")[:max_text_length],
    }


def build_document_chunk_pku_extraction_request(
    *,
    item_id: str,
    title: str,
    summary: str = "",
    category: str = "",
    tags: list[str] | None = None,
    source_type: str = "",
    anchor_chunk: dict[str, Any],
    previous_chunk: dict[str, Any] | None = None,
    next_chunk: dict[str, Any] | None = None,
    max_anchor_length: int = 6000,
    max_context_length: int = 2500,
) -> str:
    """Build the user message JSON for document chunk PKU extraction."""
    request = {
        "task": DOCUMENT_CHUNK_PKU_EXTRACTION_TASK,
        "source_item": {
            "id": item_id,
            "title": title,
            "summary": summary,
            "category": category,
            "tags": tags or [],
            "source_type": source_type,
        },
        "anchor_chunk": _chunk_payload(anchor_chunk, max_anchor_length),
        "context_chunks": {
            "previous": _chunk_payload(previous_chunk, max_context_length),
            "next": _chunk_payload(next_chunk, max_context_length),
        },
        "allowed_unit_types": ASSET_UNIT_PKU_UNIT_TYPES,
        "allowed_relation_types": ASSET_UNIT_PKU_RELATION_TYPES,
        "json_shape": JSON_SHAPE_DOCUMENT_CHUNK_PKU_EXTRACTION,
        "rules": DOCUMENT_CHUNK_PKU_EXTRACTION_RULES,
    }
    return json.dumps(request, ensure_ascii=False)


def build_document_chunk_pku_extraction_messages(
    *,
    item_id: str,
    title: str,
    summary: str = "",
    category: str = "",
    tags: list[str] | None = None,
    source_type: str = "",
    anchor_chunk: dict[str, Any],
    previous_chunk: dict[str, Any] | None = None,
    next_chunk: dict[str, Any] | None = None,
    max_anchor_length: int = 6000,
    max_context_length: int = 2500,
) -> tuple[str, str]:
    """Build the system and user messages for document chunk PKU extraction."""
    return (
        DOCUMENT_CHUNK_PKU_EXTRACTION_SYSTEM_PROMPT,
        build_document_chunk_pku_extraction_request(
            item_id=item_id,
            title=title,
            summary=summary,
            category=category,
            tags=tags,
            source_type=source_type,
            anchor_chunk=anchor_chunk,
            previous_chunk=previous_chunk,
            next_chunk=next_chunk,
            max_anchor_length=max_anchor_length,
            max_context_length=max_context_length,
        ),
    )


# ---------------------------------------------------------------------------
# CKP Topic Extraction (local PKUs -> reusable topic hubs)
# ---------------------------------------------------------------------------

CKP_TOPIC_EXTRACTION_SYSTEM_PROMPT = (
    "你是 Prism 的 CKP 子主题构建器。"
    "只返回严格 JSON，不要输出 Markdown。"
    "JSON key、结构字段和枚举/标识保持英文；title、description、reason、keywords、concepts、domains、entities 等自然语言字段默认使用中文。"
)

CKP_TOPIC_EXTRACTION_TASK = (
    "把同一批本地 PKU 归组为简洁、可复用的 CKP 子主题。"
    "CKP 是主题节点，不是某一条 PKU 的改写。"
)

CKP_TOPIC_EXTRACTION_RULES = [
    "每个子主题使用简洁的中文名词短语作为 title；可保留必要英文术语、模型名或算法名。",
    "自然语言字段默认用中文表达；JSON key、local_id、member_pku_refs 等结构字段保持英文格式。",
    "优先生成少量有意义的主题，不要生成大量过窄、重复或只复述单条 PKU 的主题。",
    "每个主题必须引用至少一个本地 PKU。",
    "不要引用未知的 PKU ref。",
    "可使用 source metadata 辅助命名和分组，但不要编造 PKU 没有支持的主题。",
    "没有可用 PKU 时返回空 topics 数组。",
]

JSON_SHAPE_CKP_TOPIC_EXTRACTION: dict[str, Any] = {
    "topics": [
        {
            "local_id": "topic_1",
            "title": "用中文表达的主题名词短语",
            "description": "用中文表达的主题说明",
            "keywords": ["中文关键词"],
            "concepts": ["中文概念或保留原文术语"],
            "domains": ["中文领域"],
            "entities": ["中文实体或保留原文专名"],
            "member_pku_refs": ["pku_1", "pku_2"],
            "confidence": 0.0,
            "reason": "用中文简述分组依据",
        }
    ],
}


def _topic_pku_payload(pku: dict[str, Any], max_statement_length: int) -> dict[str, Any]:
    return {
        "ref": str(pku.get("ref") or ""),
        "statement": str(pku.get("statement") or "")[:max_statement_length],
        "unit_type": str(pku.get("unit_type") or ""),
        "keywords": pku.get("keywords") or [],
        "concepts": pku.get("concepts") or [],
        "entities": pku.get("entities") or [],
        "domains": pku.get("domains") or [],
        "evidence_span": str(pku.get("evidence_span") or ""),
    }


def build_ckp_topic_extraction_request(
    *,
    source_kind: str,
    source_id: str,
    title: str = "",
    summary: str = "",
    category: str = "",
    tags: list[str] | None = None,
    pkus: list[dict[str, Any]],
    max_pkus: int = 80,
    max_statement_length: int = 700,
) -> str:
    """Build the user message JSON for CKP topic extraction."""
    request = {
        "task": CKP_TOPIC_EXTRACTION_TASK,
        "source": {
            "kind": source_kind,
            "id": source_id,
            "title": title,
            "summary": summary,
            "category": category,
            "tags": tags or [],
        },
        "pkus": [_topic_pku_payload(pku, max_statement_length) for pku in pkus[:max_pkus]],
        "json_shape": JSON_SHAPE_CKP_TOPIC_EXTRACTION,
        "rules": CKP_TOPIC_EXTRACTION_RULES,
    }
    return json.dumps(request, ensure_ascii=False)


def build_ckp_topic_extraction_messages(
    *,
    source_kind: str,
    source_id: str,
    title: str = "",
    summary: str = "",
    category: str = "",
    tags: list[str] | None = None,
    pkus: list[dict[str, Any]],
    max_pkus: int = 80,
    max_statement_length: int = 700,
) -> tuple[str, str]:
    """Build the system and user messages for CKP topic extraction."""
    return (
        CKP_TOPIC_EXTRACTION_SYSTEM_PROMPT,
        build_ckp_topic_extraction_request(
            source_kind=source_kind,
            source_id=source_id,
            title=title,
            summary=summary,
            category=category,
            tags=tags,
            pkus=pkus,
            max_pkus=max_pkus,
            max_statement_length=max_statement_length,
        ),
    )


# ---------------------------------------------------------------------------
# CKP Parent Topic Assignment (local child topics -> broader parent topics)
# ---------------------------------------------------------------------------

CKP_PARENT_TOPIC_ASSIGNMENT_SYSTEM_PROMPT = (
    "你是 Prism 的 CKP 上层主题分配器。"
    "只返回严格 JSON，不要输出 Markdown。"
    "JSON key、结构字段和枚举/标识保持英文；title、description、reason、keywords、concepts、domains、entities 等自然语言字段默认使用中文。"
)

CKP_PARENT_TOPIC_ASSIGNMENT_TASK = (
    "把本地子 CKP 主题归入更上层但仍然具体的父 CKP 主题。"
    "父主题应能跨多个子主题复用，但不能变成空泛分类。"
)

CKP_PARENT_TOPIC_ASSIGNMENT_RULES = [
    "每个父主题使用较宽但具体的中文名词短语作为 title；可保留必要英文术语、模型名或算法名。",
    "自然语言字段默认用中文表达；JSON key、local_id、member_child_refs 等结构字段保持英文格式。",
    "优先生成少量有意义的父主题，不要生成大量过窄、重复或空泛的父主题。",
    "每个父主题必须引用至少一个本地子主题。",
    "不要引用未知的 child topic ref。",
    "可使用 source metadata 和子主题成员 PKU 作为分组上下文，但不要编造没有证据支撑的父主题。",
    "没有可用子主题时返回空 parent_topics 数组。",
]

JSON_SHAPE_CKP_PARENT_TOPIC_ASSIGNMENT: dict[str, Any] = {
    "parent_topics": [
        {
            "local_id": "parent_1",
            "title": "用中文表达的上层主题名词短语",
            "description": "用中文表达的上层主题说明",
            "keywords": ["中文关键词"],
            "concepts": ["中文概念或保留原文术语"],
            "domains": ["中文领域"],
            "entities": ["中文实体或保留原文专名"],
            "member_child_refs": ["child_1", "child_2"],
            "confidence": 0.0,
            "reason": "用中文简述上层主题分组依据",
        }
    ],
}


def _parent_child_topic_payload(topic: dict[str, Any], max_statement_length: int) -> dict[str, Any]:
    return {
        "ref": str(topic.get("ref") or ""),
        "title": str(topic.get("title") or ""),
        "description": str(topic.get("description") or ""),
        "keywords": topic.get("keywords") or [],
        "concepts": topic.get("concepts") or [],
        "entities": topic.get("entities") or [],
        "domains": topic.get("domains") or [],
        "member_pku_statements": [
            str(statement or "")[:max_statement_length]
            for statement in (topic.get("member_pku_statements") or [])
        ],
    }


def build_ckp_parent_topic_assignment_request(
    *,
    source_kind: str,
    source_id: str,
    title: str = "",
    summary: str = "",
    category: str = "",
    tags: list[str] | None = None,
    child_topics: list[dict[str, Any]],
    max_child_topics: int = 80,
    max_statement_length: int = 500,
) -> str:
    """Build the user message JSON for CKP parent topic assignment."""
    request = {
        "task": CKP_PARENT_TOPIC_ASSIGNMENT_TASK,
        "source": {
            "kind": source_kind,
            "id": source_id,
            "title": title,
            "summary": summary,
            "category": category,
            "tags": tags or [],
        },
        "child_topics": [
            _parent_child_topic_payload(topic, max_statement_length)
            for topic in child_topics[:max_child_topics]
        ],
        "json_shape": JSON_SHAPE_CKP_PARENT_TOPIC_ASSIGNMENT,
        "rules": CKP_PARENT_TOPIC_ASSIGNMENT_RULES,
    }
    return json.dumps(request, ensure_ascii=False)


def build_ckp_parent_topic_assignment_messages(
    *,
    source_kind: str,
    source_id: str,
    title: str = "",
    summary: str = "",
    category: str = "",
    tags: list[str] | None = None,
    child_topics: list[dict[str, Any]],
    max_child_topics: int = 80,
    max_statement_length: int = 500,
) -> tuple[str, str]:
    """Build the system and user messages for CKP parent topic assignment."""
    return (
        CKP_PARENT_TOPIC_ASSIGNMENT_SYSTEM_PROMPT,
        build_ckp_parent_topic_assignment_request(
            source_kind=source_kind,
            source_id=source_id,
            title=title,
            summary=summary,
            category=category,
            tags=tags,
            child_topics=child_topics,
            max_child_topics=max_child_topics,
            max_statement_length=max_statement_length,
        ),
    )
