"""Stage A LLM entity extraction. One subagent = one chunk = one LLM call."""
import logging

from backend.app.services.entity_extraction import EntityCandidate
from backend.app.services.entity_resolution import alias_keys_for_surface, normalize_entity_key

from ..config import settings
from ..llm.client import chat
from .prompts import STAGE_A_EXTRACTION_PROMPT, parse_stage_a_json

logger = logging.getLogger("uvicorn.error")

_MAX_CHUNK_CHARS = 4000  # truncate very long chunks before sending to LLM


def extract_entities_for_chunk(chunk_text: str, chunk_id: str = "") -> list[EntityCandidate]:
    """Extract entity candidates for one chunk via LLM. never raises."""
    text = (chunk_text or "").strip()[:_MAX_CHUNK_CHARS]
    if not text:
        return []
    prompt = STAGE_A_EXTRACTION_PROMPT.format(chunk_text=text)
    try:
        raw = chat([{"role": "user", "content": prompt}], model=_stage_a_model())
    except Exception as exc:
        logger.warning("[stage_a] llm_failed chunk_id=%s error=%s", chunk_id, exc)
        return []
    parsed = parse_stage_a_json(raw)
    return [_to_candidate(p, chunk_id) for p in parsed]


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
