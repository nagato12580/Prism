import re
from dataclasses import dataclass, field

from backend.app.models import EntityAlias, EntityMention, EntityRelation, KnowledgeEntity
from backend.app.services.entity_resolution import alias_keys_for_surface, normalize_entity_key


_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PERSON_RE = re.compile(r"^[A-Z][A-Za-z'.-]+\s+[A-Z][A-Za-z'.-]+$")
_PERSON_STOP_TERMS = {
    "senior member",
    "junior member",
    "associate professor",
    "assistant professor",
    "corresponding author",
    "proximal gradient",
    "stochastic gradient",
    "gradient descent",
    "beam search",
    "multi-view",
    "multi view",
    "deep norm",
    "post norm",
    "pre norm",
}
_ORG_TERMS = (
    "University",
    "College",
    "Institute",
    "Laboratory",
    "Lab",
    "School",
    "Department",
    "Inc",
    "Ltd",
    "Corporation",
)
_ORG_SPLIT_RE = re.compile(r"[,;]")
_NOISE_TOKENS = (
    "```",
    "###",
    "#include",
    "class ",
    "def ",
    "id:",
    "repo:",
    "hooks",
    "json",
    "yaml",
    "csv",
    "args:",
    "select =",
)


@dataclass
class EntityCandidate:
    kind: str
    entity_type: str = ""
    surface_text: str = ""
    normalized_key: str = ""
    aliases: list[str] = field(default_factory=list)
    confidence: float = 0.5
    evidence_span: str = ""
    extraction_method: str = ""
    subject_surface: str = ""
    predicate: str = ""
    object_surface: str = ""
    object_entity_type: str = ""


def extract_entity_candidates_from_text(text: str, source_kind: str = "") -> list[EntityCandidate]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    candidates: list[EntityCandidate] = []

    paper_title = _extract_paper_title(lines)
    if paper_title:
        candidates.append(_entity_candidate("paper", paper_title, 0.9, paper_title, "rule_paper_title"))

    authors = _extract_author_names(lines, paper_title)
    for author in authors:
        candidates.append(_entity_candidate("person", author, 0.86, author, "rule_author_line"))

    for email in _EMAIL_RE.findall(text):
        candidates.append(_entity_candidate("email", email, 0.95, email, "rule_email"))

    organizations = _extract_organizations(lines)
    for organization in organizations:
        candidates.append(_entity_candidate("organization", organization, 0.78, organization, "rule_organization"))

    if paper_title:
        for author in authors:
            candidates.append(
                EntityCandidate(
                    kind="relation",
                    confidence=0.82,
                    evidence_span=f"{author} authored {paper_title}",
                    extraction_method="rule_author_paper_relation",
                    subject_surface=author,
                    predicate="authored",
                    object_surface=paper_title,
                    object_entity_type="paper",
                )
            )

    if organizations and authors:
        for author in authors:
            for organization in organizations:
                candidates.append(
                    EntityCandidate(
                        kind="relation",
                        confidence=0.65,
                        evidence_span=f"{author} affiliated with {organization}",
                        extraction_method="rule_author_organization_relation",
                        subject_surface=author,
                        predicate="affiliated_with",
                        object_surface=organization,
                        object_entity_type="organization",
                    )
                )

    return _dedupe_candidates(candidates)


def _looks_like_noise_span(text: str) -> bool:
    lowered = text.lower()
    if any(token in lowered for token in _NOISE_TOKENS):
        return True
    if len(text) > 160:
        return True
    if text.count("{") + text.count("}") + text.count("[") + text.count("]") >= 4:
        return True
    return False


