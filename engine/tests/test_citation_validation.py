"""Task 5: CitationRegistry assigns stable short ids, validates [Kx] tokens,
and never resolves a stale/unknown id as a real source."""

from engine.app.agent.citations import CitationRegistry


def _evidence(chunk_uid, kb_uid="kb-a", file_uid="file-a", generation="gen-1", **extra):
    item = {
        "kb_uid": kb_uid,
        "file_uid": file_uid,
        "chunk_uid": chunk_uid,
        "index_generation": generation,
        "excerpt": f"text {chunk_uid}",
    }
    item.update(extra)
    return item


def test_assigns_stable_short_ids_in_first_seen_order():
    registry = CitationRegistry()

    assert registry.register(_evidence("chunk-b")) == "K1"
    assert registry.register(_evidence("chunk-a")) == "K2"
    # Same provenance key -> same id (idempotent).
    assert registry.register(_evidence("chunk-b")) == "K1"


def test_key_is_full_provenance_not_chunk_uid_alone():
    registry = CitationRegistry()
    # Same chunk_uid but different kb/file/generation are distinct evidence.
    assert registry.register(_evidence("c1", kb_uid="kb-a")) == "K1"
    assert registry.register(_evidence("c1", kb_uid="kb-b")) == "K2"


def test_unknown_citation_is_reported_not_resolved():
    registry = CitationRegistry()
    registry.register(_evidence("chunk-b"))  # K1

    result = registry.validate("Answer [K1] and [K9]")

    assert result.valid_ids == ("K1",)
    assert result.invalid_ids == ("K9",)


def test_validate_dedupes_and_preserves_first_seen_order():
    registry = CitationRegistry()
    registry.register(_evidence("c-a"))  # K1
    registry.register(_evidence("c-b"))  # K2

    result = registry.validate("see [K2] then [K1] then [K2] again and [K7]")

    assert result.valid_ids == ("K2", "K1")
    assert result.invalid_ids == ("K7",)


def test_assign_ids_injects_short_id_into_evidence():
    registry = CitationRegistry()
    stamped = registry.assign_ids([_evidence("c-a"), _evidence("c-b")])

    assert [item["evidence_id"] for item in stamped] == ["K1", "K2"]
    # Original item dicts are not mutated.
    assert "evidence_id" not in _evidence("c-a")


def test_snapshot_is_ordered_and_carries_short_ids():
    registry = CitationRegistry()
    registry.register(_evidence("c-b"))
    registry.register(_evidence("c-a"))

    snap = registry.snapshot()

    assert [item["evidence_id"] for item in snap] == ["K1", "K2"]
    assert snap[0]["chunk_uid"] == "c-b"


def test_unmatched_citation_text_returns_empty():
    registry = CitationRegistry()
    registry.register(_evidence("c-a"))

    result = registry.validate("plain text with no citations")

    assert result.valid_ids == ()
    assert result.invalid_ids == ()
