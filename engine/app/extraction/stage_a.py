"""Stage A LLM entity extraction. One subagent = one chunk = one LLM call."""
import logging
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed

from backend.app.services.entity_extraction import EntityCandidate
from backend.app.services.entity_resolution import alias_keys_for_surface, normalize_entity_key

from ..config import settings
from ..llm.client import chat
from .deterministic import extract_document_structure_candidates
from .prompts import build_prompt, parse_stage_a_json, parse_stage_a_relations

logger = logging.getLogger("uvicorn.error")

_MAX_CHUNK_CHARS = 4000  # truncate very long chunks before sending to LLM


class GraphExtractor(ABC):
    """Extracts EntityCandidates from one chunk. Implementations never raise."""

    @abstractmethod
    def extract(self, text: str, *, chunk_id: str = "") -> list[EntityCandidate]:
        raise NotImplementedError


class LLMGraphExtractor(GraphExtractor):
    """LLM + deterministic extraction for one chunk.

    Coalesces the whole Stage A chain: truncate → build_prompt → chat →
    json_repair parse → normalize_extraction_result, plus the deterministic
    document-structure candidates (Prism's full-coverage fallback).
    """

    def __init__(self, model: str | None = None):
        self.model = model or _stage_a_model()

    def extract(self, text: str, *, chunk_id: str = "") -> list[EntityCandidate]:
        full_text = (text or "").strip()
        if not full_text:
            return []
        deterministic = extract_document_structure_candidates(full_text, source_kind="document_chunk")
        prompt = build_prompt(full_text[:_MAX_CHUNK_CHARS])
        try:
            raw = chat([{"role": "user", "content": prompt}], model=self.model)
        except Exception as exc:
            logger.warning("[stage_a] llm_failed chunk_id=%s error=%s", chunk_id, exc)
            return deterministic
        entities = parse_stage_a_json(raw)
        relations = parse_stage_a_relations(raw)
        candidates = list(deterministic)
        candidates.extend(normalize_extraction_result(entities, relations))
        return candidates


def normalize_extraction_result(entities: list[dict], relations: list[dict]) -> list[EntityCandidate]:
    """Normalize parsed LLM output into deduped EntityCandidates.

    entities: [{entity_type, surface, tier, score, evidence}]
    relations: [{subject, predicate, object, tier, score}]

    Dedups entities by (entity_type, surface) keeping the highest confidence and
    merging evidence; dedups relations by (subject, predicate, object).
    """
    candidates: list[EntityCandidate] = []
    by_entity_key: dict[tuple[str, str], EntityCandidate] = {}

    for item in entities:
        candidate = _to_candidate(item)
        key = (candidate.entity_type, candidate.surface_text)
        existing = by_entity_key.get(key)
        if existing is None:
            by_entity_key[key] = candidate
            candidates.append(candidate)
            continue
        if candidate.confidence > existing.confidence:
            existing.confidence = candidate.confidence
            existing.extraction_method = candidate.extraction_method
        if candidate.evidence_span and candidate.evidence_span not in existing.evidence_span:
            existing.evidence_span = f"{existing.evidence_span} {candidate.evidence_span}".strip()

    seen_relations: set[tuple[str, str, str]] = set()
    for item in relations:
        candidate = _to_relation_candidate(item)
        key = (candidate.subject_surface, candidate.predicate, candidate.object_surface)
        if key in seen_relations:
            continue
        seen_relations.add(key)
        candidates.append(candidate)

    return candidates


def extract_entities_for_chunk(chunk_text: str, chunk_id: str = "") -> list[EntityCandidate]:
    """Extract entity candidates for one chunk via LLM. never raises."""
    return LLMGraphExtractor().extract(chunk_text, chunk_id=chunk_id)


def _stage_a_model() -> str | None:
    return settings.ENTITY_EXTRACT_MODEL or None


def _to_candidate(item: dict) -> EntityCandidate:
    surface = item["surface"]
    entity_type = item["entity_type"]
    tier = item["tier"]
    score = item["score"]
    return EntityCandidate(
        kind="entity",
        entity_type=entity_type,
        surface_text=surface,
        normalized_key=normalize_entity_key(surface),
        aliases=alias_keys_for_surface(surface, entity_type=entity_type),
        confidence=score,
        evidence_span=item.get("evidence", "")[:500],
        extraction_method=f"llm_stage_a:{tier}",
    )


def _to_relation_candidate(item: dict) -> EntityCandidate:
    subject = item["subject"]
    obj = item["object"]
    tier = item["tier"]
    score = item["score"]
    return EntityCandidate(
        kind="relation",
        confidence=score,
        evidence_span=f"{subject} {item['predicate']} {obj}",
        extraction_method=f"llm_stage_a:{tier}",
        subject_surface=subject,
        predicate=item["predicate"],
        object_surface=obj,
        object_entity_type="",
    )


def extract_stage_a_parallel(
    chunks: list[tuple[str, str]],
    max_workers: int | None = None,
    extractor: GraphExtractor | None = None,
) -> dict[str, list[EntityCandidate]]:
    """Fan out Stage A extraction across chunks in parallel.

    chunks: list of (chunk_id, chunk_text). Each chunk is one 'subagent' (one LLM call).
    Returns {chunk_id: [EntityCandidate, ...]}. A failed chunk yields an empty list
    and never aborts the batch.
    """
    workers = max_workers or settings.ENTITY_EXTRACT_WORKERS
    extractor = extractor or LLMGraphExtractor()
    results: dict[str, list[EntityCandidate]] = {}
    if not chunks:
        return results
    with ThreadPoolExecutor(max_workers=min(workers, len(chunks)), thread_name_prefix="stage-a") as pool:
        future_to_chunk = {pool.submit(extractor.extract, text, chunk_id=cid): cid for cid, text in chunks}
        for future in as_completed(future_to_chunk):
            cid = future_to_chunk[future]
            try:
                results[cid] = future.result()
            except Exception as exc:
                logger.warning("[stage_a] chunk_failed chunk_id=%s error=%s", cid, exc)
                results[cid] = []
    return results
