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
    return json.dumps(request, ensure_ascii=False)


def build_asset_parse_messages(
    *,
    content: str,
    title: str = "",
    source_type: str = "manual",
    source_platform: str = "",
    source_url: str = "",
    max_content_length: int = 6000,
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
                "body": (asset.rewritten_content or asset.body or "")[:max_body_length],
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
    "You are Prism's document knowledge unit (PKU) extractor. "
    "Return strict JSON only. Do not output Markdown."
)

DOCUMENT_CHUNK_PKU_EXTRACTION_TASK = (
    "Extract reusable atomic PKUs from the anchor document chunk. "
    "Use neighboring chunks only as context for resolving terms and references."
)

DOCUMENT_CHUNK_PKU_EXTRACTION_RULES = [
    "Every PKU must be atomic, reusable, semantically complete, and supported by the anchor chunk.",
    "Use previous and next chunks only as context; do not create a PKU whose evidence exists only in a context chunk.",
    "The evidence field must quote or closely match text from the anchor chunk.",
    "Do not extract headings, vague summaries, or unsupported conclusions as PKUs.",
    "unit_type must use one value from allowed_unit_types.",
    "relation_type must use one value from allowed_relation_types.",
    "relations may only reference local_id values from this response.",
    "Return an empty pkus array when the anchor chunk contains no reusable knowledge.",
]

JSON_SHAPE_DOCUMENT_CHUNK_PKU_EXTRACTION: dict[str, Any] = {
    "pkus": [
        {
            "local_id": "pku_1",
            "statement": "Atomic knowledge statement supported by the anchor chunk",
            "normalized_statement": "Optional normalized statement",
            "unit_type": ASSET_UNIT_PKU_UNIT_TYPES,
            "keywords": ["keyword"],
            "domains": ["domain"],
            "entities": ["entity"],
            "concepts": ["concept"],
            "confidence": 0.0,
            "evidence": "Evidence span from the anchor chunk",
            "reason": "Short extraction reason",
        }
    ],
    "relations": [
        {
            "source_local_id": "pku_1",
            "target_local_id": "pku_2",
            "relation_type": ASSET_UNIT_PKU_RELATION_TYPES,
            "reason": "Short relation reason",
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