def extract_and_settle_entities(
    db,
    source_kind: str,
    source_id: str,
    text: str,
    item_id: str = "",
    chunk_id: str = "",
    user_id: str = "default-user",
) -> list[KnowledgeEntity]:
    candidates = extract_entity_candidates_from_text(text, source_kind=source_kind)
    settled_by_surface: dict[tuple[str, str], KnowledgeEntity] = {}
    settled_entities: list[KnowledgeEntity] = []

    for candidate in candidates:
        if candidate.kind != "entity":
            continue

        entity = _upsert_entity(db, candidate, user_id)
        _upsert_aliases(db, entity, candidate)
        _upsert_mention(db, entity, candidate, source_kind, source_id, item_id, chunk_id)
        settled_by_surface[(candidate.entity_type, candidate.surface_text)] = entity
        settled_entities.append(entity)

    db.flush()

    for candidate in candidates:
        if candidate.kind != "relation":
            continue
        subject = _resolve_entity_for_relation(db, settled_by_surface, user_id, "person", candidate.subject_surface)
        object_entity = _resolve_entity_for_relation(
            db,
            settled_by_surface,
            user_id,
            candidate.object_entity_type,
            candidate.object_surface,
        )
        if subject and object_entity:
            _upsert_relation(db, subject, object_entity, candidate, source_kind, source_id)

    db.flush()
    return settled_entities


def _entity_candidate(
    entity_type: str,
    surface_text: str,
    confidence: float,
    evidence_span: str,
    extraction_method: str,
) -> EntityCandidate:
    return EntityCandidate(
        kind="entity",
        entity_type=entity_type,
        surface_text=surface_text,
        normalized_key=normalize_entity_key(surface_text),
        aliases=alias_keys_for_surface(surface_text, entity_type=entity_type),
        confidence=confidence,
        evidence_span=evidence_span,
        extraction_method=extraction_method,
    )


def _extract_paper_title(lines: list[str]) -> str:
    for line in lines:
        if ":" in line and "@" not in line:
            title = line.strip()
            if _looks_like_noise_span(title):
                continue
            prefix = title.split(":", 1)[0].strip().lower()
            if prefix in {"repos", "repo", "args", "hooks", "select", "ignore"}:
                continue
            if len(title) <= 120 and not _looks_like_noise_span(title):
                return title
    return ""


def _extract_author_names(lines: list[str], paper_title: str) -> list[str]:
    names: list[str] = []
    search_lines = lines[1:6] if paper_title and lines else lines[:5]
    for line in search_lines:
        if _EMAIL_RE.search(line) or _contains_org_term(line):
            continue
        for token in re.split(r",|;|\band\b", line):
            cleaned = _clean_author_token(token)
            if _looks_like_person_name(cleaned) and cleaned not in names:
                names.append(cleaned)
    return names


def _looks_like_person_name(text: str) -> bool:
    if not _PERSON_RE.fullmatch(text):
        return False
    lowered = text.lower().strip()
    if lowered in _PERSON_STOP_TERMS:
        return False
    parts = text.split()
    if len(parts) != 2:
        return False
    # Reject titles / role nouns that often appear in paper front matter or prose.
    if any(part.lower() in {"member", "professor", "author", "editor", "gradient", "search", "norm"} for part in parts):
        return False
    # Real person names are usually alphabetic with modest token length.
    if any(len(part) < 2 or len(part) > 20 for part in parts):
        return False
    return True


def _clean_author_token(token: str) -> str:
    cleaned = token.strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    # Strip footnote-style leading markers such as "1 ", "1,2 ", "* ".
    cleaned = re.sub(r"^[*\d,]+\s*", "", cleaned)
    # Strip attached footnote markers like "Yanchao Tan1,2".
    cleaned = re.sub(r"(?<=[A-Za-z])\d+(?:,\d+)*$", "", cleaned).strip()
    cleaned = re.sub(r"\d+(?:,\d+)*$", "", cleaned).strip()
    return cleaned


def _extract_organizations(lines: list[str]) -> list[str]:
    organizations: list[str] = []
    for line in lines:
        if _EMAIL_RE.search(line):
            continue
        for part in _ORG_SPLIT_RE.split(line):
            if not _contains_org_term(part):
                continue
            organization = _clean_organization(part)
            if (
                organization
                and organization not in organizations
                and len(organization) <= 80
                and not _looks_like_noise_span(organization)
            ):
                organizations.append(organization)
    return organizations


def _clean_organization(value: str) -> str:
    organization = re.sub(r"^\d+\s+", "", value.strip(" ,.;"))
    organization = re.sub(r"^\d+(?:,\d+)*\s*", "", organization)
    organization = re.sub(r"\s*\d+(?:,\d+)*$", "", organization)
    organization = re.sub(r"\s+", " ", organization)
    return organization


