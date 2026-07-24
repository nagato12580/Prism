"""Run-local citation registry.

Maps canonical Evidence to short, model-visible ids (``K1``, ``K2``, ...) and
validates the ``[Kx]`` tokens the model emits in its answer.

Design rules (Plan 5):

- Evidence is keyed by its full provenance tuple
  ``(kb_uid, file_uid, chunk_uid, index_generation)`` so the same chunk in a
  different generation is *not* silently reused.
- Ids are assigned in first-seen order and are idempotent: registering the same
  provenance twice returns the same id.
- ``validate`` never *resolves* an unknown id into a source; unknown ids are
  reported separately so they can surface as trace warnings without becoming
  source cards.
- The registry is run-local and mutable; it never re-resolves against a later
  active generation. Persisted snapshots are taken from this registry at answer
  time (see ``AgentTraceRecorder``).
"""
from __future__ import annotations

import re
from typing import Any, NamedTuple


_CITATION_RE = re.compile(r"\[K(\d+)\]")


class CitationValidation(NamedTuple):
    valid_ids: tuple[str, ...]
    invalid_ids: tuple[str, ...]
    # id -> evidence dict (deep-ish copy stamped with its short id).
    matched: dict[str, dict[str, Any]]


def evidence_key(evidence: dict[str, Any]) -> tuple[str, str, str, str]:
    """Canonical provenance key for an Evidence dict.

    Falls back to ``chunk_id`` for legacy evidence shapes that use it instead of
    ``chunk_uid``.
    """
    chunk_uid = evidence.get("chunk_uid")
    if not chunk_uid:
        chunk_uid = evidence.get("chunk_id")
    return (
        str(evidence.get("kb_uid") or ""),
        str(evidence.get("file_uid") or ""),
        str(chunk_uid or ""),
        str(evidence.get("index_generation") or ""),
    )


class CitationRegistry:
    """Assigns stable short ids to Evidence and validates ``[Kx]`` citations."""

    def __init__(self) -> None:
        self._key_to_id: dict[tuple[str, str, str, str], str] = {}
        self._id_to_evidence: dict[str, dict[str, Any]] = {}
        self._counter = 0

    # -- registration ----------------------------------------------------- #

    def register(self, evidence: dict[str, Any]) -> str:
        """Assign (or reuse) a short id for ``evidence`` and return it."""
        key = evidence_key(evidence)
        existing = self._key_to_id.get(key)
        if existing is not None:
            return existing
        self._counter += 1
        short_id = f"K{self._counter}"
        self._key_to_id[key] = short_id
        self._id_to_evidence[short_id] = self._stamp(evidence, short_id)
        return short_id

    def id_for(self, evidence: dict[str, Any]) -> str | None:
        """Return the assigned id for ``evidence`` without registering a new one."""
        return self._key_to_id.get(evidence_key(evidence))

    def assign_ids(self, evidence_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return copies of ``evidence_items`` each stamped with its short id.

        Registration is a side effect; the input dicts are not mutated.
        """
        stamped: list[dict[str, Any]] = []
        for item in evidence_items:
            if not isinstance(item, dict):
                continue
            short_id = self.register(item)
            stamped.append(self._stamp(item, short_id))
        return stamped

    # -- validation ------------------------------------------------------- #

    def validate(self, text: str | None) -> CitationValidation:
        """Parse ``[Kx]`` tokens from ``text`` and split valid vs unknown ids."""
        tokens = _CITATION_RE.findall(text or "")
        ordered: list[str] = []
        seen: set[str] = set()
        for number in tokens:
            cid = f"K{number}"
            if cid not in seen:
                seen.add(cid)
                ordered.append(cid)
        valid = tuple(cid for cid in ordered if cid in self._id_to_evidence)
        invalid = tuple(cid for cid in ordered if cid not in self._id_to_evidence)
        matched = {cid: dict(self._id_to_evidence[cid]) for cid in valid}
        return CitationValidation(valid_ids=valid, invalid_ids=invalid, matched=matched)

    # -- snapshot --------------------------------------------------------- #

    def snapshot(self) -> list[dict[str, Any]]:
        """All registered evidence, ordered by id, each stamped with its id."""
        ordered_ids = sorted(self._id_to_evidence, key=_id_number)
        return [dict(self._id_to_evidence[cid]) for cid in ordered_ids]

    def __len__(self) -> int:
        return len(self._id_to_evidence)

    # -- helpers ---------------------------------------------------------- #

    @staticmethod
    def _stamp(evidence: dict[str, Any], short_id: str) -> dict[str, Any]:
        stamped = dict(evidence)
        stamped["evidence_id"] = short_id
        return stamped


def _id_number(short_id: str) -> int:
    try:
        return int(short_id[1:])
    except (TypeError, ValueError):
        return 0
