# prism/backend/app/services/knowledge_governance.py
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

import httpx
from openai import OpenAI
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.models.asset import PersonalAssetItem, PersonalAssetUnit
from backend.app.models.knowledge_governance import (
    CanonicalKnowledgePoint,
    PKUCanonicalLink,
    PKURelation,
    PersonalKnowledgeUnit,
)
from backend.app.models.knowledge_item import KnowledgeChunk, KnowledgeItem
from backend.app.prompts.asset_parse import (
    build_asset_unit_pku_extraction_messages,
    build_document_chunk_pku_extraction_messages,
)
from backend.app.services.ckp_vectors import search_ckp_vectors, upsert_ckp_vector


DEFAULT_USER_ID = "default-user"
PKU_UNIT_TYPES = {
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
}
PKU_RELATION_TYPES = {
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
}


@dataclass(frozen=True)
class GovernanceResult:
    pku_count: int
    canonical_count: int
    link_count: int
    pku_relation_count: int = 0


@dataclass(frozen=True)
class PKUTypeDecision:
    unit_type: str
    confidence: float
    reason: str = ""
    llm_model: str = ""


@dataclass(frozen=True)
class ExtractedPKU:
    statement: str
    unit_type: str
    evidence_span: str
    keywords: list[str]
    concepts: list[str]
    entities: list[str]
    domains: list[str]
    group: str
    confidence: float
    reason: str
    llm_model: str = ""
    local_id: str = ""


@dataclass(frozen=True)
class ExtractedPKURelation:
    from_ref: str
    to_ref: str
    relation_type: str
    confidence: float
    reason: str


@dataclass(frozen=True)
class AssetUnitPKUExtraction:
    pkus: list[ExtractedPKU]
    relations: list[ExtractedPKURelation]
    llm_model: str = ""


@dataclass(frozen=True)
class CKPSemanticMatchDecision:
    same: bool
    confidence: float
    reason: str = ""
    llm_model: str = ""


def _text_hash(text: str) -> str:
    return hashlib.sha256((text or "").strip().lower().encode("utf-8")).hexdigest()


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _short_title(text: str, fallback: str = "未命名知识点") -> str:
    text = _normalize_space(text)
    if not text:
        return fallback
    return text[:48] + ("..." if len(text) > 48 else "")


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _clamp_confidence(value: Any, default: float = 0.5) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = default
    return max(0.0, min(confidence, 1.0))


def _clean_string_list(value: Any, limit: int = 16) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    for item in value:
        text = _normalize_space(str(item or ""))
        if text and text not in cleaned:
            cleaned.append(text[:80])
        if len(cleaned) >= limit:
            break
    return cleaned


def _first_text(*values: Any) -> str:
    for value in values:
        text = _normalize_space(str(value or ""))
        if text:
            return text
    return ""


def _pku_type_from_llm_value(value: Any) -> str:
    unit_type = str(value or "").strip().lower()
    aliases = {
        "technique": "method",
        "source": "concept",
        "artifact": "concept",
        "fact": "claim",
        "issue": "problem",
        "概念": "concept",
        "定义": "definition",
        "观点": "claim",
        "方法": "method",
        "规则": "rule",
        "观察": "observation",
        "实验结果": "experiment_result",
        "决策": "decision",
        "问题": "problem",
        "疑问": "question",
        "经验模式": "pattern",
        "约束关系": "constraint",
    }
    unit_type = aliases.get(unit_type, unit_type)
    return unit_type if unit_type in PKU_UNIT_TYPES else ""


def _statement_from_extracted_item(item: dict[str, Any]) -> str:
    statement = _first_text(
        item.get("statement"),
        item.get("normalized_statement"),
        item.get("description"),
        item.get("content"),
        item.get("text"),
    )
    name = _first_text(item.get("name"), item.get("title"))
    if name and statement and not statement.startswith(name):
        return f"{name}：{statement}"
    return statement or name


def _extract_keywords(*parts: Any) -> list[str]:
    words: list[str] = []
    for part in parts:
        if part is None:
            continue
        if isinstance(part, list):
            values = [str(item) for item in part]
        else:
            values = [str(part)]
        for value in values:
            for raw in re.findall(r"[A-Za-z0-9_+#.-]+|[\u4e00-\u9fff]{2,}", value):
                word = raw.strip().strip("#").lower()
                if len(word) < 2 or word in words:
                    continue
                words.append(word[:48])
                if len(words) >= 24:
                    return words
    return words


def _unit_type_from_extract(kind: str, asset_kind: str) -> str:
    normalized = (kind or asset_kind or "").lower()
    if normalized in {"question", "problem"}:
        return "question"
    if normalized in {"action", "todo", "task"}:
        return "decision"
    if normalized in {"knowledge", "definition"}:
        return "definition"
    if normalized in {"method", "rule", "pattern", "claim", "observation", "experiment_result"}:
        return normalized
    if normalized in {"opinion", "idea", "resource"}:
        return "claim"
    return "claim"


