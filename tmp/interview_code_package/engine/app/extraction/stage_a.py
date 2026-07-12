"""Stage A LLM entity extraction. One subagent = one chunk = one LLM call."""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from backend.app.services.entity_extraction import EntityCandidate
from backend.app.services.entity_resolution import alias_keys_for_surface, normalize_entity_key

from ..config import settings
from ..llm.client import chat
from .deterministic import extract_document_structure_candidates
from .prompts import STAGE_A_EXTRACTION_PROMPT, parse_stage_a_json, parse_stage_a_relations

logger = logging.getLogger("uvicorn.error")

_MAX_CHUNK_CHARS = 4000  # truncate very long chunks before sending to LLM


def extract_entities_for_chunk(chunk_text: str, chunk_id: str = "") -> list[EntityCandidate]:
    """Extract entity candidates for one chunk via LLM. never raises."""
    full_text = (chunk_text or "").strip()
    if not full_text:
        return []
    deterministic = extract_document_structure_candidates(full_text, source_kind="document_chunk")
    text = full_text[:_MAX_CHUNK_CHARS]
    prompt = STAGE_A_EXTRACTION_PROMPT.format(chunk_text=text)
    try:
        raw = chat([{"role": "user", "content": prompt}], model=_stage_a_model())
    except Exception as exc:
        logger.warning("[stage_a] llm_failed chunk_id=%s error=%s", chunk_id, exc)
        return deterministic
    entities = parse_stage_a_json(raw)
    relations = parse_stage_a_relations(raw)
    candidates = list(deterministic)
    candidates.extend(_to_candidate(p, chunk_id) for p in entities)
    candidates.extend(_to_relation_candidate(r, chunk_id) for r in relations)
    return candidates


def _stage_a_model() -> str | None:
    return settings.ENTITY_EXTRACT_MODEL or None


def _to_candidate(item: dict, chunk_id: str) -> EntityCandidate:
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


def _to_relation_candidate(item: dict, chunk_id: str) -> EntityCandidate:
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
) -> dict[str, list[EntityCandidate]]:
    """Fan out Stage A extraction across chunks in parallel.

    chunks: list of (chunk_id, chunk_text). Each chunk is one 'subagent' (one LLM call).
    Returns {chunk_id: [EntityCandidate, ...]}. A failed chunk yields an empty list
    and never aborts the batch.
    """
    workers = max_workers or settings.ENTITY_EXTRACT_WORKERS
    results: dict[str, list[EntityCandidate]] = {}
    if not chunks:
        return results
    with ThreadPoolExecutor(max_workers=min(workers, len(chunks)), thread_name_prefix="stage-a") as pool:
        future_to_chunk = {pool.submit(extract_entities_for_chunk, text, cid): cid for cid, text in chunks}
        for future in as_completed(future_to_chunk):
            cid = future_to_chunk[future]
            try:
                results[cid] = future.result()
            except Exception as exc:
                logger.warning("[stage_a] chunk_failed chunk_id=%s error=%s", cid, exc)
                results[cid] = []
    return results
