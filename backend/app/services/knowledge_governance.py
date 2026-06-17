# prism/backend/app/services/knowledge_governance.py
import hashlib
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.app.models.asset import PersonalAssetItem
from backend.app.models.knowledge_governance import (
    CanonicalKnowledgePoint,
    PKUCanonicalLink,
    PersonalKnowledgeUnit,
)
from backend.app.models.knowledge_item import KnowledgeChunk, KnowledgeItem


DEFAULT_USER_ID = "default-user"


@dataclass(frozen=True)
class GovernanceResult:
    pku_count: int
    canonical_count: int
    link_count: int


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


def _unit_type_from_document_text(text: str) -> str:
    lowered = (text or "").lower()
    if any(word in lowered for word in ["定义", "是指", "refers to", "defined as"]):
        return "definition"
    if any(word in lowered for word in ["方法", "步骤", "流程", "strategy", "method", "approach"]):
        return "method"
    if any(word in lowered for word in ["必须", "应该", "规则", "must", "should", "rule"]):
        return "rule"
    return "claim"


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


def _find_existing_ckp(db: Session, *, user_id: str, statement: str, keywords: list[str]) -> CanonicalKnowledgePoint | None:
    normalized = _normalize_space(statement)
    if not normalized:
        return None
    like_title = f"%{_short_title(normalized, '')[:24]}%"
    query = db.query(CanonicalKnowledgePoint).filter(CanonicalKnowledgePoint.user_id == user_id)
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
    return best if best_score >= 2 else None


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


def _create_or_get_ckp(
    db: Session,
    *,
    asset: PersonalAssetItem,
    pku: PersonalKnowledgeUnit,
    keywords: list[str],
) -> CanonicalKnowledgePoint:
    existing = _find_existing_ckp(db, user_id=asset.user_id, statement=pku.normalized_statement, keywords=keywords)
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
    existing = _find_existing_ckp(db, user_id=user_id, statement=pku.normalized_statement, keywords=keywords)
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


def settle_personal_asset_item_to_governance(db: Session, asset: PersonalAssetItem) -> GovernanceResult:
    if asset.status != "confirmed":
        return GovernanceResult(pku_count=0, canonical_count=0, link_count=0)

    pku_ids: set[str] = set()
    ckp_ids: set[str] = set()
    link_ids: set[str] = set()

    for candidate in _candidate_statements_from_asset(asset):
        keywords = _extract_keywords(
            candidate["statement"],
            asset.title,
            asset.summary,
            asset.category,
            asset.tags or [],
            asset.raw_keywords or [],
        )
        pku = _create_or_get_asset_pku(
            db,
            asset=asset,
            statement=candidate["statement"],
            unit_type=candidate["unit_type"],
            confidence=candidate["confidence"],
            keywords=keywords,
        )
        ckp = _create_or_get_ckp(db, asset=asset, pku=pku, keywords=keywords)
        link = _create_or_get_link(db, asset=asset, pku=pku, ckp=ckp)
        pku_ids.add(pku.id)
        ckp_ids.add(ckp.id)
        link_ids.add(link.id)

    return GovernanceResult(pku_count=len(pku_ids), canonical_count=len(ckp_ids), link_count=len(link_ids))


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
    unit_type = _unit_type_from_document_text(statement)
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