def _modality_from_asset(asset: PersonalAssetItem, unit_type: str) -> str:
    kind = (asset.asset_kind or "").lower()
    if unit_type == "question":
        return "question"
    if unit_type == "decision":
        return "decision"
    if unit_type in {"observation", "experiment_result"}:
        return "observation"
    if kind in {"opinion", "idea"}:
        return "opinion"
    if kind in {"resource", "knowledge"}:
        return "fact"
    return "unknown"


def _role_from_asset(asset: PersonalAssetItem, unit_type: str) -> str:
    kind = (asset.asset_kind or "").lower()
    if unit_type == "question":
        return "question_source"
    if unit_type in {"observation", "experiment_result"}:
        return "experiment_evidence"
    if kind in {"opinion", "idea"}:
        return "personal_claim"
    return "personal_observation"


def _unit_type_from_unit_text(text: str) -> str:
    lowered = (text or "").lower()
    if any(word in lowered for word in ["constraint", "limit", "限制", "约束", "边界", "前提"]):
        return "constraint"
    if any(word in lowered for word in ["problem", "issue", "bug", "风险", "问题", "异常", "阻塞"]):
        return "problem"
    if any(word in lowered for word in ["pattern", "best practice", "经验", "模式", "套路"]):
        return "pattern"
    if any(word in lowered for word in ["defined as", "refers to", "定义", "是指"]):
        return "definition"
    if any(word in lowered for word in ["method", "approach", "strategy", "方法", "流程", "步骤"]):
        return "method"
    if any(word in lowered for word in ["must", "should", "rule", "必须", "应该", "规则"]):
        return "rule"
    return "claim"


def _unit_type_from_document_text(text: str) -> str:
    lowered = (text or "").lower()
    if any(word in lowered for word in ["定义", "是指", "refers to", "defined as"]):
        return "definition"
    if any(word in lowered for word in ["方法", "步骤", "流程", "strategy", "method", "approach"]):
        return "method"
    if any(word in lowered for word in ["必须", "应该", "规则", "must", "should", "rule"]):
        return "rule"
    return "claim"


def _fallback_pku_type_decision(unit_type: str) -> PKUTypeDecision:
    return PKUTypeDecision(unit_type=unit_type if unit_type in PKU_UNIT_TYPES else "claim", confidence=0.0)