def _contains_org_term(line: str) -> bool:
    return any(term in line for term in _ORG_TERMS)


def _dedupe_candidates(candidates: list[EntityCandidate]) -> list[EntityCandidate]:
    seen: set[tuple[str, str, str, str, str]] = set()
    deduped: list[EntityCandidate] = []
    for candidate in candidates:
        key = (
            candidate.kind,
            candidate.entity_type,
            candidate.surface_text or candidate.subject_surface,
            candidate.predicate,
            candidate.object_surface,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _upsert_entity(db, candidate: EntityCandidate, user_id: str) -> KnowledgeEntity:
    entity = (
        db.query(KnowledgeEntity)
        .filter_by(user_id=user_id, entity_type=candidate.entity_type, normalized_key=candidate.normalized_key)
        .one_or_none()
    )
    if entity:
        existing_aliases = list(entity.aliases or [])
        for alias in candidate.aliases:
            if alias not in existing_aliases:
                existing_aliases.append(alias)
        entity.aliases = existing_aliases
        entity.confidence = max(entity.confidence or 0.0, candidate.confidence)
        return entity

    entity = KnowledgeEntity(
        user_id=user_id,
        entity_type=candidate.entity_type,
        canonical_name=candidate.surface_text[:500],
        normalized_key=candidate.normalized_key[:500],
        aliases=list(candidate.aliases),
        confidence=candidate.confidence,
        status="active",
    )
    db.add(entity)
    db.flush()
    return entity


def _upsert_aliases(db, entity: KnowledgeEntity, candidate: EntityCandidate) -> None:
    for alias_key in candidate.aliases:
        existing = db.query(EntityAlias).filter_by(entity_id=entity.id, normalized_key=alias_key).one_or_none()
        if existing:
            continue
        db.add(
            EntityAlias(
                entity_id=entity.id,
                alias=alias_key,
                normalized_key=alias_key,
                confidence=candidate.confidence,
                extraction_method=candidate.extraction_method,
            )
        )


def _upsert_mention(
    db,
    entity: KnowledgeEntity,
    candidate: EntityCandidate,
    source_kind: str,
    source_id: str,
    item_id: str,
    chunk_id: str,
) -> None:
    existing = (
        db.query(EntityMention)
        .filter_by(
            entity_id=entity.id,
            source_kind=source_kind,
            source_id=source_id,
            surface_text=candidate.surface_text,
        )
        .one_or_none()
    )
    if existing:
        return
    db.add(
        EntityMention(
            entity_id=entity.id,
            source_kind=source_kind,
            source_id=source_id,
            item_id=item_id,
            chunk_id=chunk_id,
            surface_text=candidate.surface_text,
            normalized_key=candidate.normalized_key,
            evidence_span=candidate.evidence_span,
            confidence=candidate.confidence,
            extraction_method=candidate.extraction_method,
        )
    )


def _resolve_entity_for_relation(
    db,
    settled_by_surface: dict[tuple[str, str], KnowledgeEntity],
    user_id: str,
    entity_type: str,
    surface_text: str,
) -> KnowledgeEntity | None:
    entity = settled_by_surface.get((entity_type, surface_text))
    if entity:
        return entity
    return (
        db.query(KnowledgeEntity)
        .filter_by(user_id=user_id, entity_type=entity_type, normalized_key=normalize_entity_key(surface_text))
        .one_or_none()
    )


def _upsert_relation(
    db,
    subject: KnowledgeEntity,
    object_entity: KnowledgeEntity,
    candidate: EntityCandidate,
    source_kind: str,
    source_id: str,
) -> None:
    existing = (
        db.query(EntityRelation)
        .filter_by(
            subject_entity_id=subject.id,
            predicate=candidate.predicate,
            object_entity_id=object_entity.id,
            source_kind=source_kind,
            source_id=source_id,
        )
        .one_or_none()
    )
    if existing:
        return

    db.add(
        EntityRelation(
            subject_entity_id=subject.id,
            predicate=candidate.predicate,
            object_entity_id=object_entity.id,
            source_kind=source_kind,
            source_id=source_id,
            evidence_span=candidate.evidence_span,
            confidence=candidate.confidence,
            extraction_method=candidate.extraction_method,
        )
    )
