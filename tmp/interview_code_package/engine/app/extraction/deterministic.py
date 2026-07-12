from backend.app.services.entity_extraction import EntityCandidate, _entity_candidate


def extract_document_structure_candidates(
    text: str,
    source_kind: str,
) -> list[EntityCandidate]:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    candidates: list[EntityCandidate] = []

    for line in lines:
        if line.startswith("# "):
            surface = line[2:].strip()
            if surface:
                candidates.append(
                    _entity_candidate(
                        "concept",
                        surface,
                        1.0,
                        line,
                        "deterministic_heading",
                    )
                )
        if line.startswith("- "):
            surface = line[2:].strip()
            if surface:
                candidates.append(
                    _entity_candidate(
                        "concept",
                        surface,
                        1.0,
                        line,
                        "deterministic_list_item",
                    )
                )

    return candidates