def _parse_json_object(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    data = json.loads(text)
    return data if isinstance(data, dict) else {}


def _parse_asset_unit_pku_extraction(data: dict[str, Any], llm_model: str = "") -> AssetUnitPKUExtraction:
    parsed_pkus: list[ExtractedPKU] = []
    raw_pkus = _as_list(data.get("pkus")) or _as_list(data.get("concepts"))
    for item in raw_pkus:
        if not isinstance(item, dict):
            continue
        statement = _statement_from_extracted_item(item)
        unit_type = _pku_type_from_llm_value(item.get("unit_type") or item.get("type") or item.get("category_type"))
        evidence_span = _first_text(item.get("evidence_span"), item.get("evidence"), item.get("evidence_text"))
        if not statement or unit_type not in PKU_UNIT_TYPES:
            continue
        aliases = _clean_string_list(item.get("aliases"))
        concepts = _clean_string_list(item.get("concepts")) or aliases
        domains = _clean_string_list(item.get("domains")) or _clean_string_list([item.get("category")])
        keywords = _clean_string_list(item.get("keywords")) or _clean_string_list(item.get("tags"))
        parsed_pkus.append(
            ExtractedPKU(
                statement=statement[:1200],
                unit_type=unit_type,
                evidence_span=(evidence_span or statement)[:1200],
                keywords=keywords,
                concepts=concepts,
                entities=_clean_string_list(item.get("entities")),
                domains=domains,
                group=_normalize_space(str(item.get("group") or ""))[:120],
                confidence=_clamp_confidence(item.get("confidence"), 0.72),
                reason=_normalize_space(str(item.get("reason") or ""))[:500],
                llm_model=llm_model,
                local_id=_first_text(item.get("local_id"), item.get("id"), item.get("name"), item.get("title"))[:120],
            )
        )

    parsed_relations: list[ExtractedPKURelation] = []
    for item in _as_list(data.get("relations")):
        if not isinstance(item, dict):
            continue
        from_ref = _normalize_space(str(item.get("source_local_id") or item.get("from") or ""))
        to_ref = _normalize_space(str(item.get("target_local_id") or item.get("to") or ""))
        relation_type = str(item.get("relation_type") or item.get("type") or "").strip().lower()
        if not from_ref or not to_ref or relation_type not in PKU_RELATION_TYPES:
            continue
        parsed_relations.append(
            ExtractedPKURelation(
                from_ref=from_ref[:1200],
                to_ref=to_ref[:1200],
                relation_type=relation_type,
                confidence=_clamp_confidence(item.get("confidence"), 0.6),
                reason=_normalize_space(str(item.get("reason") or ""))[:500],
            )
        )

    return AssetUnitPKUExtraction(parsed_pkus, parsed_relations, llm_model=llm_model)


def _extract_asset_unit_pkus_with_llm(unit: PersonalAssetUnit) -> AssetUnitPKUExtraction:
    if not settings.LLM_API_BASE or not settings.LLM_API_KEY:
        return AssetUnitPKUExtraction([], [], llm_model="")

    system_prompt, user_message = build_asset_unit_pku_extraction_messages(
        unit_id=unit.id,
        title=unit.title or "",
        summary=unit.summary or "",
        content=unit.content or "",
        source_asset_ids=unit.source_asset_ids or [],
    )
    try:
        client = OpenAI(base_url=settings.LLM_API_BASE, api_key=settings.LLM_API_KEY)
        response = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or "{}"
        data = _parse_json_object(content)
        return _parse_asset_unit_pku_extraction(data, llm_model=settings.LLM_MODEL)
    except Exception:
        return AssetUnitPKUExtraction([], [], llm_model="")


def _document_chunk_prompt_payload(chunk: KnowledgeChunk | None, index: int | None = None) -> dict[str, Any] | None:
    if not chunk:
        return None
    return {
        "id": chunk.id,
        "index": index,
        "text": chunk.chunk_text or "",
    }


def _extract_document_chunk_pkus_with_llm(
    item: KnowledgeItem,
    anchor_chunk: KnowledgeChunk,
    previous_chunk: KnowledgeChunk | None = None,
    next_chunk: KnowledgeChunk | None = None,
    *,
    anchor_index: int | None = None,
) -> AssetUnitPKUExtraction:
    if not settings.LLM_API_BASE or not settings.LLM_API_KEY:
        return AssetUnitPKUExtraction([], [], llm_model="")

    system_prompt, user_message = build_document_chunk_pku_extraction_messages(
        item_id=item.id,
        title=item.title or "",
        summary=item.summary or "",
        category=item.category or "",
        tags=item.tags or [],
        source_type=item.source_type or "",
        anchor_chunk=_document_chunk_prompt_payload(anchor_chunk, anchor_index)
        or {"id": anchor_chunk.id, "text": ""},
        previous_chunk=_document_chunk_prompt_payload(previous_chunk, None),
        next_chunk=_document_chunk_prompt_payload(next_chunk, None),
    )
    try:
        client = OpenAI(base_url=settings.LLM_API_BASE, api_key=settings.LLM_API_KEY)
        response = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or "{}"
        data = _parse_json_object(content)
        return _parse_asset_unit_pku_extraction(data, llm_model=settings.LLM_MODEL)
    except Exception:
        return AssetUnitPKUExtraction([], [], llm_model="")


def _ollama_pku_type_decision(
    *,
    text: str,
    fallback: str,
    title: str = "",
    category: str = "",
    tags: list[str] | None = None,
) -> PKUTypeDecision:
    if not settings.PKU_TYPE_USE_OLLAMA:
        return _fallback_pku_type_decision(fallback)
    text = _normalize_space(text)
    if not text:
        return _fallback_pku_type_decision(fallback)

    prompt = {
        "task": "Classify a personal knowledge unit into exactly one unit_type. Return strict JSON only.",
        "priority_rules": [
            "If the text describes steps, workflow, process, approach, strategy, procedure, or how to do something, choose method.",
            "If the text explains what a term/concept/entity means, choose definition.",
            "If the text states a must/should constraint, policy, principle, or requirement, choose rule.",
            "If the text records a concrete measurement, event, test result, or personal experience, choose observation or experiment_result.",
            "If none of the above clearly applies, choose claim.",
        ],
        "allowed_unit_types": {
            "definition": "Defines a concept, term, entity, or meaning.",
            "method": "Describes a method, process, workflow, strategy, or steps.",
            "rule": "States a rule, constraint, principle, requirement, or should/must guidance.",
            "claim": "States a fact-like assertion, opinion, conclusion, or general proposition.",
            "question": "Asks an open question or unresolved problem.",
            "decision": "Records a choice, action decision, task, or commitment.",
            "observation": "Records an empirical observation, event, measurement, or experience.",
            "experiment_result": "Reports an experiment/test result or measured outcome.",
        },
        "examples": [
            {"text": "这个流程分为三步：先解析文档，再抽取知识单元，最后写入图谱。", "unit_type": "method"},
            {"text": "PKU 是从来源材料中抽取出的最小知识证据单元。", "unit_type": "definition"},
            {"text": "确认后的碎片知识必须先进入 personal_asset_unit。", "unit_type": "rule"},
            {"text": "用户观察到开窗通风后天气经常转好。", "unit_type": "observation"},
        ],
        "context": {
            "title": title[:300],
            "category": category[:120],
            "tags": tags or [],
        },
        "text": text[:1800],
        "output_shape": {"unit_type": "one allowed value", "confidence": "0.0-1.0", "reason": "short reason"},
    }
    try:
        resp = httpx.post(
            f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/generate",
            json={
                "model": settings.PKU_TYPE_MODEL,
                "prompt": json.dumps(prompt, ensure_ascii=False),
                "format": "json",
                "stream": False,
                "options": {"temperature": 0},
            },
            timeout=settings.PKU_TYPE_TIMEOUT,
        )
        resp.raise_for_status()
        payload = resp.json()
        data = _parse_json_object(str(payload.get("response") or ""))
        unit_type = str(data.get("unit_type") or "").strip().lower()
        confidence = float(data.get("confidence") or 0.0)
        if unit_type not in PKU_UNIT_TYPES:
            return _fallback_pku_type_decision(fallback)
        return PKUTypeDecision(
            unit_type=unit_type,
            confidence=max(0.0, min(confidence, 1.0)),
            reason=str(data.get("reason") or "")[:500],
            llm_model=settings.PKU_TYPE_MODEL,
        )
    except Exception:
        return _fallback_pku_type_decision(fallback)


def _llm_ckp_same_as_decision(
    statement: str,
    candidate: CanonicalKnowledgePoint,
    score: float,
) -> CKPSemanticMatchDecision:
    if not settings.LLM_API_BASE or not settings.LLM_API_KEY:
        return CKPSemanticMatchDecision(same=False, confidence=0.0)
    request = {
        "task": "判断 new_pku_statement 和 candidate_ckp 是否表达同一个稳定知识点。只返回 JSON。",
        "rules": [
            "same=true 只在两者可以归并为同一个 CanonicalKnowledgePoint 时使用。",
            "如果只是同一主题、上下位关系、前后步骤、相似但事实不同，返回 same=false。",
            "不要因为关键词相同就合并；必须语义等价或近似等价。",
        ],
        "vector_similarity": score,
        "new_pku_statement": statement,
        "candidate_ckp": {
            "id": candidate.id,
            "title": candidate.title,
            "canonical_type": candidate.canonical_type,
            "canonical_statement": candidate.canonical_statement,
            "summary": candidate.summary,
            "keywords": candidate.keywords or [],
        },
        "output_shape": {"same": True, "confidence": 0.0, "reason": "short reason"},
    }
    try:
        client = OpenAI(base_url=settings.LLM_API_BASE, api_key=settings.LLM_API_KEY)
        response = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": "你是 Prism 的 CKP 语义归并判定器。输出严格 JSON，不要 Markdown。"},
                {"role": "user", "content": json.dumps(request, ensure_ascii=False)},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        data = _parse_json_object(response.choices[0].message.content or "{}")
        return CKPSemanticMatchDecision(
            same=bool(data.get("same")),
            confidence=_clamp_confidence(data.get("confidence"), 0.0),
            reason=str(data.get("reason") or "")[:500],
            llm_model=settings.LLM_MODEL,
        )
    except Exception:
        return CKPSemanticMatchDecision(same=False, confidence=0.0)


def _candidate_statements_from_asset(asset: PersonalAssetItem) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for entry in _as_list(asset.extracts):
        if not isinstance(entry, dict):
            continue
        content = _normalize_space(str(entry.get("content") or ""))
        if not content:
            continue
        candidates.append(
            {
                "statement": content,
                "unit_type": _unit_type_from_extract(str(entry.get("type") or ""), asset.asset_kind),
                "confidence": float(entry.get("confidence") or (asset.confidence or {}).get("extraction", 0.6) or 0.6),
            }
        )

    fallback = _normalize_space(asset.summary or asset.body or asset.raw_text)
    if fallback:
        candidates.append(
            {
                "statement": fallback[:1200],
                "unit_type": _unit_type_from_extract("", asset.asset_kind),
                "confidence": float((asset.confidence or {}).get("overall", 0.55) or 0.55),
            }
        )

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = _text_hash(candidate["statement"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
        if len(deduped) >= 3:
            break
    return deduped


def _find_existing_ckp(
    db: Session,
    *,
    user_id: str,
    statement: str,
    keywords: list[str],
    canonical_type: str = "",
) -> CanonicalKnowledgePoint | None:
    normalized = _normalize_space(statement)
    if not normalized:
        return None
    like_title = f"%{_short_title(normalized, '')[:24]}%"
    query = db.query(CanonicalKnowledgePoint).filter(CanonicalKnowledgePoint.user_id == user_id)
    if canonical_type:
        query = query.filter(CanonicalKnowledgePoint.canonical_type == canonical_type)
    candidates = query.filter(
        or_(
            CanonicalKnowledgePoint.title.like(like_title),
            CanonicalKnowledgePoint.canonical_statement.like(f"%{normalized[:80]}%"),
        )
    ).limit(10).all()

    if not candidates and keywords:
        first_keywords = [word for word in keywords[:5] if len(word) >= 2]
        if first_keywords:
            candidates = query.filter(
                or_(*(CanonicalKnowledgePoint.canonical_statement.like(f"%{word}%") for word in first_keywords))
            ).limit(10).all()

    statement_words = set(keywords)
    best: CanonicalKnowledgePoint | None = None
    best_score = 0
    for candidate in candidates:
        candidate_words = set(_as_list(candidate.keywords))
        overlap = len(statement_words & candidate_words)
        exactish = normalized == _normalize_space(candidate.canonical_statement)
        score = overlap + (10 if exactish else 0)
        if score > best_score:
            best = candidate
            best_score = score
    if best and best_score >= 2:
        return best

    try:
        vector_hits = search_ckp_vectors(text=normalized, user_id=user_id, canonical_type=canonical_type, top_k=8)
    except Exception:
        vector_hits = []

    for hit in vector_hits:
        ckp_id = str(hit.get("ckp_id") or "")
        score = float(hit.get("score") or 0.0)
        if not ckp_id:
            continue
        candidate = (
            db.query(CanonicalKnowledgePoint)
            .filter(CanonicalKnowledgePoint.id == ckp_id, CanonicalKnowledgePoint.user_id == user_id)
            .first()
        )
        if not candidate:
            continue
        if score >= 0.8:
            return candidate
        if score >= 0.7:
            decision = _llm_ckp_same_as_decision(normalized, candidate, score)
            if decision.same and decision.confidence >= 0.8:
                return candidate
    return None


def _refresh_ckp_vector(ckp: CanonicalKnowledgePoint) -> None:
    try:
        embedding_ref = upsert_ckp_vector(ckp)
    except Exception:
        ckp.embedding_status = "failed"
        return
    if embedding_ref:
        ckp.embedding_ref = embedding_ref
        ckp.embedding_model = settings.EMBEDDING_MODEL
        ckp.embedding_status = "done"
    else:
        ckp.embedding_status = "pending"


def _create_or_get_asset_pku(
    db: Session,
    *,
    asset: PersonalAssetItem,
    statement: str,
    unit_type: str,
    confidence: float,
    keywords: list[str],
) -> PersonalKnowledgeUnit:
    normalized = _normalize_space(statement)
    statement_hash = _text_hash(normalized)
    existing = (
        db.query(PersonalKnowledgeUnit)
        .filter(
            PersonalKnowledgeUnit.user_id == asset.user_id,
            PersonalKnowledgeUnit.source_kind == "personal_asset_item",
            PersonalKnowledgeUnit.source_id == asset.id,
            PersonalKnowledgeUnit.unit_type == unit_type,
            PersonalKnowledgeUnit.normalized_statement_hash == statement_hash,
        )
        .first()
    )
    if existing:
        return existing

    pku = PersonalKnowledgeUnit(
        user_id=asset.user_id,
        source_kind="personal_asset_item",
        source_id=asset.id,
        unit_type=unit_type,
        statement=statement,
        normalized_statement=normalized,
        normalized_statement_hash=statement_hash,
        modality=_modality_from_asset(asset, unit_type),
        domains=[asset.category] if asset.category else [],
        concepts=asset.tags or [],
        keywords=keywords,
        evidence_span=statement,
        confidence=max(0.0, min(confidence, 1.0)),
        status="active",
    )
    db.add(pku)
    db.flush()
    return pku


def _create_or_get_asset_unit_pku(
    db: Session,
    *,
    unit: PersonalAssetUnit,
    extracted: ExtractedPKU,
) -> PersonalKnowledgeUnit:
    normalized = _normalize_space(extracted.statement)
    statement_hash = _text_hash(normalized)
    existing = (
        db.query(PersonalKnowledgeUnit)
        .filter(
            PersonalKnowledgeUnit.user_id == unit.user_id,
            PersonalKnowledgeUnit.source_kind == "personal_asset_unit",
            PersonalKnowledgeUnit.source_id == unit.id,
            PersonalKnowledgeUnit.unit_type == extracted.unit_type,
            PersonalKnowledgeUnit.normalized_statement_hash == statement_hash,
        )
        .first()
    )
    if existing:
        return existing

    keywords = extracted.keywords or _extract_keywords(
        extracted.statement,
        unit.title,
        unit.summary,
        unit.category,
        unit.tags or [],
    )
    pku = PersonalKnowledgeUnit(
        user_id=unit.user_id,
        source_kind="personal_asset_unit",
        source_id=unit.id,
        unit_type=extracted.unit_type,
        statement=extracted.statement,
        normalized_statement=normalized,
        normalized_statement_hash=statement_hash,
        modality="fact",
        domains=extracted.domains or ([unit.category] if unit.category else []),
        entities=extracted.entities,
        concepts=extracted.concepts or (unit.tags or []),
        keywords=keywords,
        evidence_span=extracted.evidence_span[:1200],
        confidence=_clamp_confidence(extracted.confidence, 0.72),
        llm_model=extracted.llm_model,
        status="active",
    )
    db.add(pku)
    db.flush()
    return pku


def _fallback_asset_unit_summary_pku(unit: PersonalAssetUnit) -> ExtractedPKU | None:
    summary = _normalize_space(unit.summary or "")
    if not summary:
        return None
    evidence = _normalize_space(unit.content or unit.summary or "")
    return ExtractedPKU(
        statement=summary[:1200],
        unit_type=_unit_type_from_unit_text(summary),
        evidence_span=(evidence or summary)[:1200],
        keywords=_extract_keywords(summary, unit.title, unit.category, unit.tags or []),
        concepts=unit.tags or [],
        entities=[],
        domains=[unit.category] if unit.category else [],
        group="",
        confidence=float((unit.confidence or {}).get("overall", 0.55) or 0.55),
        reason="Summary fallback because LLM PKU extraction returned no valid PKUs.",
        llm_model="",
    )


def _create_or_get_ckp(
    db: Session,
    *,
    asset: PersonalAssetItem,
    pku: PersonalKnowledgeUnit,
    keywords: list[str],
) -> CanonicalKnowledgePoint:
    existing = _find_existing_ckp(
        db,
        user_id=asset.user_id,
        statement=pku.normalized_statement,
        keywords=keywords,
        canonical_type=pku.unit_type,
    )
    if existing:
        return existing

    ckp = CanonicalKnowledgePoint(
        user_id=asset.user_id,
        canonical_type=pku.unit_type,
        title=_short_title(asset.title or pku.normalized_statement),
        canonical_statement=pku.normalized_statement,
        summary=asset.summary,
        aliases=[asset.title] if asset.title else [],
        domains=pku.domains or [],
        entities=pku.entities or [],
        concepts=pku.concepts or [],
        keywords=keywords,
        scope=pku.scope or {},
        conditions=pku.conditions or {},
        status="draft",
        confidence=pku.confidence,
        extra_meta={"created_from": "personal_asset_item", "source_id": asset.id},
    )
    db.add(ckp)
    db.flush()
    _refresh_ckp_vector(ckp)
    return ckp


def _create_or_get_ckp_from_pku(
    db: Session,
    *,
    user_id: str,
    pku: PersonalKnowledgeUnit,
    title: str,
    summary: str = "",
    aliases: list[str] | None = None,
    extra_meta: dict[str, Any] | None = None,
) -> CanonicalKnowledgePoint:
    keywords = _as_list(pku.keywords)
    existing = _find_existing_ckp(
        db,
        user_id=user_id,
        statement=pku.normalized_statement,
        keywords=keywords,
        canonical_type=pku.unit_type,
    )
    if existing:
        return existing

    ckp = CanonicalKnowledgePoint(
        user_id=user_id,
        canonical_type=pku.unit_type,
        title=_short_title(title or pku.normalized_statement),
        canonical_statement=pku.normalized_statement,
        summary=summary,
        aliases=aliases or [],
        domains=pku.domains or [],
        entities=pku.entities or [],
        concepts=pku.concepts or [],
        keywords=keywords,
        scope=pku.scope or {},
        conditions=pku.conditions or {},
        status="draft",
        confidence=pku.confidence,
        extra_meta=extra_meta or {},
    )
    db.add(ckp)
    db.flush()
    _refresh_ckp_vector(ckp)
    return ckp


def _create_or_get_link(
    db: Session,
    *,
    asset: PersonalAssetItem,
    pku: PersonalKnowledgeUnit,
    ckp: CanonicalKnowledgePoint,
) -> PKUCanonicalLink:
    existing = (
        db.query(PKUCanonicalLink)
        .filter(
            PKUCanonicalLink.pku_id == pku.id,
            PKUCanonicalLink.canonical_id == ckp.id,
            PKUCanonicalLink.relation_type == "same_as",
        )
        .first()
    )
    if existing:
        return existing
    link = PKUCanonicalLink(
        user_id=asset.user_id,
        pku_id=pku.id,
        canonical_id=ckp.id,
        relation_type="same_as",
        role=_role_from_asset(asset, pku.unit_type),
        confidence=pku.confidence,
        reason="Initial deterministic settlement from confirmed PersonalAssetItem.",
    )
    db.add(link)
    db.flush()
    return link


def _create_or_get_generic_link(
    db: Session,
    *,
    user_id: str,
    pku: PersonalKnowledgeUnit,
    ckp: CanonicalKnowledgePoint,
    relation_type: str,
    role: str,
    reason: str,
) -> PKUCanonicalLink:
    existing = (
        db.query(PKUCanonicalLink)
        .filter(
            PKUCanonicalLink.pku_id == pku.id,
            PKUCanonicalLink.canonical_id == ckp.id,
            PKUCanonicalLink.relation_type == relation_type,
        )
        .first()
    )
    if existing:
        return existing
    link = PKUCanonicalLink(
        user_id=user_id,
        pku_id=pku.id,
        canonical_id=ckp.id,
        relation_type=relation_type,
        role=role,
        confidence=pku.confidence,
        reason=reason,
    )
    db.add(link)
    db.flush()
    return link


def _create_or_get_pku_relation(
    db: Session,
    *,
    user_id: str,
    source_pku: PersonalKnowledgeUnit,
    target_pku: PersonalKnowledgeUnit,
    relation: ExtractedPKURelation,
    source_kind: str,
    source_id: str,
    llm_model: str,
) -> PKURelation:
    existing = (
        db.query(PKURelation)
        .filter(
            PKURelation.source_pku_id == source_pku.id,
            PKURelation.target_pku_id == target_pku.id,
            PKURelation.relation_type == relation.relation_type,
        )
        .first()
    )
    if existing:
        return existing
    row = PKURelation(
        user_id=user_id,
        source_pku_id=source_pku.id,
        target_pku_id=target_pku.id,
        relation_type=relation.relation_type,
        confidence=relation.confidence,
        reason=relation.reason,
        source_kind=source_kind,
        source_id=source_id,
        llm_model=llm_model,
        extra_meta={},
    )
    db.add(row)
    db.flush()
    return row


def settle_personal_asset_item_to_governance(db: Session, asset: PersonalAssetItem) -> GovernanceResult:
    return GovernanceResult(pku_count=0, canonical_count=0, link_count=0)


def settle_personal_asset_unit_to_governance(db: Session, unit: PersonalAssetUnit) -> GovernanceResult:
    if unit.status != "confirmed":
        return GovernanceResult(pku_count=0, canonical_count=0, link_count=0)

    extraction = _extract_asset_unit_pkus_with_llm(unit)
    extracted_pkus = list(extraction.pkus)
    using_llm_extraction = bool(extracted_pkus)
    if not extracted_pkus:
        fallback = _fallback_asset_unit_summary_pku(unit)
        extracted_pkus = [fallback] if fallback else []
    if not extracted_pkus:
        return GovernanceResult(pku_count=0, canonical_count=0, link_count=0)

    pku_ids: set[str] = set()
    ckp_ids: set[str] = set()
    link_ids: set[str] = set()
    relation_ids: set[str] = set()
    pku_by_ref: dict[str, PersonalKnowledgeUnit] = {}

    for extracted in extracted_pkus:
        pku = _create_or_get_asset_unit_pku(db, unit=unit, extracted=extracted)
        ckp = _create_or_get_ckp_from_pku(
            db,
            user_id=unit.user_id or DEFAULT_USER_ID,
            pku=pku,
            title=unit.title or pku.statement,
            summary=unit.summary or "",
            aliases=[unit.title] if unit.title else [],
            extra_meta={
                "created_from": "personal_asset_unit",
                "source_unit_id": unit.id,
                "source_asset_ids": unit.source_asset_ids or [],
                "extraction_group": extracted.group,
                "extraction_reason": extracted.reason,
            },
        )
        link = _create_or_get_generic_link(
            db,
            user_id=unit.user_id or DEFAULT_USER_ID,
            pku=pku,
            ckp=ckp,
            relation_type="same_as",
            role="synthesized_personal_knowledge",
            reason="Settlement from confirmed PersonalAssetUnit PKU extraction.",
        )
        pku_ids.add(pku.id)
        ckp_ids.add(ckp.id)
        link_ids.add(link.id)
        if extracted.local_id:
            pku_by_ref[_normalize_space(extracted.local_id)] = pku
        pku_by_ref[_normalize_space(extracted.statement)] = pku

    if using_llm_extraction:
        for relation in extraction.relations:
            source_pku = pku_by_ref.get(_normalize_space(relation.from_ref))
            target_pku = pku_by_ref.get(_normalize_space(relation.to_ref))
            if not source_pku or not target_pku or source_pku.id == target_pku.id:
                continue
            row = _create_or_get_pku_relation(
                db,
                user_id=unit.user_id or DEFAULT_USER_ID,
                source_pku=source_pku,
                target_pku=target_pku,
                relation=relation,
                source_kind="personal_asset_unit",
                source_id=unit.id,
                llm_model=extraction.llm_model,
            )
            relation_ids.add(row.id)

    return GovernanceResult(
        pku_count=len(pku_ids),
        canonical_count=len(ckp_ids),
        link_count=len(link_ids),
        pku_relation_count=len(relation_ids),
    )


def clear_document_item_governance(db: Session, item_id: str) -> int:
    chunk_ids = [
        row.id
        for row in db.query(KnowledgeChunk.id)
        .filter(KnowledgeChunk.item_id == item_id)
        .all()
    ]
    if not chunk_ids:
        return 0

    pkus = (
        db.query(PersonalKnowledgeUnit)
        .filter(
            PersonalKnowledgeUnit.source_kind == "document_chunk",
            PersonalKnowledgeUnit.source_id.in_(chunk_ids),
        )
        .all()
    )
    count = len(pkus)
    for pku in pkus:
        db.delete(pku)
    db.flush()
    return count


def _create_or_get_document_pku(
    db: Session,
    *,
    item: KnowledgeItem,
    chunk: KnowledgeChunk,
    statement: str,
    keywords: list[str],
) -> PersonalKnowledgeUnit:
    normalized = _normalize_space(statement)
    statement_hash = _text_hash(normalized)
    type_decision = _ollama_pku_type_decision(
        text=statement,
        fallback=_unit_type_from_document_text(statement),
        title=item.title,
        category=item.category,
        tags=item.tags or [],
    )
    unit_type = type_decision.unit_type
    user_id = item.user_id or DEFAULT_USER_ID
    existing = (
        db.query(PersonalKnowledgeUnit)
        .filter(
            PersonalKnowledgeUnit.user_id == user_id,
            PersonalKnowledgeUnit.source_kind == "document_chunk",
            PersonalKnowledgeUnit.source_id == chunk.id,
            PersonalKnowledgeUnit.unit_type == unit_type,
            PersonalKnowledgeUnit.normalized_statement_hash == statement_hash,
        )
        .first()
    )
    if existing:
        return existing

    pku = PersonalKnowledgeUnit(
        user_id=user_id,
        source_kind="document_chunk",
        source_id=chunk.id,
        unit_type=unit_type,
        statement=statement,
        normalized_statement=normalized,
        normalized_statement_hash=statement_hash,
        modality="fact",
        domains=[item.category] if item.category else [],
        concepts=item.tags or [],
        keywords=keywords,
        evidence_span=statement[:1200],
        confidence=0.72,
        llm_model=type_decision.llm_model,
        status="active",
    )
    db.add(pku)
    db.flush()
    return pku


def settle_document_item_to_governance(db: Session, item_id: str) -> GovernanceResult:
    item = db.query(KnowledgeItem).filter(KnowledgeItem.id == item_id).first()
    if not item:
        return GovernanceResult(pku_count=0, canonical_count=0, link_count=0)

    chunks = (
        db.query(KnowledgeChunk)
        .filter(KnowledgeChunk.item_id == item_id, KnowledgeChunk.chunk_type == "parent")
        .order_by(KnowledgeChunk.created_at.asc(), KnowledgeChunk.id.asc())
        .all()
    )
    if not chunks:
        chunks = (
            db.query(KnowledgeChunk)
            .filter(KnowledgeChunk.item_id == item_id)
            .order_by(KnowledgeChunk.created_at.asc(), KnowledgeChunk.id.asc())
            .all()
        )

    pku_ids: set[str] = set()
    ckp_ids: set[str] = set()
    link_ids: set[str] = set()

    for chunk in chunks:
        statement = _normalize_space(chunk.chunk_text or "")
        if not statement:
            continue
        statement = statement[:1200]
        keywords = _extract_keywords(statement, item.title, item.summary, item.category, item.tags or [])
        pku = _create_or_get_document_pku(
            db,
            item=item,
            chunk=chunk,
            statement=statement,
            keywords=keywords,
        )
        ckp = _create_or_get_ckp_from_pku(
            db,
            user_id=item.user_id or DEFAULT_USER_ID,
            pku=pku,
            title=item.title or statement,
            summary=item.summary or "",
            aliases=[item.title] if item.title else [],
            extra_meta={"created_from": "document_chunk", "source_item_id": item.id, "source_chunk_id": chunk.id},
        )
        link = _create_or_get_generic_link(
            db,
            user_id=item.user_id or DEFAULT_USER_ID,
            pku=pku,
            ckp=ckp,
            relation_type="same_as",
            role="external_reference",
            reason="Initial deterministic settlement from ingested KnowledgeChunk.",
        )
        pku_ids.add(pku.id)
        ckp_ids.add(ckp.id)
        link_ids.add(link.id)

    return GovernanceResult(pku_count=len(pku_ids), canonical_count=len(ckp_ids), link_count=len(link_ids))
